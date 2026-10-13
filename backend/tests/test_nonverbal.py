"""nonverbal.py testleri — gerçek tepki kayıtları (v4 sözleşmesi, bölüm 2).

Gerçek kayıt yerine tohumlu sentetik "gülme" kullanılır: 300 ms'lik darbeler (500–3500 Hz bant geçiren gürültü +
180 Hz ton, sin² zarf), aralarında sessizlik ve -70 dBFS taban gürültüsü. Perde ölçümünde saf ton yerine harmonikli,
vibratolu bir "ses" kullanılır: faz vokoderleri (rubberband) durağan saf tonda perdeyi yanlış kaydırabiliyor, gerçek
seste bu olmuyor.
"""
import math
import shutil
import subprocess

import librosa
import numpy as np
import pytest
import soundfile as sf
from scipy import signal

from app import nonverbal as nv
from app.emotion import NONVERBAL, PAUSE_TAGS, resolve
from app.tr import tr_capitalize

SR = 24000
FFMPEG_VAR = shutil.which("ffmpeg") is not None
ffmpeg_gerekli = pytest.mark.skipif(not FFMPEG_VAR, reason="ffmpeg yok")
TEMPO_ALT, TEMPO_UST = 1 / 1.03, 1 / 0.97              # çıktı/girdi uzunluk oranı sınırları (tempo ±3 %)
PERDE_ALT, PERDE_UST = 2 ** (-0.3 / 12), 2 ** (0.3 / 12)   # perde oranı sınırları (±0.3 yarım ton)
SOZLESME_ANAHTARLARI = ("gülme", "kahkaha", "kıkırdama", "iç çekme", "hmm", "of", "nefes verir", "öksürür",
                        "boğaz temizler", "esner", "ağlar", "şaşırır", "hıh", "mmm", "cık")


# ---------- yardımcılar ----------

def sentetik_gulme(genlikler=(0.5, 0.5, 0.5), darbe_s=0.3, aralik_s=0.15, bas_s=0.5, son_s=0.5, sr=SR, tohum=0):
    """Gülme benzeri sinyal: her darbe sin² zarflı (180 Hz ton + bant geçiren gürültü), darbeler arası sessizlik."""
    rng = np.random.default_rng(tohum)
    sos = signal.butter(4, [500, 3500], btype="bandpass", fs=sr, output="sos")
    parcalar = [np.zeros(int(bas_s * sr))]
    for i, g in enumerate(genlikler):
        n = int(darbe_s * sr)
        t = np.arange(n) / sr
        gurultu = signal.sosfilt(sos, rng.standard_normal(n))
        gurultu /= np.max(np.abs(gurultu))
        zarf = np.sin(np.pi * t / darbe_s) ** 2
        parcalar.append(g * zarf * (0.6 * np.sin(2 * np.pi * 180 * t) + 0.4 * gurultu))
        if i < len(genlikler) - 1:
            parcalar.append(np.zeros(int(aralik_s * sr)))
    parcalar.append(np.zeros(int(son_s * sr)))
    y = np.concatenate(parcalar)
    y = y + 10 ** (-70 / 20) * rng.standard_normal(y.size)
    return y.astype(np.float32)


def harmonik_ses(f0=180.0, sure_s=1.5, sr=SR):
    """Konuşma benzeri harmonik dizisi (1/k), 5 Hz'de %3 vibrato."""
    t = np.arange(int(sure_s * sr)) / sr
    faz = 2 * np.pi * np.cumsum(f0 * (1 + 0.03 * np.sin(2 * np.pi * 5 * t))) / sr
    x = sum(np.sin(k * faz) / k for k in range(1, 30) if k * f0 * 1.05 < sr / 2)
    return (0.3 * x / np.max(np.abs(x))).astype(np.float32)


def rms_db(x) -> float:
    x = np.asarray(x, dtype=np.float64)
    return 20 * math.log10(math.sqrt(float(np.mean(x * x))) + 1e-12)


def tepe_db(x) -> float:
    return 20 * math.log10(float(np.max(np.abs(x))) + 1e-12)


