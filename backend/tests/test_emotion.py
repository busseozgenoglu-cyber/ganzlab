"""emotion.py ve styles.py testleri: Türkçe büyük harf, otomatik duygu, etiketler, vurgu, katalog, stiller."""
import shutil

import numpy as np
import pytest

from app.emotion import (
    ALIAS_TO_NAME, AUTO_LEXICON, NONVERBAL, PAUSE_TAGS, PROFILES, _ffmpeg_filter, fold_ascii, infer_emotion,
    infer_emotion_scores, parse_tagged_text, resolve, tag_catalog, timed_pause_ms,
)
from app.styles import STYLE_FIELDS, STYLES, Style, apply_style, resolve_style, style_catalog
from app.tr import tr_lower


def _tek(text):
    """Tek bölüm bekleyen ayrıştırma yardımcısı."""
    segs = parse_tagged_text(text)
    assert len(segs) == 1, segs
    return segs[0]


# ---------- resolve: Türkçe büyük harf, İ/ı, ASCII, eş anlamlılar ----------

def test_resolve_buyuk_harf_ve_turkce_karakter():
    assert resolve("HEYECANLI").name == "heyecanlı"
    assert resolve("Üzgün").name == "üzgün"
    assert resolve("ŞAŞKIN").name == "şaşkın"
    assert resolve("KIZGIN").name == "kızgın"
    assert resolve("EXCITED").name == "heyecanlı"          # İngilizce büyük harf (tr_lower 'excıted' verirdi)
    assert resolve("SİNİRLİ").name == "kızgın"             # İ → i
    assert resolve("saskin").name == "şaşkın"              # ASCII yazım
    assert resolve("  sakin  ").name == "sakin"
    assert resolve("yok") is None
    assert resolve("") is None and resolve("   ") is None and resolve(None) is None


def test_yeni_profiller_ve_es_anlamlilar():
    n = PROFILES["nazik"]
    assert (n.exaggeration, n.cfg_weight, n.temperature, n.pause_mul) == (0.45, 0.5, 0.75, 1.1)
    assert PROFILES["gururlu"].exaggeration == 0.6 and PROFILES["gururlu"].cfg_weight == 0.45
    assert PROFILES["umutlu"].exaggeration == 0.55
    assert (PROFILES["nostaljik"].speed, PROFILES["nostaljik"].pause_mul) == (0.95, 1.3)
    g = PROFILES["gergin"]
    assert (g.exaggeration, g.cfg_weight, g.temperature, g.speed, g.pause_mul) == (0.6, 0.4, 0.85, 1.03, 0.85)
    r = PROFILES["romantik"]
    assert (r.speed, r.pause_mul, r.whisper_mix) == (0.95, 1.25, 0.15)
    assert PROFILES["çocuksu"].ref_pitch == 1.5 and PROFILES["çocuksu"].exaggeration == 0.7
    o = PROFILES["otoriter"]
    assert o.compress is True and o.speed == 0.97 and o.cfg_weight == 0.55
    assert resolve("kibar").name == "nazik" and resolve("polite").name == "nazik"
    assert resolve("hizmet").name == "nazik"
    assert resolve("proud").name == "gururlu" and resolve("hopeful").name == "umutlu"
    assert resolve("nostalgic").name == "nostaljik" and resolve("tense").name == "gergin"
    assert resolve("romantic").name == "romantik" and resolve("childlike").name == "çocuksu"
    assert resolve("AUTHORITATIVE").name == "otoriter"
    assert resolve("coşkulu").name == "heyecanlı"          # eski eş anlamlılar korunuyor
    assert resolve("yorgun").name == "sıkılmış"


def test_profil_tablosu_tutarli():
    assert all(p.description for p in PROFILES.values())
    sahip: dict[str, str] = {}
    for p in PROFILES.values():
        for a in [p.name, *p.aliases]:
            k = tr_lower(a)
            assert sahip.setdefault(k, p.name) == p.name, f"çakışan eş anlamlı: {a}"
            assert resolve(a).name == p.name
    # ASCII karşılıkları da çakışmamalı
    katlanmis: dict[str, str] = {}
    for k, n in ALIAS_TO_NAME.items():
        assert katlanmis.setdefault(fold_ascii(k), n) == n, f"ASCII çakışması: {k}"
    # etiket tabloları duygu adlarını gölgelememeli
    assert not (set(NONVERBAL) | set(PAUSE_TAGS)) & set(ALIAS_TO_NAME)


