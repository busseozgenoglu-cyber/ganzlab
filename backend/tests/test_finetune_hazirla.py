"""finetune/hazirla.py testleri — sentetik kayıtlardan LJSpeech kümesi (SOZLESME3 §5).

Kayıtlar ``app.backends.fake.speechlike`` ile üretilir: sözcük benzeri parçalar arasında kısa sessizlikler,
başta/sonda oda tonu. Model ya da torch gerekmez. Toplam ses < 60 sn tutulur (analiz pyin kullandığı için).
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from app.backends.fake import speechlike

_YOL = Path(__file__).resolve().parents[2] / "finetune" / "hazirla.py"
_spec = importlib.util.spec_from_file_location("finetune_hazirla", _YOL)
hazirla = importlib.util.module_from_spec(_spec)
sys.modules["finetune_hazirla"] = hazirla
_spec.loader.exec_module(hazirla)

SR = 24000


# ---------- sentetik kayıt üretimi ----------

def _konusma(sure: float, tohum: int, aralik: float = 9.0, sr: int = SR, oda: float = 0.0003) -> np.ndarray:
    """~``sure`` sn konuşma benzeri sinyal: sözcükler arası 120–250 ms boşluk, baş/son 0,3 sn oda tonu."""
    rng = np.random.default_rng(tohum)
    parcalar = [np.zeros(int(0.3 * sr), np.float32)]
    t, k = 0.0, 0
    while t < sure:
        n = int(rng.integers(8, 14))
        s = speechlike(n, sr, seed=tohum * 100 + k, range_st=aralik, f0_base=140.0 + 10 * (tohum % 5))
        k += 1
        bosluk = np.zeros(int(rng.uniform(0.12, 0.25) * sr), np.float32)
        parcalar += [s, bosluk]
        t += len(s) / sr + len(bosluk) / sr
    parcalar.append(np.zeros(int(0.3 * sr), np.float32))
    x = np.concatenate(parcalar)
    return (x + rng.standard_normal(x.size) * oda).astype(np.float32)


def _kisa(tohum: int) -> np.ndarray:
    """0,4 sn'lik tek "sözcük" + oda tonu."""
    rng = np.random.default_rng(tohum)
    z = np.zeros(int(0.3 * SR), np.float32)
    x = np.concatenate([z, speechlike(5, SR, seed=tohum), z])
    return (x + rng.standard_normal(x.size) * 0.0003).astype(np.float32)


def _gurultulu(tohum: int) -> np.ndarray:
    x = _konusma(1.5, tohum)
    return (x + np.random.default_rng(tohum + 1).standard_normal(x.size) * 0.02).astype(np.float32)


def _kirpik(tohum: int) -> np.ndarray:
    return np.clip(_konusma(1.5, tohum) * 8.0, -1.0, 1.0).astype(np.float32)


def _yaz(path: Path, wav: np.ndarray, sr: int = SR, **kw) -> Path:
    sf.write(str(path), wav, sr, **kw)
    return path


def _nfd(s: str) -> str:
    return unicodedata.normalize("NFD", s)


def _manifest(path: Path, satirlar: list[tuple[str, str, str, str]]) -> Path:
    path.write_text("id|duygu|yogunluk|metin\n" + "".join("|".join(s) + "\n" for s in satirlar), encoding="utf-8")
    return path


def _metadata(path: Path) -> list[list[str]]:
    if not path.exists():
        return []
    return [line.split("|") for line in path.read_text(encoding="utf-8").splitlines()]


# ---------- ortak küme (bir kez hazırlanır) ----------

