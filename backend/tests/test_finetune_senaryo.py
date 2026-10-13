"""finetune/senaryo.py — kayıt senaryosu üretici (SOZLESME3 §4).

Modül paket değildir; dosya yolundan ``importlib`` ile yüklenir. Gerçek banka (finetune/cumleler) başka ajanlarca
yazıldığından testler kendi geçici bankasını ``tmp_path``'te kurar.
"""
from __future__ import annotations

import csv
import importlib.util
import re
from pathlib import Path

import pytest

SENARYO_YOLU = Path(__file__).resolve().parents[2] / "finetune" / "senaryo.py"
_spec = importlib.util.spec_from_file_location("finetune_senaryo", SENARYO_YOLU)
senaryo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(senaryo)

ID_RE = re.compile(r"^[a-zçğıöşü]+_\d{4}$")


# ---------- yardımcılar ----------

def cumleler_uret(onek: str, adet: int = 30) -> list[str]:
    """Birbirinden farklı, 5–8 sözcüklük, noktalamayla biten cümleler."""
    sonlar = [".", "!", "?", "..."]
    return [f"{onek} bugün {i}. kez yine aynı yoldan geçti{sonlar[i % 4]}" for i in range(1, adet + 1)]


def dosya_yaz(klasor: Path, duygu: str, cumleler: list[str], yonerge: str | None = "Doğal oku.",
              ornek: str | None = "Böyle söyle.") -> Path:
    satirlar = []
    if yonerge is not None:
        satirlar.append(f"# yönerge: {yonerge}")
    if ornek is not None:
        satirlar.append(f"# örnek: {ornek}")
    satirlar.append("# sıradan bir yorum satırı")
    satirlar += cumleler
    path = klasor / f"{duygu}.txt"
    path.write_text("\n".join(satirlar) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def banka(tmp_path: Path) -> Path:
    """Temiz banka: normal, mutlu, üzgün (her biri 30 cümle)."""
    klasor = tmp_path / "cumleler"
    klasor.mkdir()
    dosya_yaz(klasor, "normal", cumleler_uret("Komşumuz"), yonerge="Nötr ve doğal oku.")
    dosya_yaz(klasor, "mutlu", cumleler_uret("Kardeşim"), yonerge="Gülümseyerek oku.", ornek="Ne güzel!")
    dosya_yaz(klasor, "üzgün", cumleler_uret("Yaşlı adam"), yonerge="Yavaş ve alçak oku.", ornek="Keşke...")
    return klasor


def satirlar(manifest: list[dict], duygu: str) -> list[dict]:
    return [r for r in manifest if r["duygu"] == duygu]


# ---------- load_bank ----------

def test_load_bank_yonerge_ornek_ve_cumleleri_okur(banka):
    b = senaryo.load_bank(banka)
    assert set(b) == {"normal", "mutlu", "üzgün"}
    assert b["mutlu"]["yonerge"] == "Gülümseyerek oku."
    assert b["mutlu"]["ornek"] == "Ne güzel!"
    assert len(b["mutlu"]["cumleler"]) == 30
    assert all(not c.startswith("#") for c in b["mutlu"]["cumleler"])


def test_load_bank_turkce_karakterli_dosya_adi_duygu_olur(tmp_path):
    for ad in ("üzgün", "kızgın", "fısıltı", "sıkılmış"):
        dosya_yaz(tmp_path, ad, cumleler_uret("Biri", 3))
    b = senaryo.load_bank(tmp_path)
    assert set(b) == {"üzgün", "kızgın", "fısıltı", "sıkılmış"}


def test_load_bank_bos_satir_ve_bom(tmp_path):
    (tmp_path / "sakin.txt").write_text("﻿# yönerge: Yavaş.\n\n  Derin bir nefes alalım şimdi.  \n\n",
                                        encoding="utf-8")
    b = senaryo.load_bank(tmp_path)
    assert b["sakin"] == {"yonerge": "Yavaş.", "ornek": "", "cumleler": ["Derin bir nefes alalım şimdi."]}


def test_load_bank_klasor_yoksa_bos(tmp_path):
    assert senaryo.load_bank(tmp_path / "yok") == {}


# ---------- split_sentences ----------

def test_split_kisaltmalari_bolmez():
    assert senaryo.split_sentences("Dr. Ayşe geldi. Sonra gitti.") == ["Dr. Ayşe geldi.", "Sonra gitti."]


def test_split_cesitli_kisaltmalar_ve_sira_sayisi():
    metin = "T.C. Sağlık Bakanlığı açıkladı. Prof. Dr. Ali, vb. konuları anlattı. 3. kattaki ofise geçtik!"
    assert senaryo.split_sentences(metin) == [
        "T.C. Sağlık Bakanlığı açıkladı.", "Prof. Dr. Ali, vb. konuları anlattı.", "3. kattaki ofise geçtik!"]


def test_split_kucuk_harfle_suren_yerden_bolmez():
    assert senaryo.split_sentences('"Gel buraya!" dedi annem bana gülerek.') == ['"Gel buraya!" dedi annem bana gülerek.']


def test_split_uzun_cumleyi_virgulden_boler():
    uzun = ("Sabah erkenden kalktık, kahvaltımızı yaptık, çantalarımızı topladık, arabaya bindik, uzun bir yola "
            "çıktık, yolda iki kez mola verdik, akşam olmadan köye vardık, herkes bizi kapıda karşıladı ve çok sevindik.")
    parcalar = senaryo.split_sentences(uzun)
    assert len(parcalar) >= 2
    for p in parcalar:
        assert 4 <= senaryo._sozcuk_sayisi(p) <= 25
        assert p.endswith((".", "!", "?"))
        assert not p.rstrip(".").endswith(",")
    assert " ".join(parcalar).count("kalktık") == 1


def test_split_virgulsuz_uzun_cumle_sozcukten_bolunur():
    uzun = " ".join(f"sözcük{i}" for i in range(60)) + "."
    parcalar = senaryo.split_sentences(uzun)
    assert len(parcalar) == 3
    assert all(senaryo._sozcuk_sayisi(p) <= 25 for p in parcalar)


def test_split_cok_kisa_parcayi_oncekine_ekler():
    assert senaryo.split_sentences("Bu uzun bir cümle olarak burada duruyor. Evet.") == [
        "Bu uzun bir cümle olarak burada duruyor. Evet."]
    # ilk parça kısaysa sonrakine eklenir
    assert senaryo.split_sentences("Hayır! Bunu asla kabul etmeyeceğim, anladın mı?") == [
        "Hayır! Bunu asla kabul etmeyeceğim, anladın mı?"]


def test_split_basliklari_atlar_ve_diyalog_cizgisini_temizler():
    metin = "BİRİNCİ BÖLÜM\n\n— Nereye gidiyorsun bu saatte?\n\n— Eve dönüyorum artık, çok yoruldum."
    assert senaryo.split_sentences(metin) == ["Nereye gidiyorsun bu saatte?", "Eve dönüyorum artık, çok yoruldum."]


def test_split_bos_metin():
    assert senaryo.split_sentences("") == []
    assert senaryo.split_sentences("   \n\n ") == []


# ---------- build_manifest ----------

def test_build_manifest_id_bicimi_ve_sira(banka):
    m = senaryo.build_manifest(senaryo.load_bank(banka))
    assert len(m) == 90
    assert all(ID_RE.match(r["id"]) for r in m)
    assert len({r["id"] for r in m}) == len(m)
    uz = satirlar(m, "üzgün")
    assert [r["id"] for r in uz[:3]] == ["üzgün_0001", "üzgün_0002", "üzgün_0003"]
    assert all(r["yogunluk"] == "normal" for r in m)
    assert set(m[0]) >= {"id", "duygu", "yogunluk", "metin"}


def test_build_manifest_tekrar_2_iki_yogunluk(banka):
    m = senaryo.build_manifest(senaryo.load_bank(banka), tekrar=2)
    mutlu = satirlar(m, "mutlu")
    assert len(mutlu) == 60
    assert {r["yogunluk"] for r in mutlu} == {"hafif", "güçlü"}
    assert mutlu[0]["metin"] == mutlu[1]["metin"]
    assert (mutlu[0]["yogunluk"], mutlu[1]["yogunluk"]) == ("hafif", "güçlü")
    assert (mutlu[0]["id"], mutlu[1]["id"]) == ("mutlu_0001", "mutlu_0002")
    assert all(ID_RE.match(r["id"]) for r in m)
    # normal duygu yoğunluk taşımaz: tekrar edilmez
    assert len(satirlar(m, "normal")) == 30
    assert {r["yogunluk"] for r in satirlar(m, "normal")} == {"normal"}


def test_build_manifest_duygular_suzer(banka):
    b = senaryo.load_bank(banka)
    m = senaryo.build_manifest(b, duygular=["üzgün"])
    assert {r["duygu"] for r in m} == {"üzgün"}
    m2 = senaryo.build_manifest(b, duygular="mutlu, uzgun, yok")      # ASCII yazım da eşleşir
    assert [d for d in dict.fromkeys(r["duygu"] for r in m2)] == ["mutlu", "üzgün"]


def test_build_manifest_ek_metin_normale_eklenir(banka):
    b = senaryo.load_bank(banka)
    ek = "Kitabın ilk cümlesi burada başlıyor. İkinci cümle de hemen ardından geliyor."
    m = senaryo.build_manifest(b, ek_metin=ek)
    normal = satirlar(m, "normal")
    assert len(normal) == 32
    assert normal[-2]["metin"] == "Kitabın ilk cümlesi burada başlıyor."
    assert normal[-1]["id"] == "normal_0032"
    # bankada normal yoksa da eklenir
    m2 = senaryo.build_manifest(b, duygular=["mutlu"], ek_metin=["Tek bir ek cümle burada."])
    assert satirlar(m2, "normal")[0]["id"] == "normal_0001"


def test_build_manifest_ayiriciyi_temizler():
    b = {"mutlu": {"yonerge": "", "ornek": "", "cumleler": ["Bu | işaret  manifesti\tbozmasın."]}}
    assert senaryo.build_manifest(b)[0]["metin"] == "Bu / işaret manifesti bozmasın."


# ---------- plan_sessions ----------

def _yapay_manifest(sayilar: dict[str, int]) -> list[dict]:
    m = []
    for duygu, n in sayilar.items():
        m += [{"id": f"{duygu}_{i:04d}", "duygu": duygu, "yogunluk": "normal", "metin": f"cümle {i}."}
              for i in range(1, n + 1)]
    return m


def _bolunen_duygular(oturumlar: list[list[dict]]) -> set[str]:
    yer: dict[str, set[int]] = {}
    for i, o in enumerate(oturumlar):
        for r in o:
            yer.setdefault(r["duygu"], set()).add(i)
    return {d for d, s in yer.items() if len(s) > 1}


def test_plan_sessions_120_siniri_ve_duygular_bolunmez():
    m = _yapay_manifest({"normal": 30, "mutlu": 60, "üzgün": 60, "kızgın": 60, "sakin": 30})
    oturumlar = senaryo.plan_sessions(m)
    assert all(len(o) <= 120 for o in oturumlar)
    assert sum(len(o) for o in oturumlar) == len(m)
    assert _bolunen_duygular(oturumlar) == set()
    assert [r["id"] for o in oturumlar for r in o] == [r["id"] for r in m]      # sıra korunur


def test_plan_sessions_120yi_asan_duygu_ikiye_bolunur():
    m = _yapay_manifest({"mutlu": 200, "üzgün": 30})
    oturumlar = senaryo.plan_sessions(m)
    assert all(len(o) <= 120 for o in oturumlar)
    assert _bolunen_duygular(oturumlar) == {"mutlu"}
    mutlu_parcalari = [sum(1 for r in o if r["duygu"] == "mutlu") for o in oturumlar]
    assert sorted(x for x in mutlu_parcalari if x) == [100, 100]


def test_plan_sessions_oturum_sayisi_verilirse_esit_ve_duygu_sinirinda():
    m = _yapay_manifest({"a": 30, "b": 30, "c": 30, "d": 30})
    oturumlar = senaryo.plan_sessions(m, oturum=2)
    assert [len(o) for o in oturumlar] == [60, 60]
    assert _bolunen_duygular(oturumlar) == set()
    oturumlar3 = senaryo.plan_sessions(m, oturum=3)
    assert len(oturumlar3) == 3
    assert sum(len(o) for o in oturumlar3) == 120
    assert max(len(o) for o in oturumlar3) - min(len(o) for o in oturumlar3) <= 30


def test_plan_sessions_bos_ve_tek():
    assert senaryo.plan_sessions([]) == []
    m = _yapay_manifest({"a": 5})
    assert senaryo.plan_sessions(m, oturum=10) == [[r for r in m][i:i + 1] for i in range(5)]


# ---------- write_scripts ----------

def test_write_scripts_dosyalar_manifest_ve_ozet(banka, tmp_path):
    m = senaryo.build_manifest(senaryo.load_bank(banka), tekrar=2)
    oturumlar = senaryo.plan_sessions(m)
    cikti = tmp_path / "senaryo"
    yazilan = senaryo.write_scripts(oturumlar, cikti, kisi="Ayşe")
    adlar = {p.name for p in yazilan}
    assert {"oturum_01.md", "oturum_02.md", "manifest.csv", "OZET.md", "kayit_listesi.txt"} <= adlar
    assert all(p.exists() for p in yazilan)

    satir = (cikti / "manifest.csv").read_text(encoding="utf-8").splitlines()
    assert satir[0] == "id|duygu|yogunluk|metin"
    assert len(satir) == len(m) + 1
    with (cikti / "manifest.csv").open(encoding="utf-8", newline="") as f:
        kayitlar = list(csv.DictReader(f, delimiter="|"))
    assert [k["id"] for k in kayitlar] == [r["id"] for r in m]
    assert {k["yogunluk"] for k in kayitlar} == {"normal", "hafif", "güçlü"}

    liste = (cikti / "kayit_listesi.txt").read_text(encoding="utf-8").split()
    assert liste == [r["id"] for r in m]

    oturum1 = (cikti / "oturum_01.md").read_text(encoding="utf-8")
    assert "Ayşe" in oturum1
    assert "## Duygu: normal" in oturum1
    assert "Nötr ve doğal oku." in oturum1
    assert re.search(r"^1\. \[normal_0001\] Komşumuz", oturum1, re.M)
    for anahtar in ("Sessiz oda", "15–20 cm", "Su", "1 saniye", "baştan"):
        assert anahtar in oturum1
    tum_md = "".join((cikti / f"oturum_{i:02d}.md").read_text(encoding="utf-8") for i in (1, 2))
    assert "(hafif)" in tum_md and "(güçlü)" in tum_md and "Yoğunluk" in tum_md

    ozet = (cikti / "OZET.md").read_text(encoding="utf-8")
    toplam_dk = senaryo._dk(len(m) * (senaryo.SN_CUMLE + senaryo.SN_ARA))
    assert f"{toplam_dk} dk" in ozet
    assert "Tahmini kayıt süresi" in ozet
    assert "| mutlu | 30 | 60 |" in ozet
    assert "3 saat" in ozet and "--tekrar" in ozet and "--metin" in ozet


# ---------- check_bank ----------

def test_check_bank_temiz_bankada_hata_yok(banka):
    assert [s for s in senaryo.check_bank(banka) if s.startswith("HATA")] == []


def test_check_bank_eksik_yonerge(banka):
    dosya_yaz(banka, "sakin", cumleler_uret("Deniz"), yonerge=None)
    sorunlar = senaryo.check_bank(banka)
    assert any("sakin.txt" in s and "yönerge" in s and s.startswith("HATA") for s in sorunlar)


def test_check_bank_tekrar_tr_lower_ile(banka):
    cumleler = cumleler_uret("Deniz")
    cumleler[5] = "İSTANBUL'DA hava bugün çok güzel."
    cumleler[9] = "istanbul'da hava bugün çok güzel!"
    dosya_yaz(banka, "sakin", cumleler)
    sorunlar = senaryo.check_bank(banka)
    assert any("tekrar" in s and "10. cümle 6. cümlenin" in s for s in sorunlar)


def test_check_bank_30dan_az_satir(banka):
    dosya_yaz(banka, "sakin", cumleler_uret("Deniz", 12))
    sorunlar = senaryo.check_bank(banka)
    assert any("sakin.txt: 12 cümle" in s and s.startswith("HATA") for s in sorunlar)


def test_check_bank_kisa_uzun_ve_noktalamasiz(banka):
    cumleler = cumleler_uret("Deniz")
    cumleler[0] = "Çok güzel."                                              # 2 sözcük → HATA
    cumleler[1] = " ".join(["uzun"] * 22) + " cümle."                       # 23 sözcük → UYARI
    cumleler[2] = "Bu cümlenin sonunda nokta yok"                           # noktalama → HATA
    dosya_yaz(banka, "sakin", cumleler)
    sorunlar = senaryo.check_bank(banka)
    assert any(s.startswith("HATA") and "1. cümle 2 sözcük" in s for s in sorunlar)
    assert any(s.startswith("UYARI") and "2. cümle 23 sözcük" in s for s in sorunlar)
    assert any(s.startswith("HATA") and "3. cümle noktalamayla bitmiyor" in s for s in sorunlar)


def test_check_bank_klasor_yok(tmp_path):
    assert senaryo.check_bank(tmp_path / "yok")[0].startswith("HATA")


# ---------- main ----------

def test_main_kontrol_temiz_bankada_0(banka, capsys):
    assert senaryo.main(["--kontrol", "--banka", str(banka)]) == 0
    assert "0 hata" in capsys.readouterr().out


def test_main_kontrol_sorunlu_bankada_1(banka, capsys):
    dosya_yaz(banka, "sakin", cumleler_uret("Deniz", 10), yonerge=None)
    assert senaryo.main(["--kontrol", "--banka", str(banka)]) == 1
    cikti = capsys.readouterr().out
    assert "HATA" in cikti and "sakin.txt" in cikti


def test_main_tam_akis(banka, tmp_path, capsys):
    cikti = tmp_path / "senaryo"
    kod = senaryo.main(["--cikti", str(cikti), "--banka", str(banka), "--tekrar", "2", "--kisi", "Deneme Kişi"])
    assert kod == 0
    for ad in ("oturum_01.md", "manifest.csv", "OZET.md", "kayit_listesi.txt"):
        assert (cikti / ad).exists()
    satir = (cikti / "manifest.csv").read_text(encoding="utf-8").splitlines()
    assert len(satir) == 1 + 30 + 60 + 60
    assert "Senaryo yazıldı" in capsys.readouterr().out


def test_main_oturum_sayisi(banka, tmp_path):
    cikti = tmp_path / "s"
    assert senaryo.main(["--cikti", str(cikti), "--banka", str(banka), "--oturum", "3"]) == 0
    assert sorted(p.name for p in cikti.glob("oturum_*.md")) == ["oturum_01.md", "oturum_02.md", "oturum_03.md"]


def test_main_metin_normale_eklenir(banka, tmp_path):
    kitap = tmp_path / "kitap.txt"
    kitap.write_text("Dr. Ayşe sabah erkenden kliniğe geldi. Hastalar onu kapıda bekliyordu.\n", encoding="utf-8")
    cikti = tmp_path / "s"
    assert senaryo.main(["--cikti", str(cikti), "--banka", str(banka), "--metin", str(kitap)]) == 0
    with (cikti / "manifest.csv").open(encoding="utf-8", newline="") as f:
        kayitlar = list(csv.DictReader(f, delimiter="|"))
    normal = [k for k in kayitlar if k["duygu"] == "normal"]
    assert len(normal) == 32
    assert normal[-2]["metin"] == "Dr. Ayşe sabah erkenden kliniğe geldi."
    assert normal[-1]["id"] == "normal_0032"


def test_main_duygular_suzer(banka, tmp_path):
    cikti = tmp_path / "s"
    assert senaryo.main(["--cikti", str(cikti), "--banka", str(banka), "--duygular", "mutlu,üzgün"]) == 0
    with (cikti / "manifest.csv").open(encoding="utf-8", newline="") as f:
        duygular = {k["duygu"] for k in csv.DictReader(f, delimiter="|")}
    assert duygular == {"mutlu", "üzgün"}


def test_main_bos_banka_ve_bilinmeyen_duygu_1(tmp_path, banka):
    bos = tmp_path / "bos"
    bos.mkdir()
    assert senaryo.main(["--cikti", str(tmp_path / "x"), "--banka", str(bos)]) == 1
    assert senaryo.main(["--cikti", str(tmp_path / "y"), "--banka", str(banka), "--duygular", "yok"]) == 1