# ---------- otomatik duygu ----------

def test_sozluk_yapisi():
    gorulen = set()
    for emo, kaliplar in AUTO_LEXICON:
        assert emo in PROFILES
        assert 25 <= len(kaliplar) <= 40, (emo, len(kaliplar))
        for k in kaliplar:
            assert k == tr_lower(k), k
            assert k not in gorulen, f"tekrarlanan kalıp: {k}"
            gorulen.add(k)


def test_infer_yeni_sozcukler_ve_buyuk_harf():
    assert infer_emotion("İNANILMAZ BİR HABER!") == "heyecanlı"
    assert infer_emotion("BUNU HEMEN DÜZELTİN YETER ARTIK") == "kızgın"
    assert infer_emotion("Yeter artık, bıktım!") == "kızgın"
    assert infer_emotion("Ne? Gerçekten mi?") == "şaşkın"
    assert infer_emotion("Ne yaptın?!") == "şaşkın"
    assert infer_emotion("Endişelenme, her şey yolunda.") == "sakin"   # en uzun kalıp: korkmuş değil
    assert infer_emotion("Umarım yarın her şey düzelir.") == "umutlu"
    assert infer_emotion("Seni seviyorum.") == "romantik"              # 'seviyorum' (mutlu) yerine
    assert infer_emotion("Çocukken o günler ne güzeldi...") == "nostaljik"
    assert infer_emotion("Lütfen bekleyiniz, size yardımcı olabilir miyim?") == "nazik"
    assert infer_emotion("Bunu başardık, gurur duyuyoruz!") == "gururlu"
    assert infer_emotion("Eyvah, biri var!") == "korkmuş"
    assert infer_emotion("Özür dilerim.") == "nazik"
    assert infer_emotion("Süpermarkete gidiyorum.") is None            # '=süper' tam sözcük
    assert infer_emotion("") is None


def test_infer_olumsuzluk():
    assert infer_emotion("Bu harika değil.") == "üzgün"
    assert infer_emotion("Bu hiç güzel değil.") == "üzgün"
    assert infer_emotion("Harika değil!") == "kızgın"
    assert infer_emotion("Harika, değil mi?") == "heyecanlı"           # onay sorusu olumsuzluk değil
    assert infer_emotion("Harika değil mi?") == "heyecanlı"
    assert infer_emotion("Önemli değil.") is None                      # olumsuz 'ciddi' sayılmaz
    assert infer_emotion("Mutlu asla olamam.") == "üzgün"              # 'asla' burada kızgınlık değil
    assert infer_emotion("Asla kabul etmem!") == "kızgın"


def test_infer_puanlar_ve_noktalama():
    assert infer_emotion_scores("Maalesef kaybettik...") == {"üzgün": 5}   # 2 + 2 + '...' 1
    assert infer_emotion_scores("Yarın geliyor musun?") == {}             # '?' yalnızca aday varsa
    puan = infer_emotion_scores("İNANILMAZ BİR HABER!")
    assert next(iter(puan)) == infer_emotion("İNANILMAZ BİR HABER!")
    assert puan["heyecanlı"] > puan["kızgın"] > 0
    assert infer_emotion_scores("Geldim!") == {"heyecanlı": 1}            # yalnız '!' → hafif heyecan


# ---------- sözsüz etiketler ve duraklamalar ----------