@pytest.fixture(scope="module")
def kume(tmp_path_factory):
    kok = tmp_path_factory.mktemp("hazirla")
    kay = kok / "kayitlar"
    kay.mkdir()
    _yaz(kay / "normal_0001.wav", _konusma(1.6, 1, aralik=6.0))
    _yaz(kay / "normal_0002.wav", _konusma(1.8, 2, aralik=6.0))
    stereo48 = _konusma(1.8, 3, aralik=16.0, sr=48000)
    _yaz(kay / "mutlu_0001.wav", np.stack([stereo48, stereo48 * 0.8], axis=1), 48000)     # 48 kHz stereo
    _yaz(kay / "mutlu_0002.flac", _konusma(1.6, 4, aralik=16.0))
    _yaz(kay / (_nfd("üzgün_0001") + ".wav"), _konusma(1.6, 5))                       # macOS NFD adı
    _yaz(kay / "kızgın_0001.wav", _gurultulu(6))
    _yaz(kay / "kızgın_0002.wav", _kirpik(7))
    _yaz(kay / "korkmuş_0001.wav", _kisa(8))
    _yaz(kay / "sakin_0001.wav", _konusma(13.6, 9))                                    # ~14 sn
    man = _manifest(kok / "manifest.csv", [
        ("normal_0001", "normal", "normal", "Bugün hava çok güzel."),
        ("normal_0002", "normal", "normal", 'Saat 3\'te geldim | "tamam" dedi.'),
        ("mutlu_0001", "mutlu", "hafif", "Harika bir haber aldım!"),
        ("mutlu_0002", "mutlu", "güçlü", "Sonunda   başardık,  inanamıyorum!"),
        ("üzgün_0001", "üzgün", "hafif", "Keşke daha önce söyleseydin..."),
        ("kızgın_0001", "kızgın", "hafif", "Bu kaçıncı oldu böyle?"),
        ("kızgın_0002", "kızgın", "güçlü", "Yeter artık, dinlemiyorsun!"),
        ("korkmuş_0001", "korkmuş", "hafif", "Sesi duydun mu?"),
        ("sakin_0001", "sakin", "normal", "Uzun bir paragraf okunuyor."),
        ("şaşkın_0001", "şaşkın", "hafif", "Gerçekten mi?"),
    ])
    cikti = kok / "MyTTSDataset"
    rapor = hazirla.prepare(kay, man, cikti, sr=SR, etiket=True, dogrulama=0.5)
    egitim = _metadata(cikti / "metadata.csv")
    val = _metadata(cikti / "metadata_val.csv")
    satirlar = {r[0]: r for r in egitim + val}
    return {"kok": kok, "kayitlar": kay, "cikti": cikti, "rapor": rapor, "egitim": egitim, "val": val,
            "satirlar": satirlar, "red": {r["id"]: r["neden"] for r in rapor["red"]}}


KABUL = {"normal_0001", "normal_0002", "mutlu_0001", "mutlu_0002", "üzgün_0001"}


def test_temiz_kayitlar_kabul_24khz_mono_pcm16(kume):
    assert set(kume["satirlar"]) == KABUL
    for kid in ("normal_0001", "mutlu_0001", "mutlu_0002"):          # mutlu_0001: 48 kHz stereo kaynak
        info = sf.info(str(kume["cikti"] / "wavs" / f"{kid}.wav"))
        assert info.samplerate == SR
        assert info.channels == 1
        assert info.subtype == "PCM_16"
        assert 1.0 <= info.duration <= 12.0


def test_metadata_basliksiz_uc_sutun_uzantisiz(kume):
    satirlar = kume["egitim"] + kume["val"]
    assert satirlar
    for s in satirlar:
        assert len(s) == 3
        assert not s[0].endswith(".wav")
        assert s[0] != "filename" and s[0] != "id"
    ilk = (kume["cikti"] / "metadata.csv").read_text(encoding="utf-8").splitlines()[0]
    assert ilk.split("|")[0] in KABUL
    assert not (kume["cikti"] / "metadata.csv").read_bytes().startswith(b"\xef\xbb\xbf")


def test_gurultulu_kayit_reddedilir(kume):
    assert kume["red"]["kızgın_0001"] == "gürültülü"


def test_kirpilmis_kayit_reddedilir(kume):
    assert kume["red"]["kızgın_0002"] == "kırpılmış"


def test_cok_kisa_kayit_reddedilir(kume):
    assert kume["red"]["korkmuş_0001"] == "çok kısa"


def test_uzun_kayit_bolmesiz_reddedilir(kume):
    assert kume["red"]["sakin_0001"] == "uzun"


def test_reddedilen_ciktiya_kopyalanmaz(kume):
    adlar = {unicodedata.normalize("NFC", p.stem) for p in (kume["cikti"] / "wavs").glob("*.wav")}
    assert adlar == KABUL


def test_eksik_kayit_raporda(kume):
    assert kume["rapor"]["eksik"] == ["şaşkın_0001"]
    assert "şaşkın_0001" not in kume["red"]


def test_etiket_iki_sutunda_normalde_yok(kume):
    for kid in ("mutlu_0001", "mutlu_0002"):
        _, raw, norm = kume["satirlar"][kid]
        assert raw.startswith("[mutlu] ")
        assert norm.startswith("[mutlu] ")
    _, raw, norm = kume["satirlar"]["üzgün_0001"]
    assert raw.startswith("[üzgün] ") and norm.startswith("[üzgün] ")
    for kid in ("normal_0001", "normal_0002"):
        _, raw, norm = kume["satirlar"][kid]
        assert not raw.startswith("[") and not norm.startswith("[")


