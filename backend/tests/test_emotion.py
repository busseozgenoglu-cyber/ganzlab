"""emotion.py ve styles.py testleri: Türkçe büyük harf, otomatik duygu, etiketler, vurgu, katalog, stiller;
v4: sözsüz bölümler, yoğunluk, karışım, kayış, hız/perde/konuşmacı, etkin profil, vurgu planı."""
import dataclasses
import shutil

import numpy as np
import pytest

from app.emotion import (
    ALIAS_TO_NAME, ARC_WORDS, AUTO_LEXICON, NONVERBAL, NONVERBAL_CANON, PAUSE_TAGS, PROFILES, Segment,
    _ffmpeg_filter, effective_profile, fold_ascii, infer_emotion, infer_emotion_scores, interpolate_profile,
    nonverbal_fallback, nonverbal_key, parse_tagged_text, plan_emphasis, resolve, tag_catalog, timed_pause_ms,
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


# =====================================================================================================
# v4: sözsüz bölümler, yoğunluk, karışım, kayış, satır içi kontroller, etkin profil, vurgu planı
# =====================================================================================================

KAYDEDILEBILIR = ("gülme", "kahkaha", "kıkırdama", "iç çekme", "hmm", "of", "nefes verir", "öksürür",
                  "boğaz temizler", "esner", "ağlar", "şaşırır", "hıh", "mmm", "cık")


def _ozet(text, **kw):
    """(metin, duygu, sözsüz anahtar) üçlüleri."""
    return [(s.text, s.emotion, s.nonverbal) for s in parse_tagged_text(text, **kw)]


# ---------- Segment ----------

def test_segment_yeni_alan_varsayilanlari():
    s = Segment("Merhaba", None)
    assert (s.nonverbal, s.intensity, s.blend, s.rate, s.pitch, s.speaker, s.arc_to) == \
           (None, 1.0, [], None, None, None, None)
    assert Segment("a", None).blend is not Segment("b", None).blend          # paylaşılan liste yok
    eski = Segment("Selam", "heyecanlı", 500, 0, ["Selam"])                  # eski konumsal çağrı geçerli
    assert (eski.pause_before_ms, eski.emphasis_words, eski.intensity) == (500, ["Selam"], 1.0)
    for seg in parse_tagged_text("[heyecanlı] Selam! [gülme] [nefes] *Devam* [üzgün: Bitti.]"):
        assert (seg.nonverbal, seg.intensity, seg.blend, seg.rate, seg.pitch, seg.speaker, seg.arc_to) == \
               (None, 1.0, [], None, None, None, None)


# ---------- keep_nonverbal ----------

def test_keep_nonverbal_iki_mod():
    metin = "[heyecanlı] Selam! [gülme] Devam. [nefes] [üzgün] Bitti. [bilinmeyen] Son."
    assert parse_tagged_text(metin) == parse_tagged_text(metin, keep_nonverbal=False)
    assert _ozet(metin) == [("Selam! Hahaha! Devam.", "heyecanlı", None), ("Bitti. Son.", "üzgün", None)]
    segs = parse_tagged_text(metin, keep_nonverbal=True)
    assert _ozet(metin, keep_nonverbal=True) == [
        ("Selam!", "heyecanlı", None), ("", "heyecanlı", "gülme"), ("Devam.", "heyecanlı", None),
        ("Bitti. Son.", "üzgün", None)]
    assert segs[3].pause_before_ms == 500                                    # [nefes] yine duraklama
    assert _ozet("Of [tüh] olsun.", keep_nonverbal=True) == [
        ("Of", None, None), ("", None, "tüh"), ("olsun.", None, None)]       # kaydı olmayan da ayrı bölüm


def test_keep_nonverbal_duraklama_ve_durum():
    segs = parse_tagged_text("Bir. [1 sn] [iç çekme] İki.", keep_nonverbal=True)
    assert [(s.text, s.nonverbal, s.pause_before_ms) for s in segs] == [
        ("Bir.", None, 0), ("", "iç çekme", 1000), ("İki.", None, 0)]
    segs = parse_tagged_text("[gülme] Tamam. [kahkaha atar] [2 sn]", keep_nonverbal=True)
    assert [(s.text, s.nonverbal) for s in segs] == [("", "gülme"), ("Tamam.", None), ("", "kahkaha")]
    assert segs[-1].pause_after_ms == 2000                                   # sondaki duraklama son bölüme
    # sözsüz bölüm o anki konuşmacı / hız / perde / yoğunluğu taşır; bekleyen kayışı metne bırakır
    segs = parse_tagged_text("[ses:Ayşe] [hız:0.9] [perde:+1] [çok mutlu] [sakinleşerek] [gülme] Neyse.",
                             keep_nonverbal=True)
    nv = segs[0]
    assert (nv.text, nv.nonverbal, nv.emotion, nv.intensity, nv.speaker, nv.rate, nv.pitch, nv.arc_to) == \
           ("", "gülme", "mutlu", 1.35, "Ayşe", 0.9, 1.0, None)
    assert (segs[1].text, segs[1].emotion, segs[1].arc_to) == ("Neyse.", "mutlu", "sakin")


@pytest.mark.parametrize("etiket, anahtar", [
    ("laughs", "gülme"), ("güler", "gülme"), ("gülme", "gülme"), ("kahkaha atar", "kahkaha"),
    ("kıkırdar", "kıkırdama"), ("sighs", "iç çekme"), ("iç çeker", "iç çekme"), ("hm", "hmm"), ("hmm", "hmm"),
    ("cries", "ağlar"), ("ağlıyor", "ağlar"), ("coughs", "öksürür"), ("clears throat", "boğaz temizler"),
    ("yawns", "esner"), ("exhales", "nefes verir"), ("nefes verme", "nefes verir"), ("cık cık", "cık"),
    ("mmm", "mmm"), ("hıhı", "hıh"), ("şaşırır", "şaşırır"),
    # büyük harf, harf tekrarı, ASCII yazım, tekrarlı gülme
    ("LAUGHS", "gülme"), ("HMMM", "hmm"), ("gulme", "gülme"), ("hahahaha", "gülme"), ("hihihi", "kıkırdama"),
    ("İÇ ÇEKER", "iç çekme"),
])
def test_kanonik_sozsuz_adlar(etiket, anahtar):
    assert nonverbal_key(etiket) == anahtar
    segs = parse_tagged_text(f"Peki [{etiket}] tamam.", keep_nonverbal=True)
    assert [(s.text, s.nonverbal) for s in segs] == [("Peki", None), ("", anahtar), ("tamam.", None)]


def test_kanonik_tablo_tutarli():
    sesli = {k for k, v in NONVERBAL.items() if v}
    assert set(NONVERBAL_CANON) == sesli                                     # her sesli etiketin kanonik adı var
    assert all(NONVERBAL_CANON[k] == k for k in KAYDEDILEBILIR)              # kayıt anahtarları kanonik
    for kanonik in set(NONVERBAL_CANON.values()):
        assert NONVERBAL_CANON[kanonik] == kanonik and NONVERBAL[kanonik], kanonik
    assert NONVERBAL_CANON["chuckles"] == "kıkırdama" and NONVERBAL_CANON["tüh"] == "tüh"
    assert nonverbal_key("nefes") is None and nonverbal_key("heyecanlı") is None
    assert nonverbal_key("") is None and nonverbal_key(None) is None


def test_nonverbal_fallback():
    assert nonverbal_fallback("gülme") == "Hahaha!"
    assert nonverbal_fallback("iç çekme") == "Ahh..."
    assert nonverbal_fallback("kahkaha") == "Hahahaha!"
    assert nonverbal_fallback("laughs") == nonverbal_fallback("gülme")       # eş ad → kanonik okunuş
    assert nonverbal_fallback("hıhı") == NONVERBAL["hıh"]
    assert nonverbal_fallback("nefes") == "" and nonverbal_fallback("yok böyle") == ""
    assert all(nonverbal_fallback(k) for k in KAYDEDILEBILIR)


# ---------- yoğunluk ----------

@pytest.mark.parametrize("etiket, yogunluk", [
    ("heyecanlı:1", 0.7), ("heyecanlı:2", 1.0), ("heyecanlı:3", 1.4), ("heyecanlı: 3", 1.4), ("HEYECANLI:1", 0.7),
    ("biraz heyecanlı", 0.65), ("hafif heyecanlı", 0.65), ("az heyecanlı", 0.65),
    ("çok heyecanlı", 1.35), ("epey heyecanlı", 1.35), ("aşırı heyecanlı", 1.6), ("çok çok heyecanlı", 1.6),
    ("ÇOK HEYECANLI", 1.35), ("cok heyecanli", 1.35), ("çok excited", 1.35),
    ("heyecanlı %150", 1.5), ("heyecanlı 150%", 1.5), ("%80 heyecanlı", 0.8), ("heyecanlı %50", 0.5),
    ("heyecanlı %160", 1.6), ("heyecanlı %200", 1.6), ("heyecanlı %20", 0.5),      # 50–160 sınırı
    ("biraz heyecanlı:3", 0.91),                                                   # sözcük × seviye
])
def test_yogunluk_sozdizimi(etiket, yogunluk):
    seg = _tek(f"[{etiket}] Bu harika!")
    assert (seg.text, seg.emotion) == ("Bu harika!", "heyecanlı")
    assert seg.intensity == pytest.approx(yogunluk)


def test_yogunluk_surekli_ve_sifirlanir():
    segs = parse_tagged_text("[çok üzgün] Bir. [nefes] İki. [mutlu] Üç. [biraz heyecanlı: Dört.] Beş. [normal] Altı.")
    assert [(s.text, s.emotion, s.intensity) for s in segs] == [
        ("Bir.", "üzgün", 1.35), ("İki.", "üzgün", 1.35), ("Üç.", "mutlu", 1.0), ("Dört.", "heyecanlı", 0.65),
        ("Beş.", "mutlu", 1.0), ("Altı.", None, 1.0)]


def test_yogunluk_kapsamli_metinle_karismaz():
    assert [(s.text, s.emotion) for s in parse_tagged_text("[heyecanlı: 4 kişi geldi!]")] == \
           [("4 kişi geldi!", "heyecanlı")]
    assert [s.text for s in parse_tagged_text("[heyecanlı:1] Geldi.")] == ["Geldi."]   # "1" okunmaz
    seg = _tek("A [çok xyz] B.")                                             # bilinmeyen duygu → yok sayılır
    assert (seg.text, seg.emotion, seg.intensity) == ("A B.", None, 1.0)
    assert _tek("[biraz] Selam.").emotion is None


# ---------- karışım ----------

def test_karisim():
    seg = _tek("[üzgün+umutlu] Belki yarın.")
    assert (seg.emotion, seg.blend, seg.intensity) == ("üzgün", ["umutlu"], 1.0)
    assert _tek("[üzgün + umutlu] Belki.").blend == ["umutlu"]
    assert (_tek("[sad+hopeful] Belki.").emotion, _tek("[sad+hopeful] Belki.").blend) == ("üzgün", ["umutlu"])
    seg = _tek("[üzgün+xyz+umutlu+sakin+kızgın] Belki.")                     # bilinmeyen atılır, en çok 2 ikincil
    assert (seg.emotion, seg.blend) == ("üzgün", ["umutlu", "sakin"])
    assert _tek("[üzgün+üzgün] A.").blend == []                              # yinelenen atılır
    assert _tek("[xyz+umutlu] A.").emotion == "umutlu"                       # bilinmeyen birincil atılır
    seg = _tek("[çok üzgün+biraz umutlu] A.")
    assert (seg.emotion, seg.blend, seg.intensity) == ("üzgün", ["umutlu"], 1.35)
    segs = parse_tagged_text("[sakin] A. [üzgün+umutlu: B.] C. [üzgün+umutlu] D. [nefes] E. [mutlu] F.")
    assert [(s.text, s.emotion, s.blend) for s in segs] == [
        ("A.", "sakin", []), ("B.", "üzgün", ["umutlu"]), ("C.", "sakin", []), ("D.", "üzgün", ["umutlu"]),
        ("E.", "üzgün", ["umutlu"]), ("F.", "mutlu", [])]


# ---------- kayış (arc) ----------

@pytest.mark.parametrize("etiket", ["heyecanlı→sakin", "heyecanlı -> sakin", "heyecanlı>sakin", "HEYECANLI → SAKİN",
                                    "excited->calm"])
def test_kayis_ok_bicimleri(etiket):
    seg = _tek(f"[{etiket}] Tamam, tamam. Geçti.")
    assert (seg.text, seg.emotion, seg.arc_to) == ("Tamam, tamam. Geçti.", "heyecanlı", "sakin")


def test_kayis_bolumden_sonra_hedefte_kalir():
    segs = parse_tagged_text("[heyecanlı→sakin] Bir. İki. [nefes] Üç. [hız:0.9] Dört.")
    assert [(s.text, s.emotion, s.arc_to) for s in segs] == [
        ("Bir. İki.", "heyecanlı", "sakin"), ("Üç.", "sakin", None), ("Dört.", "sakin", None)]
    # bekleyen kayış boş bölümle harcanmaz
    segs = parse_tagged_text("[sakinleşerek] [nefes] Geçti.")
    assert [(s.text, s.emotion, s.arc_to, s.pause_before_ms) for s in segs] == [("Geçti.", None, "sakin", 500)]
    # normale kayış ve kaynağı boş kayış (o anki duygudan)
    segs = parse_tagged_text("[kızgın→normal] Yeter. [nefes] Peki. [üzgün] A. [→mutlu] B. C.")
    assert [(s.emotion, s.arc_to) for s in segs] == [("kızgın", "normal"), (None, None), ("üzgün", None),
                                                    ("üzgün", "mutlu")]
    # kapsamlı kayış dış duyguyu değiştirmez; yoğunluk kayışla birlikte yazılabilir
    segs = parse_tagged_text("[heyecanlı] A. [heyecanlı→sakin: B.] C. [çok kızgın→sakin] D.")
    assert [(s.emotion, s.arc_to, s.intensity) for s in segs] == [
        ("heyecanlı", None, 1.0), ("heyecanlı", "sakin", 1.0), ("heyecanlı", None, 1.0), ("kızgın", "sakin", 1.35)]


@pytest.mark.parametrize("etiket, hedef", [*ARC_WORDS.items(), ("SAKİNLEŞEREK", "sakin"), ("sakinleserek", "sakin")])
def test_tek_sozcuk_kayis(etiket, hedef):
    seg = _tek(f"[{etiket}] Peki.")
    assert (seg.emotion, seg.arc_to) == (None, hedef)                       # başta o anki duygu yok
    segs = parse_tagged_text(f"[üzgün] Önce. [{etiket}] Sonra.")
    beklenen = None if hedef == "üzgün" else hedef                          # aynı duyguya kayış etkisiz
    assert (segs[1].text, segs[1].emotion, segs[1].arc_to) == ("Sonra.", "üzgün", beklenen)


def test_kayis_sozlugu_ve_fisildayarak():
    assert ARC_WORDS == {"sakinleşerek": "sakin", "heyecanlanarak": "heyecanlı", "yumuşayarak": "samimi",
                         "sertleşerek": "kızgın", "hüzünlenerek": "üzgün", "neşelenerek": "mutlu",
                         "ciddileşerek": "ciddi", }
    assert all(h in PROFILES for h in ARC_WORDS.values())
    assert not set(ARC_WORDS) & (set(NONVERBAL) | set(PAUSE_TAGS))
    # [fısıldayarak] v3'teki gibi doğrudan fısıltı (kayış değil): fısıltı kaydı referans alınabilsin
    assert (_tek("[fısıldayarak] Bu bir sır.").emotion, _tek("[fısıldayarak] Bu bir sır.").arc_to) == ("fısıltı", None)
    assert [(s.emotion, s.arc_to) for s in parse_tagged_text("[fısıldayarak: Bu bir sır.]")] == [("fısıltı", None)]
    assert resolve("fısıldayarak").name == "fısıltı"


# ---------- hız / perde / konuşmacı ----------

def test_hiz_ve_perde_surekli():
    segs = parse_tagged_text("Önce. [hız:0.9] Bir. [nefes] İki. [üzgün] Üç. [perde:+1] Dört. [hız:normal] Beş. "
                             "[perde] Altı.")
    assert [(s.text, s.rate, s.pitch) for s in segs] == [
        ("Önce.", None, None), ("Bir.", 0.9, None), ("İki.", 0.9, None), ("Üç.", 0.9, None),
        ("Dört.", 0.9, 1.0), ("Beş.", None, 1.0), ("Altı.", None, None)]
    assert segs[3].emotion == "üzgün" and segs[4].emotion == "üzgün"         # duygudan bağımsız


@pytest.mark.parametrize("etiket, alan, deger", [
    ("hız:0.9", "rate", 0.9), ("tempo:0.9", "rate", 0.9), ("HIZ:1,1", "rate", 1.1), ("hiz: 1.3", "rate", 1.3),
    ("hız:0.7", "rate", 0.7), ("hız:%90", "rate", 0.9), ("perde:+1", "pitch", 1.0), ("pitch:-2", "pitch", -2.0),
    ("perde:−1,5", "pitch", -1.5), ("perde:4", "pitch", 4.0), ("PERDE:-4", "pitch", -4.0), ("perde:0", "pitch", 0.0),
])
def test_hiz_perde_degerleri(etiket, alan, deger):
    segs = parse_tagged_text(f"A. [{etiket}] B.")
    assert [s.text for s in segs] == ["A.", "B."]                            # yeni bölüm başlar
    assert getattr(segs[0], alan) is None and getattr(segs[1], alan) == pytest.approx(deger)


@pytest.mark.parametrize("etiket", ["hız:1.5", "hız:0.5", "tempo:2", "perde:+5", "pitch:-4.5", "hız:hızlı",
                                    "perde:yüksek"])
def test_aralik_disi_kontrol_yok_sayilir(etiket):
    seg = _tek(f"A. [{etiket}] B.")
    assert (seg.text, seg.rate, seg.pitch) == ("A. B.", None, None)


def test_hiz_sifirlama_bicimleri():
    for sifirla in ("hız", "hız:normal", "tempo", "Hız: Normal"):
        segs = parse_tagged_text(f"[hız:0.8] A. [{sifirla}] B.")
        assert [s.rate for s in segs] == [0.8, None], sifirla


def test_konusmaci_etiketi():
    segs = parse_tagged_text("[ses:Ayşe] Selam! [nefes] Naber? [konuşmacı: Mehmet  Ali] İyiyim. [heyecanlı] Harika! "
                             "[ses] Anlatıcı.")
    assert [(s.text, s.speaker) for s in segs] == [
        ("Selam!", "Ayşe"), ("Naber?", "Ayşe"), ("İyiyim.", "Mehmet Ali"), ("Harika!", "Mehmet Ali"),
        ("Anlatıcı.", None)]
    assert segs[3].emotion == "heyecanlı" and segs[4].emotion == "heyecanlı"   # konuşmacı duyguyu sıfırlamaz
    assert _tek("[SES:AYŞE] A.").speaker == "AYŞE"                           # ad yazıldığı gibi
    assert _tek("[konusmaci:Dr. Ali] A.").speaker == "Dr. Ali"


# ---------- etkin profil ----------

def test_effective_profile_yogunluk_matematigi():
    p = effective_profile("heyecanlı", 1.4)               # ex 0.7, cfg 0.35, speed 1.04, pause 0.8, kazanç 1.5
    assert p.exaggeration == pytest.approx(0.78)          # 0.5 + 0.2·1.4
    assert p.cfg_weight == pytest.approx(0.3)             # 0.5 − 0.15·1.4 = 0.29 → 0.3 alt sınırı
    assert p.speed == pytest.approx(1.056) and p.pause_mul == pytest.approx(0.72)
    assert p.out_gain_db == pytest.approx(2.1)
    assert p.temperature == 0.9                           # sıcaklık yoğunlukla değişmez
    assert (p.name, p.label, p.aliases) == ("heyecanlı", "Heyecanlı", [])
    u = effective_profile("üzgün", 0.65)
    assert u.exaggeration == pytest.approx(0.37) and u.cfg_weight == pytest.approx(0.5)
    assert u.speed == pytest.approx(0.935) and u.pause_mul == pytest.approx(1.325)
    assert u.out_gain_db == pytest.approx(-1.625)
    assert u.ref_pitch == PROFILES["üzgün"].ref_pitch     # referans alanları ölçeklenmez
    assert effective_profile("kızgın", 1.6).exaggeration == pytest.approx(0.95)    # 1.06 → üst sınır
    assert effective_profile("fısıltı", 1.6).exaggeration == pytest.approx(0.25)   # 0.10 → alt sınır
    assert effective_profile("fısıltı", 1.6).cfg_weight == pytest.approx(0.66)
    h = effective_profile("hızlı", 1.4)                   # None alanlar None kalır (istekteki değer geçerli)
    assert h.exaggeration is None and h.cfg_weight is None and h.speed == pytest.approx(1.168)
    assert effective_profile("heyecanlı", 9) == effective_profile("heyecanlı", 1.6)   # yoğunluk 0.5–1.6


def test_effective_profile_normal_none_ve_yeni_nesne():
    assert effective_profile(None) is None and effective_profile("normal", 1.4) is None
    assert effective_profile("nötr", 0.5, ["umutlu"]) is None and effective_profile("yok-böyle") is None
    assert effective_profile("excited", 1.4).name == "heyecanlı"
    once = repr(PROFILES)
    for ad, prof in PROFILES.items():
        if ad == "normal":
            continue
        e = effective_profile(ad)
        assert e is not prof and e.aliases == [] and prof.aliases, ad      # yeni nesne, eş adlar boş
        assert dataclasses.replace(e, aliases=prof.aliases) == prof, ad    # yoğunluk 1 → değerler aynı
        effective_profile(ad, 1.6, ["sakin", "kızgın"])
    assert repr(PROFILES) == once                                          # PROFILES değişmedi


def test_effective_profile_karisim_ortalamasi():
    p = effective_profile("üzgün", 1.0, ["umutlu"])
    u, h = PROFILES["üzgün"], PROFILES["umutlu"]
    assert (p.name, p.label) == ("üzgün", "Üzgün + Umutlu")
    assert p.exaggeration == pytest.approx(0.7 * 0.3 + 0.3 * 0.55)
    assert p.cfg_weight == pytest.approx(0.5)                      # umutlu'da cfg yok → nötr 0.5
    assert p.temperature == pytest.approx(0.7 * 0.7 + 0.3 * 0.8)    # umutlu'da sıcaklık yok → nötr 0.8
    for alan in ("speed", "pause_mul", "out_gain_db", "ref_pitch", "ref_tempo", "whisper_mix"):
        assert getattr(p, alan) == pytest.approx(0.7 * getattr(u, alan) + 0.3 * getattr(h, alan)), alan
    assert p.out_pitch == u.out_pitch and p.ref_gain_db == u.ref_gain_db   # listede olmayanlar birincilden
    f = effective_profile("fısıltı", 1.0, ["kızgın", "heyecanlı"])           # iki ikincil %15'er
    assert f.label == "Fısıltı + Kızgın + Heyecanlı"
    assert f.compress is False and f.ref_breathy is True                     # bool alanlar birincilden
    assert f.whisper_mix == pytest.approx(0.7)
    assert f.exaggeration == pytest.approx(0.7 * 0.25 + 0.15 * 0.85 + 0.15 * 0.7)
    assert effective_profile("üzgün", 1.0, ["xyz", "üzgün", "umutlu", "umutlu"]) == p   # atılanlar
    assert effective_profile("üzgün", 1.0, ["umutlu", "sakin", "kızgın"]).label == "Üzgün + Umutlu + Sakin"
    q = effective_profile("üzgün", 1.4, ["umutlu"])                          # önce karışım, sonra yoğunluk
    assert q.exaggeration == pytest.approx(0.5 + (0.375 - 0.5) * 1.4)


def test_interpolate_profile():
    a, b = PROFILES["heyecanlı"], PROFILES["sakin"]
    bas, son, orta = interpolate_profile(a, b, 0), interpolate_profile(a, b, 1), interpolate_profile(a, b, 0.5)
    for alan in ("exaggeration", "cfg_weight", "temperature", "speed", "pause_mul", "out_gain_db", "ref_pitch",
                 "out_pitch"):
        assert getattr(bas, alan) == pytest.approx(getattr(a, alan)), alan
        assert getattr(son, alan) == pytest.approx(getattr(b, alan)), alan
        assert getattr(orta, alan) == pytest.approx((getattr(a, alan) + getattr(b, alan)) / 2), alan
    assert [p.name for p in (bas, interpolate_profile(a, b, 0.49), orta, son)] == \
           ["heyecanlı", "heyecanlı", "sakin", "sakin"]
    assert orta.label == "Heyecanlı→Sakin" and orta.aliases == []
    assert interpolate_profile(a, b, -3) == bas and interpolate_profile(a, b, 7) == son   # t sıkıştırılır
    n = interpolate_profile(a, None, 1.0)                  # None taraf = normal profil
    assert n.name == "normal" and n.exaggeration is None and n.label == "Heyecanlı→Normal"
    assert interpolate_profile(a, None, 0.5).exaggeration == pytest.approx(0.6)   # nötr 0.5'e doğru
    assert interpolate_profile(None, None, 0.3).name == "normal"
    assert interpolate_profile(PROFILES["kızgın"], b, 0.25).compress is True      # bool alanlar ad tarafından
    assert interpolate_profile(PROFILES["kızgın"], b, 0.75).compress is False
    assert PROFILES["heyecanlı"].label == "Heyecanlı" and PROFILES["heyecanlı"].aliases


# ---------- vurgu planı ----------

@pytest.mark.parametrize("metin, sozcukler, beklenen", [
    ("Bu çok önemli.", ["çok"], [("Bu", False), ("çok", True), ("önemli.", False)]),
    ("Bu çok önemli bir konu.", ["çok", "önemli"], [("Bu", False), ("çok önemli", True), ("bir konu.", False)]),
    ("Bu önemli.", ["önemli"], [("Bu", False), ("önemli.", True)]),                 # noktalama parçada kalır
    ("İSTANBUL'A gidiyoruz.", ["istanbul"], [("İSTANBUL'A", True), ("gidiyoruz.", False)]),   # tr_lower + kesme
    ("Ankara’ya, yarın!", ["Ankara'ya", "YARIN"], [("Ankara’ya, yarın!", True)]),
    ("Hemen şimdi gel, hemen!", ["hemen şimdi"], [("Hemen şimdi", True), ("gel, hemen!", False)]),   # öbek
    ("«Yarın» gel ve yarın kal.", ["yarın"],
     [("«Yarın»", True), ("gel ve", False), ("yarın", True), ("kal.", False)]),    # her geçiş
    ("Bu çok önemli.", [], [("Bu çok önemli.", False)]),
    ("Bu çok önemli.", ["yok", "  "], [("Bu çok önemli.", False)]),
    ("Bu önemliydi.", ["önemli"], [("Bu önemliydi.", False)]),                     # yalnızca tam sözcük
])
def test_plan_emphasis(metin, sozcukler, beklenen):
    parcalar = plan_emphasis(metin, sozcukler)
    assert parcalar == beklenen
    assert " ".join(p for p, _ in parcalar) == metin                                # birleşim metni verir


def test_plan_emphasis_bosluklar_korunur():
    metin = "Bu  çok\tönemli   bir konu"
    parcalar = plan_emphasis(metin, ["önemli"])
    assert parcalar == [("Bu  çok", False), ("önemli", True), ("bir konu", False)]
    assert " ".join(p for p, _ in parcalar).split() == metin.split()


# ---------- katalog (v4) ----------

def test_tag_catalog_v4_alanlari():
    cat = tag_catalog()
    assert cat["intensity"] == [{"suffix": ":1", "label": "hafif"}, {"suffix": ":2", "label": "normal"},
                                {"suffix": ":3", "label": "güçlü"}, {"suffix": "biraz ", "label": "biraz"},
                                {"suffix": "çok ", "label": "çok"}]
    assert {"tag": "sakinleşerek", "to": "sakin"} in cat["arcs"] and len(cat["arcs"]) == len(ARC_WORDS)
    assert all(_tek(f"[{a['tag']}] A.").arc_to == a["to"] for a in cat["arcs"])
    assert cat["controls"] == [{"tag": "hız:0.9", "label": "Hız"}, {"tag": "perde:+1", "label": "Perde"},
                               {"tag": "ses:Ad", "label": "Konuşmacı"}]
    seg = _tek("".join(f"[{c['tag']}]" for c in cat["controls"]) + " Merhaba.")   # örnekler gerçekten çalışır
    assert (seg.rate, seg.pitch, seg.speaker) == (0.9, 1.0, "Ad")
    for oge in cat["intensity"]:
        s = oge["suffix"]
        etiket = f"[{s}heyecanlı]" if s.endswith(" ") else f"[heyecanlı{s}]"
        assert (_tek(f"{etiket} A.").intensity == 1.0) == (oge["label"] == "normal"), etiket
    # eski alanlar aynen
    assert set(cat) == {"emotions", "nonverbal", "nonverbal_detail", "pauses", "pause_detail",
                        "timed_pause_examples", "emphasis_examples", "scoped_example", "intensity", "arcs", "controls"}
    assert cat["scoped_example"] == "[heyecanlı: Yalnızca bu cümle heyecanlı.]"
    assert cat["timed_pause_examples"] == ["[500 ms]", "[1 sn]", "[1.5 sn]", "[2 saniye]"]
    assert cat["emphasis_examples"] == ["*çok* önemli", "[vurgu] yarın", "[vurgu: hemen şimdi]"]
    assert cat["nonverbal"] == sorted(k for k, v in NONVERBAL.items() if v)
    assert [e["name"] for e in cat["emotions"]] == list(PROFILES)


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