@pytest.mark.parametrize("etiket, okunus", [
    ("gülme", "Hahaha!"), ("kahkaha", "Hahahaha!"), ("kıkırdama", "Hihihi!"), ("iç çekme", "Ahh..."),
    ("of", "Off..."), ("hmm", "Hmm..."), ("şaşırır", "Vay canına!"), ("ağlar", "Hıh hıh..."),
    ("öksürür", "Öhö öhö."), ("boğaz temizler", "Ehem."), ("esner", "Aaah..."), ("tüh", "Tüh!"),
    ("aman", "Aman!"), ("ay", "Ay!"), ("oh", "Oh..."), ("hıh", "Hıh."), ("hah", "Hah!"), ("ıı", "Iıı..."),
    ("ee", "Iıı..."), ("şey", "Şey..."), ("hı hı", "Hı hı."), ("hişt", "Hişt!"), ("pff", "Pöf..."),
    ("mmm", "Mmm..."), ("vay", "Vay!"), ("evet evet", "Evet, evet."), ("yok ya", "Yok ya!"),
    ("cık", "Cık cık."), ("ıslık", "Fiiüüt!"), ("nefes verir", "Hoff..."), ("laughs", "Hahaha!"),
    ("sighs", "Ahh..."), ("gasps", "Hah!"), ("groans", "Ohh..."), ("coughs", "Öhö öhö."), ("sniffs", "Sniff."),
    ("hums", "Hmm hmm hmm."),
    # büyük harf, harf tekrarı ve ASCII yazım
    ("GÜLME", "Hahaha!"), ("SIGHS", "Ahh..."), ("II", "Iıı..."), ("hmmm", "Hmm..."), ("offf", "Off..."),
    ("tühhh", "Tüh!"), ("gulme", "Hahaha!"), ("hahahaha", "Hahaha!"), ("GIGGLES", "Hihihi!"),
])
def test_sozsuz_etiketler(etiket, okunus):
    assert _tek(f"Peki [{etiket}] tamam.").text == f"Peki {okunus} tamam."


@pytest.mark.parametrize("etiket, ms", [
    ("nefes", 500), ("derin nefes", 700), ("kısa duraklama", 350), ("duraklama", 800), ("uzun duraklama", 1500),
    ("sessizlik", 2000), ("1.5 sn", 1500), ("1,5 sn", 1500), ("1 sn", 1000), ("500 ms", 500), ("2 saniye", 2000),
    ("2 SN", 2000), ("0.25s", 250), ("duraklama: 2 sn", 2000), ("99 sn", 10_000),
])
def test_duraklama_etiketleri(etiket, ms):
    segs = parse_tagged_text(f"Bir. [{etiket}] İki.")
    assert [s.text for s in segs] == ["Bir.", "İki."]
    assert segs[1].pause_before_ms == ms


def test_duraklama_birikimi_ve_sonda_duraklama():
    segs = parse_tagged_text("Bir. [nefes] [1 sn] İki. [2 saniye]")
    assert segs[1].pause_before_ms == 1500
    assert segs[-1].pause_after_ms == 2000
    assert _tek("Bitti [derin nefes]").text == "Bitti"                  # ses üretmez
    assert timed_pause_ms("1.5 sn") == 1500 and timed_pause_ms("merhaba") is None


# ---------- kapsamlı duygu etiketi, vurgu, desteklenmeyen biçimler ----------

def test_kapsamli_duygu_etiketi():
    segs = parse_tagged_text("Merhaba. [heyecanlı: Bu harika!] Devam.")
    assert [(s.text, s.emotion) for s in segs] == [("Merhaba.", None), ("Bu harika!", "heyecanlı"), ("Devam.", None)]
    segs = parse_tagged_text("[üzgün] A. [MUTLU: B.] C. [normal: D.] E.")
    assert [s.emotion for s in segs] == ["üzgün", "mutlu", "üzgün", None, "üzgün"]
    uzun = "Bu cümle kırk karakterden çok daha uzun olsa da yine heyecanlı okunmalı."
    assert parse_tagged_text(f"[heyecanlı: {uzun}]")[0].text == uzun


def test_satir_basi_duygu_bicimi_desteklenmez():
    seg = _tek("Heyecanlı: Bu harika.")
    assert seg.emotion is None and seg.text == "Heyecanlı: Bu harika."