def test_normalize_sayiyi_aciyor(kume):
    _, raw, norm = kume["satirlar"]["normal_0002"]
    assert "3'te" in raw
    assert "3" not in norm
    assert "üç" in norm


def test_ayirici_ve_bosluk_temizligi(kume):
    _, raw, norm = kume["satirlar"]["normal_0002"]
    assert "|" not in raw and "|" not in norm
    assert '"tamam"' in raw
    _, raw2, _ = kume["satirlar"]["mutlu_0002"]
    assert "  " not in raw2
    for s in (kume["cikti"] / "metadata.csv").read_text(encoding="utf-8").splitlines():
        assert s.count("|") == 2


def test_dogrulama_bolmesi_toplami_korur(kume):
    egitim = {s[0] for s in kume["egitim"]}
    val = {s[0] for s in kume["val"]}
    assert val and egitim
    assert not egitim & val
    assert egitim | val == KABUL
    assert len(val) == round(0.5 * len(KABUL))
    r = kume["rapor"]
    assert r["egitim_adet"] == len(egitim) and r["dogrulama_adet"] == len(val)


def test_dogrulama_secimi_sabit_tohumla_tekrarlanir():
    kabul = [{"id": f"{d}_{i:04d}", "duygu": d} for d in ("mutlu", "normal", "üzgün") for i in range(1, 21)]
    a = hazirla._dogrulama_sec(kabul, 0.1)
    b = hazirla._dogrulama_sec(list(reversed(kabul)), 0.1)
    assert a == b and len(a) == 6
    for d in ("mutlu", "normal", "üzgün"):
        assert sum(1 for x in a if x.startswith(d)) == 2           # duygu başına dengeli
    assert len(hazirla._dogrulama_sec(kabul[:3], 0.01)) == 1         # en az 1


def test_rapor_yeterlilik_ve_dakikalar(kume):
    r = kume["rapor"]
    kayitli = json.loads((kume["cikti"] / "rapor.json").read_text(encoding="utf-8"))
    assert kayitli["kabul"] == r["kabul"] == len(KABUL)
    assert r["yeterlilik"] == "yetersiz (<30 dk)"
    assert r["toplam_dk"] == pytest.approx(r["toplam_sn"] / 60, abs=0.01)
    assert r["toplam_saat"] == pytest.approx(r["toplam_sn"] / 3600, abs=0.001)
    assert sum(v["dakika"] for v in r["duygu"].values()) == pytest.approx(r["toplam_dk"], abs=0.02)
    assert r["duygu"]["mutlu"]["adet"] == 2 and r["duygu"]["normal"]["adet"] == 2
    assert {x["id"] for x in r["red"]} == {"kızgın_0001", "kızgın_0002", "korkmuş_0001", "sakin_0001"}
    assert any("30 dk" in u for u in r["uyarilar"])
    for v in r["duygu"].values():
        assert set(v) == {"adet", "dakika", "range_semitones_medyan", "std_semitones_medyan", "uyari"}


def test_duz_okunan_duygu_uyarisi(kume):
    d = kume["rapor"]["duygu"]
    assert d["mutlu"]["range_semitones_medyan"] >= 12 and d["mutlu"]["uyari"] is None
    assert d["normal"]["range_semitones_medyan"] < 12
    assert "duygusu düz okunmuş, daha ifadeli tekrar kaydedin" in d["normal"]["uyari"]


def test_yeterlilik_esikleri():
    assert hazirla._yeterlilik(29.9) == "yetersiz (<30 dk)"
    assert hazirla._yeterlilik(30.0) == "asgari (30 dk–3 sa)"
    assert hazirla._yeterlilik(180.0) == "iyi (≥3 sa)"


def test_turkce_id_ve_nfd_dosya_adi_eslesir(kume, tmp_path):
    assert "üzgün_0001" in kume["satirlar"]
    assert (kume["cikti"] / "wavs" / "üzgün_0001.wav").exists()          # çıktı adı NFC
    _yaz(tmp_path / (_nfd("gülümseyen_0003") + ".wav"), np.zeros(SR, np.float32))
    _yaz(tmp_path / "Mutlu_0004.WAV", np.zeros(SR, np.float32))
    _yaz(tmp_path / "şaşkın_0005.ogg", np.zeros(SR, np.float32), format="OGG")
    assert hazirla.find_recording(tmp_path, "gülümseyen_0003").name == _nfd("gülümseyen_0003") + ".wav"
    assert hazirla.find_recording(tmp_path, _nfd("gülümseyen_0003")) is not None
    assert hazirla.find_recording(tmp_path, "mutlu_0004").name == "Mutlu_0004.WAV"
    assert hazirla.find_recording(tmp_path, "şaşkın_0005").suffix == ".ogg"
    assert hazirla.find_recording(tmp_path, "yok_0001") is None