def kare_guc(x, sr=SR, ms=10):
    f = int(sr * ms / 1000)
    n = len(x) // f
    return np.mean(np.asarray(x[: n * f], dtype=np.float64).reshape(n, f) ** 2, axis=1)


def darbeler(x, sr=SR, esik_db=20.0) -> list[float]:
    """En gür kareye göre esik_db içindeki ardışık 10 ms kare grupları (darbeler) → her birinin ortalama gücü (dB)."""
    p = kare_guc(x, sr)
    acik = p > p.max() * 10 ** (-esik_db / 10)
    sonuc, i = [], 0
    while i < len(p):
        if acik[i]:
            j = i
            while j < len(p) and acik[j]:
                j += 1
            sonuc.append(10 * math.log10(float(np.mean(p[i:j]))))
            i = j
        else:
            i += 1
    return sonuc


def baskin_frekans(x, sr=SR) -> float:
    sp = np.abs(np.fft.rfft(np.asarray(x, dtype=np.float64) * np.hanning(len(x))))
    return float(np.argmax(sp)) * sr / len(x)


def medyan_f0(y, sr=SR) -> float:
    f = librosa.yin(np.asarray(y, dtype=np.float32), fmin=80, fmax=600, sr=sr, frame_length=2048)
    return float(np.median(f[5:-5]))


def yaz(yol, x, sr=SR):
    sf.write(str(yol), x, sr)
    return yol


def oku(yol):
    y, sr = sf.read(str(yol), dtype="float32", always_2d=False)
    return y, sr


def ffmpeg_yok(monkeypatch):
    """shutil.which("ffmpeg") → None (diğer araçlar etkilenmez)."""
    gercek = shutil.which
    monkeypatch.setattr(shutil, "which", lambda ad, *a, **k: None if ad == "ffmpeg" else gercek(ad, *a, **k))


@pytest.fixture(scope="module")
def hazir_gulme(tmp_path_factory):
    """prepare_nonverbal'dan geçmiş sentetik gülme: (yol, süre)."""
    d = tmp_path_factory.mktemp("nonverbal")
    sure = nv.prepare_nonverbal(yaz(d / "gulme_ham.wav", sentetik_gulme()), d / "gulme.wav")
    return d / "gulme.wav", sure


# ---------- anahtarlar, yönergeler, katalog ----------

def test_anahtarlar_sozlesmedeki_15_anahtar():
    assert nv.NONVERBAL_KEYS == SOZLESME_ANAHTARLARI
    assert isinstance(nv.NONVERBAL_KEYS, tuple) and len(set(nv.NONVERBAL_KEYS)) == 15
    for k in nv.NONVERBAL_KEYS:
        assert NONVERBAL.get(k), k            # kayıt yoksa okunacak ünlem emotion.NONVERBAL'da var


def test_kayit_yonergeleri():
    assert set(nv.NONVERBAL_SCRIPTS) == set(nv.NONVERBAL_KEYS)
    for k, metin in nv.NONVERBAL_SCRIPTS.items():
        assert 30 <= len(metin) <= 200, k
        assert "saniye" in metin, k          # her yönergede süre ipucu var
    assert "kahkaha" in nv.NONVERBAL_SCRIPTS["gülme"] and "Zorlama" in nv.NONVERBAL_SCRIPTS["gülme"]


def test_katalog_ve_yedek_okunus():
    kat = nv.nonverbal_catalog()
    assert [x["key"] for x in kat] == list(nv.NONVERBAL_KEYS)
    for x in kat:
        assert set(x) == {"key", "label", "script", "aliases"}
        assert x["label"] == tr_capitalize(x["label"]) and x["label"][0].isupper(), x["label"]
        assert x["script"] == nv.NONVERBAL_SCRIPTS[x["key"]]
        assert x["key"] in x["aliases"]
        assert nv.fallback_text(x["key"]) == NONVERBAL[x["key"]]
    etiket = {x["key"]: x["label"] for x in kat}
    assert etiket["iç çekme"] == "İç çekme" and etiket["öksürür"] == "Öksürük" and etiket["gülme"] == "Gülme"
    assert nv.fallback_text("gülme") == "Hahaha!"
    assert nv.fallback_text("chuckles") == "Heh heh."           # eş adın kendi okunuşu
    assert nv.fallback_text("[KAHKAHA ATAR]") == "Hahahaha!"
    assert nv.fallback_text("hahahahaha") == "Hahaha!"          # kalıp → anahtarın okunuşu
    assert nv.fallback_text("bilinmeyen") == "" and nv.fallback_text("nefes") == "" and nv.fallback_text(None) == ""