def test_yildiz_vurgusu():
    seg = _tek("Bu *çok* önemli, **kesinlikle** doğru.")
    assert seg.text == "Bu çok önemli, kesinlikle doğru."
    assert seg.emphasis_words == ["çok", "kesinlikle"]
    seg = _tek("Sonuç 2*3*4 eder.")
    assert seg.text == "Sonuç 2*3*4 eder." and seg.emphasis_words == []
    seg = _tek("[vurgu] Yarın geliyorum, [vurgu: hemen şimdi] çık.")
    assert seg.text == "Yarın geliyorum, hemen şimdi çık."
    assert seg.emphasis_words == ["Yarın", "hemen şimdi"]
    assert _tek("Düz metin.").emphasis_words == []
    assert _tek("[vurgu] «Yarın» gel.").emphasis_words == ["Yarın"]


def test_uzun_koseli_parantez_metin_olarak_kalir():
    t = "Not [bu köşeli parantez içindeki açıklama kırk karakterden uzundur] son."
    assert _tek(t).text == t
    assert _tek("Kısa [bilinmeyen etiket] son.").text == "Kısa son."


# ---------- katalog ----------

def test_tag_catalog_eski_ve_yeni_alanlar():
    cat = tag_catalog()
    assert isinstance(cat["nonverbal"], list) and all(isinstance(x, str) for x in cat["nonverbal"])
    assert cat["nonverbal"] == sorted(cat["nonverbal"])
    for t in ["gülme", "kahkaha", "kıkırdama", "iç çekme", "hmm", "of", "şaşırır", "ağlar", "öksürür",
              "boğaz temizler", "esner", "tüh", "şey"]:
        assert t in cat["nonverbal"], t
    assert "nefes" not in cat["nonverbal"]                              # ses üretmeyenler listede yok
    assert {"tag": "gülme", "reads": "Hahaha!"} in cat["nonverbal_detail"]
    assert len(cat["nonverbal_detail"]) == len(cat["nonverbal"])
    assert isinstance(cat["pauses"], list) and cat["pauses"] == sorted(cat["pauses"])
    for p in ["nefes", "duraklama", "uzun duraklama", "kısa duraklama", "sessizlik", "derin nefes"]:
        assert p in cat["pauses"], p
    assert {"tag": "derin nefes", "ms": 700} in cat["pause_detail"]
    e = {x["name"]: x for x in cat["emotions"]}
    assert set(e["heyecanlı"]) >= {"name", "label", "aliases", "description"}
    assert "nazik" in e and e["nazik"]["description"]
    # ses üretmeyen sözsüz etiketlerin hepsinin süresi tanımlı
    assert all(k in PAUSE_TAGS for k, v in NONVERBAL.items() if not v)


# ---------- ffmpeg hatası girdiyi döndürür ----------