def test_manifest_okuma(tmp_path):
    p = tmp_path / "m.csv"
    p.write_text('﻿id|duygu|yogunluk|metin\nmutlu_0001|Mutlu|Güçlü|"Evet" dedi | gitti.\n\n', encoding="utf-8")
    satir = hazirla.read_manifest(p)
    assert satir == [{"id": "mutlu_0001", "duygu": "mutlu", "yogunluk": "güçlü", "metin": '"Evet" dedi gitti.'}]
    p.write_text("ad|metin\nx|y\n", encoding="utf-8")
    with pytest.raises(ValueError, match="başlık"):
        hazirla.read_manifest(p)
    p.write_text("id|duygu|yogunluk|metin\na_0001|normal|normal|x\na_0001|normal|normal|y\n", encoding="utf-8")
    with pytest.raises(ValueError, match="yinelenen"):
        hazirla.read_manifest(p)


def test_manifestsiz_txt_modu(kume, tmp_path):
    kay = tmp_path / "kayitlar"
    kay.mkdir()
    shutil.copy(kume["kayitlar"] / "mutlu_0002.flac", kay / "mutlu_0007.flac")
    (kay / "mutlu_0007.txt").write_text("Bugün 5 kişiyiz!\n", encoding="utf-8")
    shutil.copy(kume["kayitlar"] / "normal_0001.wav", kay / "kayit.wav")
    (kay / "kayit.txt").write_text("Merhaba,\nnasılsın?", encoding="utf-8")
    shutil.copy(kume["kayitlar"] / "korkmuş_0001.wav", kay / "yalniz.wav")      # .txt yok
    r = hazirla.prepare(kay, None, tmp_path / "out", etiket=True)
    satirlar = {s[0]: s for s in _metadata(tmp_path / "out" / "metadata.csv")}
    assert set(satirlar) == {"mutlu_0007", "kayit"}
    assert satirlar["mutlu_0007"][1] == "[mutlu] Bugün 5 kişiyiz!"
    assert "5" not in satirlar["mutlu_0007"][2] and satirlar["mutlu_0007"][2].startswith("[mutlu] ")
    assert satirlar["kayit"][1] == "Merhaba, nasılsın?"                     # duygu yok → normal, etiketsiz
    assert {x["id"]: x["neden"] for x in r["red"]} == {"yalniz": "transkript yok"}
    assert set(r["duygu"]) == {"mutlu", "normal"}


def test_boleme_transkriptsiz_uzun_kaydi_parcalar(kume, tmp_path):
    kay = tmp_path / "kayitlar"
    kay.mkdir()
    shutil.copy(kume["kayitlar"] / "sakin_0001.wav", kay / "sakin_0001.wav")
    man = _manifest(tmp_path / "manifest.csv", [("sakin_0001", "sakin", "normal", "Uzun metin.")])
    r = hazirla.prepare(kay, man, tmp_path / "out", etiket=True, dogrulama=0.5, boleme=True, transkriptsiz=True)
    # metinsiz parçalar metadata.csv'ye girmez (pandas boş alanı NaN → "nan" metni okurdu)
    assert (tmp_path / "out" / "metadata.csv").read_text(encoding="utf-8") == ""
    assert not (tmp_path / "out" / "metadata_val.csv").exists()
    ham = (tmp_path / "out" / "metadata_transkriptsiz.csv").read_text(encoding="utf-8").splitlines()
    assert len(ham) >= 2
    for satir in ham:
        kid, raw, norm = satir.split("|")
        assert satir.endswith("||") and raw == "" and norm == ""
        assert kid.startswith("sakin_0001_")
        sure = sf.info(str(tmp_path / "out" / "wavs" / f"{kid}.wav")).duration
        assert 2.5 <= sure <= 10.1
    assert r["transkriptsiz_adet"] == len(ham) and r["egitim_adet"] == 0 and r["dogrulama_adet"] == 0
    assert any("Whisper" in u and "metadata.csv'ye ekleyin" in u for u in r["uyarilar"])
    assert "metadata_transkriptsiz.csv" in hazirla.ozet_metni(r, tmp_path / "out")