# ---------- sample_key ----------

@pytest.mark.parametrize("etiket, anahtar", [
    ("laughs", "gülme"), ("güler", "gülme"), ("gülüyor", "gülme"), ("kahkaha atar", "kahkaha"),
    ("kıkırdar", "kıkırdama"), ("chuckles", "kıkırdama"), ("sighs", "iç çekme"), ("iç çeker", "iç çekme"),
    ("ağlıyor", "ağlar"), ("cries", "ağlar"), ("coughs", "öksürür"), ("clears throat", "boğaz temizler"),
    ("yawns", "esner"), ("exhales", "nefes verir"), ("nefes verme", "nefes verir"), ("hmm", "hmm"), ("hm", "hmm"),
    ("mmm", "mmm"), ("cık cık", "cık"), ("hıhı", "hıh"), ("hı hı", "hıh"), ("pff", "of"), ("vay canına", "şaşırır"),
    ("gasps", "şaşırır"), ("ehem", "boğaz temizler"), ("sobs", "ağlar"), ("giggles", "kıkırdama"),
    ("kıs kıs güler", "kıkırdama"), ("esneme", "esner"), ("öksürük", "öksürür"),
])
def test_sample_key_es_adlar(etiket, anahtar):
    assert nv.sample_key(etiket) == anahtar


def test_sample_key_anahtarlar_kendine_doner():
    for k in nv.NONVERBAL_KEYS:
        assert nv.sample_key(k) == k


def test_sample_key_emotion_nonverbal_kapsami():
    """emotion.NONVERBAL'da okunuşu bir anahtarınkiyle aynı olan her eş ad o anahtara eşlenir."""
    okunus = {NONVERBAL[k]: k for k in nv.NONVERBAL_KEYS}
    assert len(okunus) == 15                  # anahtarların okunuşları birbirinden farklı
    sayac = 0
    for es_ad, metin in NONVERBAL.items():
        if metin in okunus:
            assert nv.sample_key(es_ad) == okunus[metin], es_ad
            sayac += 1
    assert sayac >= 50


def test_sample_key_buyuk_harf_ascii_ve_yazim_bicimleri():
    assert nv.sample_key("LAUGHS") == "gülme"
    assert nv.sample_key("SIGHS") == "iç çekme"                 # tr_lower 'sıghs' verir; ASCII yedeği eşler
    assert nv.sample_key("İÇ ÇEKME") == "iç çekme" and nv.sample_key("Kahkaha  Atar") == "kahkaha"
    assert nv.sample_key("gulme") == "gülme" and nv.sample_key("ic cekme") == "iç çekme"
    assert nv.sample_key("oksurur") == "öksürür" and nv.sample_key("bogaz temizler") == "boğaz temizler"
    assert nv.sample_key("[gülme]") == "gülme" and nv.sample_key("(kıkırdar)") == "kıkırdama"
    assert nv.sample_key("*laughs*") == "gülme" and nv.sample_key("gülme!") == "gülme"
    assert nv.sample_key("clears-throat") == "boğaz temizler" and nv.sample_key("iç_çekme") == "iç çekme"
    assert nv.sample_key("uh-huh") == "hıh"
    assert nv.sample_key("hmmmm") == "hmm" and nv.sample_key("offff") == "of" and nv.sample_key("mmmmm") == "mmm"
    assert nv.sample_key("gu\u0308lme") == "gülme"              # NFD (macOS) yazımı
    assert nv.sample_key("hahahahaha") == "gülme" and nv.sample_key("ha ha ha") == "gülme"
    assert nv.sample_key("hihihihi") == "kıkırdama" and nv.sample_key("hehehe") == "kıkırdama"
    assert nv.sample_key("derin bir iç çekme") == "iç çekme" and nv.sample_key("hafif gülme") == "gülme"
    assert nv.sample_key("gülme:2") == "gülme" and nv.sample_key("öksürük sesi") == "öksürür"
    assert nv.sample_key("laughs softly") == "gülme" and nv.sample_key("deep sigh") == "iç çekme"