@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg yok")
def test_ffmpeg_hatasi_girdiyi_dondurur(caplog):
    sr = 16000
    wav = (0.5 * np.sin(2 * np.pi * 220 * np.arange(sr // 2) / sr)).astype(np.float32)
    with caplog.at_level("WARNING", logger="sesklon.emotion"):
        out = _ffmpeg_filter(wav, sr, "boyle_bir_filtre_yok=1")
    assert out is wav
    assert any("ffmpeg" in r.getMessage() for r in caplog.records)
    kisik = _ffmpeg_filter(wav, sr, "volume=-6dB")
    assert 0.4 < float(np.max(np.abs(kisik))) / float(np.max(np.abs(wav))) < 0.6


# ---------- stiller ----------

BEKLENEN_STILLER = ["sohbet", "anlatıcı", "haber", "reklam", "masal", "podcast", "belgesel", "eğitim",
                    "sesli-kitap", "duygusal", "müşteri-hizmeti", "spor-spikeri"]


def test_her_stil_cozumleniyor():
    assert list(STYLES) == BEKLENEN_STILLER
    for ad in BEKLENEN_STILLER:
        s = resolve_style(ad)
        assert s is not None and s.name == ad
        assert s.label and s.description
        assert s.emotion is None or s.emotion in PROFILES
        assert s.colloquial in ("off", "light", "full")
        assert resolve_style(s.label).name == ad


@pytest.mark.parametrize("ad, stil", [
    ("narrator", "anlatıcı"), ("news", "haber"), ("ad", "reklam"), ("fairy tale", "masal"),
    ("documentary", "belgesel"), ("education", "eğitim"), ("audiobook", "sesli-kitap"),
    ("emotional", "duygusal"), ("support", "müşteri-hizmeti"), ("sports", "spor-spikeri"),
    ("ANLATICI", "anlatıcı"), ("Sesli Kitap", "sesli-kitap"), ("sesli_kitap", "sesli-kitap"),
    ("EĞİTİM", "eğitim"), ("egitim", "eğitim"), ("MUSTERI HIZMETI", "müşteri-hizmeti"), ("PODCAST", "podcast"),
])
def test_stil_es_anlamlilari(ad, stil):
    assert resolve_style(ad).name == stil


def test_stil_es_anlamli_cakismasi_yok_ve_bilinmeyen():
    sahip: dict[str, str] = {}
    for s in STYLES.values():
        for a in [s.name, s.label, *s.aliases]:
            assert sahip.setdefault(tr_lower(a).replace("-", " "), s.name) == s.name, f"çakışma: {a}"
    assert resolve_style("yok") is None and resolve_style("") is None and resolve_style(None) is None


def test_stil_degerleri_sozlesmeye_uygun():
    assert STYLES["sohbet"].description == "Varsayılan: doğal, samimi, konuşur gibi."
    assert STYLES["haber"].punctuation_emotion is False and STYLES["haber"].colloquial == "off"
    assert STYLES["reklam"].emotion == "heyecanlı" and STYLES["reklam"].speed == 1.04
    assert STYLES["masal"].emotion == "samimi" and STYLES["masal"].pause_scale == 1.35
    assert STYLES["podcast"].colloquial == "full"
    assert STYLES["belgesel"].emotion == "ciddi"
    assert STYLES["duygusal"].auto_emotion is True
    assert STYLES["müşteri-hizmeti"].emotion == "nazik"
    sp = STYLES["spor-spikeri"]
    assert (sp.exaggeration, sp.cfg_weight, sp.temperature, sp.speed, sp.pause_scale) == (0.85, 0.3, 0.95, 1.08, 0.7)


def test_apply_style_override():
    d = apply_style("haber", {"speed": None, "exaggeration": 0.6, "bilinmeyen_alan": 5})
    assert tuple(d) == STYLE_FIELDS
    assert d["exaggeration"] == 0.6                                     # kullanıcı değeri
    assert d["speed"] == 1.0 and d["cfg_weight"] == 0.55                # None → stilin değeri
    assert d["colloquial"] == "off" and d["punctuation_emotion"] is False
    assert apply_style(STYLES["reklam"], {"emotion": "Üzgün"})["emotion"] == "üzgün"
    assert apply_style("reklam", {"emotion": "normal"})["emotion"] is None
    assert apply_style("reklam", {})["emotion"] == "heyecanlı"
    assert apply_style("masal", {"colloquial": True})["colloquial"] == "light"
    assert apply_style("sohbet", {"colloquial": False})["colloquial"] == "off"
    assert apply_style("sohbet", {"colloquial": "LIGHT"})["colloquial"] == "light"   # tr_lower "lıght" değil
    beklenen = {**apply_style("sesli-kitap", {}), "breaths": False, "pause_scale": 1.5}
    assert apply_style("Sesli Kitap", {"breaths": False, "pause_scale": "1.5"}) == beklenen
    varsayilan = apply_style(None, {})
    taban = Style("", "", "")
    assert varsayilan == {f: getattr(taban, f) for f in STYLE_FIELDS}
    with pytest.raises(ValueError):
        apply_style("böyle-bir-stil-yok", {})
    with pytest.raises(ValueError):
        apply_style("sohbet", {"colloquial": "çok"})


def test_style_catalog():
    cat = style_catalog()
    assert [c["name"] for c in cat] == BEKLENEN_STILLER
    for c in cat:
        assert {"name", "label", "description", "aliases"} <= set(c)
        assert set(STYLE_FIELDS) <= set(c)