def test_transkriptsiz_txtsiz_kayit_ayri_dosyaya_metinli_metadataya(kume, tmp_path):
    kay = tmp_path / "kayitlar"
    kay.mkdir()
    shutil.copy(kume["kayitlar"] / "normal_0001.wav", kay / "metinli.wav")
    (kay / "metinli.txt").write_text("Bugün hava güzel.", encoding="utf-8")
    shutil.copy(kume["kayitlar"] / "mutlu_0002.flac", kay / "metinsiz.flac")
    r = hazirla.prepare(kay, None, tmp_path / "out", transkriptsiz=True)
    assert _metadata(tmp_path / "out" / "metadata.csv") == [["metinli", "Bugün hava güzel.", "Bugün hava güzel."]]
    assert (tmp_path / "out" / "metadata_transkriptsiz.csv").read_text(encoding="utf-8") == "metinsiz||\n"
    for satir in (tmp_path / "out" / "metadata.csv").read_text(encoding="utf-8").splitlines():
        assert all(alan.strip() for alan in satir.split("|"))          # boş alan yok
    assert {k["id"]: k["bolum"] for k in r["kabul_edilenler"]} == {"metinli": "egitim", "metinsiz": "transkriptsiz"}


def test_pandas_tuzagi_adlar():
    for ad in ("0001", "12", "1.5", "1e5", "-3", "+7", "nan", "NULL", "None", "True", "inf"):
        assert hazirla.pandas_tuzagi_mi(ad), ad
    for ad in ("mutlu_0001", "kayit", "e", "a1", "üzgün_0012", "1_000"):
        assert not hazirla.pandas_tuzagi_mi(ad), ad


def test_sayisal_kayit_adlari_kayit_oneki_alir(kume, tmp_path):
    kay = tmp_path / "kayitlar"
    kay.mkdir()
    for ad in ("0001", "kayit_0001", "1.5"):
        shutil.copy(kume["kayitlar"] / "normal_0001.wav", kay / f"{ad}.wav")
        (kay / f"{ad}.txt").write_text("Bugün hava güzel.", encoding="utf-8")
    shutil.copy(kume["kayitlar"] / "korkmuş_0001.wav", kay / "0002.wav")        # çok kısa → red
    (kay / "0002.txt").write_text("Kısa.", encoding="utf-8")
    r = hazirla.prepare(kay, None, tmp_path / "out")
    idler = {s[0] for s in _metadata(tmp_path / "out" / "metadata.csv")}
    assert idler == {"kayit_0001", "kayit_0001_2", "kayit_1.5"}               # gerçek kayit_0001 ile çakışmaz
    assert r["id_eslemesi"] == {"0001": "kayit_0001_2", "0002": "kayit_0002", "1.5": "kayit_1.5"}
    assert (tmp_path / "out" / "wavs" / "kayit_0001_2.wav").exists()
    assert not (tmp_path / "out" / "wavs" / "0001.wav").exists()
    assert {x["id"]: x["neden"] for x in r["red"]} == {"0002": "çok kısa"}     # red listesinde kullanıcının adı
    assert any("kayit_" in u and "pandas" in u for u in r["uyarilar"])
    pd = pytest.importorskip("pandas")
    tablo = pd.read_csv(tmp_path / "out" / "metadata.csv", sep="|", header=None, quoting=3)
    assert all(isinstance(v, str) for v in tablo[0])


def test_main_donus_kodlari(kume, tmp_path, capsys):
    iyi = tmp_path / "iyi"
    iyi.mkdir()
    shutil.copy(kume["kayitlar"] / "normal_0001.wav", iyi / "normal_0001.wav")
    (iyi / "normal_0001.txt").write_text("Bugün hava çok güzel.", encoding="utf-8")
    assert hazirla.main(["--kayitlar", str(iyi), "--cikti", str(tmp_path / "o1")]) == 0
    assert "Toplam ses" in capsys.readouterr().out

    kotu = tmp_path / "kotu"
    kotu.mkdir()
    shutil.copy(kume["kayitlar"] / "kızgın_0001.wav", kotu / "kızgın_0001.wav")
    man = _manifest(tmp_path / "m.csv", [("kızgın_0001", "kızgın", "hafif", "Bu kaçıncı oldu?")])
    assert hazirla.main(["--kayitlar", str(kotu), "--manifest", str(man), "--cikti", str(tmp_path / "o2")]) == 2
    assert "kabul edilmedi" in capsys.readouterr().err

    assert hazirla.main(["--kayitlar", str(tmp_path / "yok"), "--cikti", str(tmp_path / "o3")]) == 1
    hata = capsys.readouterr().err
    assert "kayıt klasörü bulunamadı" in hata
    assert hazirla.main(["--kayitlar", str(iyi), "--manifest", str(tmp_path / "yok.csv"),
                         "--cikti", str(tmp_path / "o4")]) == 1
    assert "manifest bulunamadı" in capsys.readouterr().err