@pytest.mark.parametrize("etiket", [
    "nefes", "derin nefes", "nefes alır", "breath", "takes a breath", "kısa duraklama", "uzun duraklama", "duraklama",
    "pause", "sessizlik", "...", "1.5 sn", "[500 ms]", "2 saniye", "kısa nefes", "uzun sessizlik",
])
def test_sample_key_duraklama_etiketleri_none(etiket):
    assert nv.sample_key(etiket) is None


@pytest.mark.parametrize("etiket", [
    "mutlu", "heyecanlı", "fısıltı", "tüh", "aman", "şey", "evet evet", "ıslık", "sniffs", "ııı", "inler", "hums",
    "hıçkırır", "bilinmeyen etiket", "", "   ", "ha", "çok", None, 42,
])
def test_sample_key_eslesmeyen_none(etiket):
    assert nv.sample_key(etiket) is None


def test_emotion_kanonik_gruplariyla_tutarli():
    """emotion.py'nin kanonik sözsüz adları (keep_nonverbal bölümleri) ile sample_key aynı kararı verir: kaydedilebilir
    gruptaki her eş ad o anahtara, kaydedilemeyen gruptakiler None'a eşlenir."""
    from app import emotion
    kanon = getattr(emotion, "NONVERBAL_CANON", None)
    if not kanon:
        pytest.skip("emotion.NONVERBAL_CANON henüz yok")
    for es_ad, ad in kanon.items():
        beklenen = ad if ad in nv.NONVERBAL_KEYS else None
        assert nv.sample_key(es_ad) == beklenen, (es_ad, ad)
    assert set(nv.NONVERBAL_KEYS) <= set(kanon.values())


def test_es_adlar_tekil_ve_duygu_duraklama_ile_cakismaz():
    assert set(nv.NONVERBAL_ALIASES) == set(nv.NONVERBAL_KEYS)
    gorulen: dict[str, str] = {}
    for k, es_adlar in nv.NONVERBAL_ALIASES.items():
        assert k in es_adlar
        for a in es_adlar:
            assert a not in gorulen, (a, k, gorulen.get(a))    # bir eş ad yalnızca bir anahtara ait
            gorulen[a] = k
            assert resolve(a) is None, a                        # duygu profiliyle karışmaz
            assert a not in PAUSE_TAGS, a
            assert nv.sample_key(a) == k, a


# ---------- veritabanı anahtarı ----------

def test_db_key_gidis_donus():
    for k in nv.NONVERBAL_KEYS:
        d = nv.db_key(k)
        assert d == "nv:" + k and nv.is_db_key(d) and nv.key_of_db(d) == k
    assert nv.db_key("gülme") == "nv:gülme"
    assert nv.db_key("laughs") == "nv:gülme" and nv.db_key("nv:gülme") == "nv:gülme"
    assert not nv.is_db_key("gülme") and not nv.is_db_key("mutlu") and not nv.is_db_key("nv:")
    assert not nv.is_db_key(None)
    assert nv.key_of_db("mutlu") == "mutlu"                     # duygu örnekleri olduğu gibi
    for kotu in ("mutlu", "", "nefes", "nv:bilinmeyen", None):
        with pytest.raises(ValueError, match="Bilinmeyen sözsüz tepki"):
            nv.db_key(kotu)


# ---------- prepare_nonverbal ----------

def test_prepare_sentetik_gulme(hazir_gulme):
    yol, sure = hazir_gulme
    y, sr = oku(yol)
    assert sr == SR and y.ndim == 1
    assert sure == pytest.approx(len(y) / SR, abs=1e-9)
    # 3 darbe × 0.3 sn + 2 boşluk × 0.15 sn = 1.2 sn; baştaki/sondaki 0.5 sn sessizlik kırpılır (30 ms pay kalır)
    assert 1.15 <= sure <= 1.32
    assert rms_db(y) == pytest.approx(-22.0, abs=0.3)
    assert tepe_db(y) <= -1.0 + 1e-3
    assert y[0] == 0.0 and y[-1] == 0.0                          # uçlar fade ile sıfır
    assert len(darbeler(y)) == 3                                 # üç darbe de yerinde


def test_prepare_fade_15_ms(tmp_path):
    t = np.arange(SR) / SR
    x = (0.3 * np.sin(2 * np.pi * 180 * t)).astype(np.float32)   # baştan sona ses: kırpılacak sessizlik yok
    sure = nv.prepare_nonverbal(yaz(tmp_path / "ton.wav", x), tmp_path / "ton_out.wav")
    y, _ = oku(tmp_path / "ton_out.wav")
    assert sure == pytest.approx(1.0, abs=1e-6)
    orta = slice(SR // 4, 3 * SR // 4)
    kazanc = float(np.dot(y[orta], x[orta]) / np.dot(x[orta], x[orta]))
    n = int(0.015 * SR)                                          # 15 ms = 360 örnek
    for bolum, beklenen in ((slice(0, n + 200), np.clip(np.arange(n + 200) / (n - 1), 0, 1)),
                            (slice(SR - n - 200, SR), np.clip(np.arange(n + 200)[::-1] / (n - 1), 0, 1))):
        gecerli = np.abs(x[bolum]) > 0.1                         # sıfır geçişlerinde oran tanımsız
        rampa = y[bolum][gecerli] / (kazanc * x[bolum][gecerli])
        assert np.allclose(rampa, beklenen[gecerli], atol=0.01)  # doğrusal 15 ms fade-in / fade-out


@pytest.mark.parametrize("dizilim", ["orta", "bas", "son"])
def test_prepare_uzun_girdi_en_enerjik_bolge(tmp_path, dizilim):
    gur = [0.5] * 4
    genlikler = {"orta": [0.25] * 5 + gur + [0.25] * 3, "bas": gur + [0.25] * 8, "son": [0.25] * 8 + gur}[dizilim]
    x = sentetik_gulme(genlikler, aralik_s=0.16, bas_s=0.3, son_s=0.3)
    assert len(x) / SR > 5.9                                     # ~6 sn girdi
    sure = nv.prepare_nonverbal(yaz(tmp_path / "uzun.wav", x), tmp_path / "uzun_out.wav")
    y, _ = oku(tmp_path / "uzun_out.wav")
    assert sure <= 3.0 and len(y) <= 3 * SR
    assert sure >= 2.0                                           # gereksiz yere kısaltılmadı
    d = darbeler(y)
    assert sum(1 for v in d if v > max(d) - 3) == 4              # +6 dB'lik dört darbenin dördü de seçildi
    assert 4 < len(d) < 12
    p = kare_guc(y, ms=20)
    assert 10 * math.log10(p[0] / p.max()) < -25                 # sınırlar sessizliğe denk geldi
    assert 10 * math.log10(p[-1] / p.max()) < -25


def test_prepare_surekli_uzun_ses_kesilir(tmp_path):
    t = np.arange(6 * SR) / SR
    x = (0.3 * (0.6 + 0.4 * np.sin(2 * np.pi * 0.5 * t)) * np.sin(2 * np.pi * 180 * t)).astype(np.float32)
    sure = nv.prepare_nonverbal(yaz(tmp_path / "surekli.wav", x), tmp_path / "surekli_out.wav")
    assert 2.4 <= sure <= 3.0


def test_prepare_cok_kisa_ya_da_sessiz(tmp_path):
    dst = tmp_path / "out.wav"
    t = np.arange(int(0.1 * SR)) / SR
    with pytest.raises(ValueError, match="^Kayıt çok kısa$"):
        nv.prepare_nonverbal(yaz(tmp_path / "kisa.wav", (0.3 * np.sin(2 * np.pi * 180 * t)).astype(np.float32)), dst)
    assert not dst.exists()
    # 1 sn sessizlik içinde 40 ms'lik ses: kırpılınca 0.15 sn'nin altında kalır
    x = np.zeros(SR, dtype=np.float32)
    n = int(0.04 * SR)
    x[SR // 2: SR // 2 + n] = 0.3 * np.sin(2 * np.pi * 180 * np.arange(n) / SR)
    with pytest.raises(ValueError, match="^Kayıt çok kısa$"):
        nv.prepare_nonverbal(yaz(tmp_path / "tik.wav", x), dst)
    assert not dst.exists()
    sessiz = (10 ** (-60 / 20) * np.random.default_rng(1).standard_normal(SR)).astype(np.float32)
    with pytest.raises(ValueError, match="sessiz"):
        nv.prepare_nonverbal(yaz(tmp_path / "sessiz.wav", sessiz), dst)
    assert not dst.exists()


def test_prepare_48k_stereo_girdi(tmp_path):
    x48 = sentetik_gulme(sr=48000)
    sure = nv.prepare_nonverbal(yaz(tmp_path / "s48.wav", np.stack([x48, 0.5 * x48], axis=1), sr=48000),
                                tmp_path / "s48_out.wav")
    y, sr = oku(tmp_path / "s48_out.wav")
    assert sr == SR and y.ndim == 1
    assert 1.15 <= sure <= 1.32
    assert rms_db(y) == pytest.approx(-22.0, abs=0.3)


def test_prepare_ffmpeg_olmadan(tmp_path, monkeypatch):
    ffmpeg_yok(monkeypatch)
    assert shutil.which("ffmpeg") is None
    sure = nv.prepare_nonverbal(yaz(tmp_path / "g.wav", sentetik_gulme()), tmp_path / "g_out.wav")
    y, sr = oku(tmp_path / "g_out.wav")
    assert sr == SR and 1.15 <= sure <= 1.32
    assert rms_db(y) == pytest.approx(-22.0, abs=0.3)


# ---------- render_nonverbal ----------

@ffmpeg_gerekli
def test_render_ayni_seed_ayni_cikti(hazir_gulme):
    yol, _ = hazir_gulme
    a = nv.render_nonverbal(yol, SR, seed=7)
    assert a.dtype == np.float32 and a.ndim == 1 and np.all(np.isfinite(a))
    assert np.array_equal(a, nv.render_nonverbal(yol, SR, seed=7))
    c = nv.render_nonverbal(yol, SR, seed=8)
    assert not (len(a) == len(c) and np.array_equal(a, c))


@ffmpeg_gerekli
def test_render_mikro_varyasyon_sinirlari(hazir_gulme):
    yol, _ = hazir_gulme
    giris, _ = oku(yol)
    seviyeler, oranlar = [], []
    for s in range(8):
        y = nv.render_nonverbal(yol, SR, seed=s)
        seviyeler.append(rms_db(y))
        oranlar.append(len(y) / len(giris))
        assert tepe_db(y) <= -1.0 + 1e-4
        assert y[0] == 0.0 and y[-1] == 0.0                      # 10 ms fade
    assert all(abs(v + 22.0) <= 1.5 + 0.01 for v in seviyeler)   # seviye ±1.5 dB
    assert max(seviyeler) - min(seviyeler) > 0.5                 # farklı seed → ölçülebilir RMS farkı
    assert all(TEMPO_ALT - 0.002 <= o <= TEMPO_UST + 0.002 for o in oranlar)   # uzunluk ±3 %
    assert max(oranlar) - min(oranlar) > 0.01                    # tempo gerçekten değişiyor


@ffmpeg_gerekli
@pytest.mark.parametrize("rubberband", [True, False])
def test_render_perde_varyasyonu(tmp_path, monkeypatch, rubberband):
    if rubberband and not nv._has_rubberband():
        pytest.skip("ffmpeg rubberband filtresi yok")
    if not rubberband:
        monkeypatch.setattr(nv, "_has_rubberband", lambda: False)    # asetrate + aresample + atempo yolu
    yol = yaz(tmp_path / "ses.wav", harmonik_ses())
    temel = medyan_f0(oku(yol)[0])
    oranlar = [medyan_f0(nv.render_nonverbal(yol, SR, seed=s)) / temel for s in range(5)]
    assert all(PERDE_ALT - 0.004 <= o <= PERDE_UST + 0.004 for o in oranlar), oranlar   # ±0.3 yarım ton
    assert max(oranlar) - min(oranlar) > 0.01, oranlar


@ffmpeg_gerekli
def test_render_rubberband_yoksa_asetrate_yolu(hazir_gulme, monkeypatch):
    monkeypatch.setattr(nv, "_has_rubberband", lambda: False)
    yol, _ = hazir_gulme
    giris, _ = oku(yol)
    a = nv.render_nonverbal(yol, SR, seed=3)
    assert np.array_equal(a, nv.render_nonverbal(yol, SR, seed=3))
    assert abs(rms_db(a) + 22.0) <= 1.51 and tepe_db(a) <= -1.0 + 1e-4
    oranlar = [len(nv.render_nonverbal(yol, SR, seed=s)) / len(giris) for s in range(4)]
    assert all(TEMPO_ALT - 0.005 <= o <= TEMPO_UST + 0.005 for o in oranlar), oranlar
    assert max(oranlar) - min(oranlar) > 0.005


def test_render_hedef_rms(hazir_gulme):
    yol, _ = hazir_gulme
    for s in range(4):
        assert rms_db(nv.render_nonverbal(yol, SR, target_rms_db=-30.0, seed=s)) == pytest.approx(-30.0, abs=1.51)


def test_render_ffmpeg_olmadan_yalnizca_seviye(hazir_gulme, monkeypatch):
    yol, _ = hazir_gulme
    giris, _ = oku(yol)
    ffmpegli = [rms_db(nv.render_nonverbal(yol, SR, seed=s)) for s in range(4)] if FFMPEG_VAR else None
    ffmpeg_yok(monkeypatch)
    cikti = [nv.render_nonverbal(yol, SR, seed=s) for s in range(4)]
    for y in cikti:
        assert y.dtype == np.float32 and len(y) == len(giris)   # tempo/perde değişmez
        assert abs(rms_db(y) + 22.0) <= 1.51 and tepe_db(y) <= -1.0 + 1e-4
    assert np.array_equal(cikti[0], nv.render_nonverbal(yol, SR, seed=0))
    seviyeler = [rms_db(y) for y in cikti]
    assert max(seviyeler) - min(seviyeler) > 0.5
    if ffmpegli:
        assert seviyeler == pytest.approx(ffmpegli, abs=0.02)    # seviye sapması yoldan bağımsız
    # yalnızca kazanç: ortası girişle orantılı
    orta = slice(int(0.05 * SR), len(giris) - int(0.05 * SR))
    g = float(np.dot(cikti[0][orta], giris[orta]) / np.dot(giris[orta], giris[orta]))
    assert np.allclose(cikti[0][orta], g * giris[orta], atol=1e-5)


def test_render_ffmpeg_hatasinda_yalnizca_seviye(hazir_gulme, monkeypatch):
    yol, _ = hazir_gulme
    giris, _ = oku(yol)

    def bozuk_ffmpeg(*a, **k):
        raise subprocess.CalledProcessError(1, "ffmpeg", stderr=b"filtre hatasi")

    monkeypatch.setattr(shutil, "which", lambda ad, *a, **k: "/usr/bin/ffmpeg")
    monkeypatch.setattr(nv, "_has_rubberband", lambda: True)
    monkeypatch.setattr(subprocess, "run", bozuk_ffmpeg)
    y = nv.render_nonverbal(yol, SR, seed=4)
    assert len(y) == len(giris) and abs(rms_db(y) + 22.0) <= 1.51   # üretim düşmez, yalnızca seviye


def test_render_48k_dosya_24k_cikti(tmp_path, monkeypatch):
    x48 = sentetik_gulme(sr=48000)
    yol = yaz(tmp_path / "g48.wav", x48, sr=48000)
    if FFMPEG_VAR:
        y = nv.render_nonverbal(yol, SR, seed=1)
        assert TEMPO_ALT - 0.003 <= len(y) / (len(x48) / 2) <= TEMPO_UST + 0.003
    ffmpeg_yok(monkeypatch)
    y = nv.render_nonverbal(yol, SR, seed=1)
    assert abs(len(y) - len(x48) / 2) <= 1                      # 48 kHz → 24 kHz: yarı uzunluk
    assert baskin_frekans(y) == pytest.approx(180.0, abs=2.0)    # 180 Hz ton yerinde (doğru sr dönüşümü)


def test_render_kisa_ve_bos_dosya(tmp_path):
    y = nv.render_nonverbal(yaz(tmp_path / "bos.wav", np.zeros(0, dtype=np.float32)), SR, seed=1)
    assert y.dtype == np.float32 and y.size == 0
    t = np.arange(int(0.03 * SR)) / SR
    kisa = yaz(tmp_path / "kisa.wav", (0.2 * np.sin(2 * np.pi * 300 * t)).astype(np.float32))
    y = nv.render_nonverbal(kisa, SR, seed=1)
    assert len(y) == int(0.03 * SR) and np.all(np.isfinite(y))  # çok kısa parçaya tempo/perde uygulanmaz


# ---------- seviyeleme ----------

def test_active_rms_db():
    t = np.arange(SR) / SR
    ton = (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)          # RMS = 0.1/√2 → -23.01 dBFS
    dolgulu = np.concatenate([np.zeros(SR, np.float32), ton, np.zeros(SR, np.float32)])
    assert nv.active_rms_db(ton, SR) == pytest.approx(-23.01, abs=0.05)
    assert nv.active_rms_db(dolgulu, SR) == pytest.approx(-23.01, abs=0.05)   # sessizlik seviyeyi düşürmez
    assert rms_db(dolgulu) < -27.0                                          # (düz RMS düşerdi)
    assert nv.active_rms_db(np.zeros(SR, np.float32), SR) == float("-inf")
    assert nv.active_rms_db(np.zeros(0, np.float32), SR) == float("-inf")


def test_level_match(hazir_gulme):
    yol, _ = hazir_gulme
    parca = nv.render_nonverbal(yol, SR, seed=2)
    y = nv.level_match(parca, SR, -20.0)
    assert y.dtype == np.float32 and len(y) == len(parca)
    assert nv.active_rms_db(y, SR) == pytest.approx(-24.0, abs=0.05)       # komşu konuşmadan 4 dB kısık
    assert tepe_db(y) <= -1.0 + 1e-4
    dolgulu = np.concatenate([np.zeros(SR // 2, np.float32), parca, np.zeros(SR // 2, np.float32)])
    assert nv.active_rms_db(nv.level_match(dolgulu, SR, -20.0), SR) == pytest.approx(-24.0, abs=0.1)
    assert tepe_db(nv.level_match(parca, SR, -3.0)) <= -1.0 + 1e-4         # çok gür komşu: tepe sınırı
    assert nv.active_rms_db(nv.level_match(parca, SR, -20.0, offset_db=0.0), SR) == pytest.approx(-20.0, abs=0.05)
    for yok in (None, float("nan"), float("-inf"), -120.0):                # komşu seviyesi yok → dokunma
        z = nv.level_match(parca, SR, yok)
        assert np.array_equal(z, parca) and z is not parca
    sessiz = np.zeros(SR // 2, dtype=np.float32)
    assert np.array_equal(nv.level_match(sessiz, SR, -20.0), sessiz)
