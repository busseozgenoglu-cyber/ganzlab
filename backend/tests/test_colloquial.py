"""colloquial.py testleri: yazı dili → İstanbul Türkçesi konuşma dili (off / light / full).

Her vaka birebir dizge eşitliğiyle denetlenir. Koruma vakaları (özel ad, isim olarak -ecek, sayı bağlamı,
cümle ortasında büyük harf) her iki seviyede de metnin hiç değişmediğini doğrular.
"""
import unicodedata

import pytest

from app.colloquial import (
    FUTURE_EXCEPTIONS,
    LEVELS,
    RULE_LABELS,
    colloquial_report,
    colloquial_tr,
    normalize_level,
)

# ------------------------------------------------------------------------------------------- light

LIGHT_CASES = [
    # test_text.py'deki sözleşme örnekleri (birebir aynı kalmalı)
    ("Yarın geleceğim, sana bir şey göstereceğim.", "Yarın gelicem, sana bişey göstericem."),
    ("Ne yapacaksın? Hiçbir şey yapmayacağım.", "Napıcaksın? Hiçbişey yapmıycam."),
    ("olacak, görecek, bulacağız, olmayacak", "olucak, görücek, bulucaz, olmıycak"),
    ("Gelecek yıl yiyecek alacak mısın?", "Gelecek yıl yiyecek alıcak mısın?"),
    ("değil mi", "di mi"),
    # gelecek zaman: ünsüzle biten gövde, 4'lü uyum
    ("Yapacağım.", "Yapıcam."),
    ("Bunu yarın yapacaksınız.", "Bunu yarın yapıcaksınız."),
    ("Onlar da gelecekler mi?", "Onlar da gelicekler mi?"),
    ("Kazanacağız!", "Kazanıcaz!"),
    ("Görüşeceğiz.", "Görüşücez."),
    ("Daha çok zaman gerekecek.", "Daha çok zaman gerekicek."),
    ("Bunu yapabilecek misin?", "Bunu yapabilicek misin?"),
    ("Yağmur yağacaktır.", "Yağmur yağıcaktır."),
    ("Yapacaktım ama vazgeçtim.", "Yapıcaktım ama vazgeçtim."),
    ("Ocak ayında taşınacağız.", "Ocak ayında taşınıcaz."),
    ("Bacak ağrısı geçecek.", "Bacak ağrısı geçicek."),
    ("Dilekçe yazacak.", "Dilekçe yazıcak."),
    # gelecek zaman: ünlüyle biten gövde + y, olumsuz
    ("Bence başlayacağız.", "Bence başlıycaz."),
    ("Kitabı okuyacak.", "Kitabı okuycak."),
    ("Seni arayacağım.", "Seni arıycam."),
    ("Gelmeyeceğiz.", "Gelmiycez."),
    ("Görmeyecekler.", "Görmiycekler."),
    ("Yapamayacağım.", "Yapamıycam."),
    ("yapmayacaksın", "yapmıycaksın"),
    ("Sonra ne diyecek?", "Sonra ne dicek?"),
    ("Akşam ne yiyeceğiz?", "Akşam ne yicez?"),
    ("Eve koyacağım.", "Eve koycam."),
    ("Paraları sayacağım.", "Paraları sayıcam."),
    # -acağım yalnız fiil olduğu kesin bağlamda kısalır
    ("Geleceğim ama geç kalacağım.", "Gelicem ama geç kalıcam."),
    ("Geleceğim yarın.", "Gelicem yarın."),
    ("Söyleyeceğim sana bir şey.", "Söyliycem sana bişey."),
    ("Geleceğim ve göreceğim.", "Gelicem ve görücem."),
    ("Hoşça kal, yarın yine geleceğim!", "Hoşça kal, yarın yine gelicem!"),
    # isim olabilen "gelecek / yiyecek": soru eki ya da kesin fiil bağlamında çevrilir
    ("Gelecek hafta geleceğim.", "Gelecek hafta gelicem."),
    ("Yarın gelecek misin?", "Yarın gelicek misin?"),
    ("Yiyecek misin?", "Yicek misin?"),
    ("Ahmet de gelecek.", "Ahmet de gelicek."),
    ("Gelecekte neler olacak?", "Gelecekte neler olucak?"),
    # cümle başı büyük harf çevrilir; Türkçe İ / I
    ("İçeceğim.", "İçicem."),
    ("Isıtacağım.", "Isıtıcam."),
    ("İçeceğim.", "İçicem."),  # ayrık yazılmış "İ" (NFD)
    ("Tamam.\nGeleceğim", "Tamam.\nGelicem"),
    ("Konuşmacı: Geleceğim.", "Konuşmacı: Gelicem."),
    # tırnak içi de konuşulur
    ('Annem "Yarın geleceğim" dedi.', 'Annem "Yarın gelicem" dedi.'),
    ('O "Yapacağım" dedi.', 'O "Yapıcam" dedi.'),
    # bişey / hiçbişey / herşey
    ("Bir şeyler oldu.", "Bişeyler oldu."),
    ("hiç bir şey", "hiçbişey"),
    ("hiçbir şeyi", "hiçbişeyi"),
    ("bir şeyden", "bişeyden"),
    ("Her şeyi biliyor.", "Herşeyi biliyor."),
    ("Bir gün her şey düzelecek.", "Bi gün herşey düzelicek."),
    # kalıp "bi"ler
    ("Bir dakika bekle.", "Bi dakka bekle."),
    ("Bir tane daha ver.", "Bi tane daha ver."),
    ("Birkaç gün sonra.", "Bikaç gün sonra."),
    ("bir kaç kişi", "bikaç kişi"),
    ("birtakım sorunlar", "bitakım sorunlar"),
    ("Bir sürü insan vardı.", "Bi sürü insan vardı."),
    ("Bir şekilde hallederiz.", "Bi şekilde hallederiz."),
    ("bir yere gidelim", "bi yere gidelim"),
    ("Bir zamanlar bir kral varmış.", "Bi zamanlar bir kral varmış."),
    ("Bir de şuna bak.", "Bi de şuna bak."),
    ("Söz veriyorum, bir daha yapmayacağım.", "Söz veriyorum, bi daha yapmıycam."),
    # ne kaynaşmaları
    ("Ne haber?", "Naber?"),
    ("Ne oldu?", "Noldu?"),
    ("Burada ne oluyor?", "Burada noluyor?"),
    ("Ne olur gel.", "Nolur gel."),
    ("Peki şimdi ne olacak?", "Peki şimdi nolucak?"),
    ("Ne yapıyorsun?", "Napıyorsun?"),
    ("Ne yaptın?", "Naptın?"),
    ("Ne olursa olsun.", "Nolursa olsun."),
    # istek kipi 1. tekil (ünsüzle biten fiil gövdesi, 4'lü uyum)
    ("Ağabey, geleyim mi?", "Abi, geliyim mi?"),
    ("Bir bakayım.", "Bi bakıyım."),
    ("Bunu bulayım, sonra göreyim.", "Bunu buluyum, sonra görüyüm."),
    ("Yardım edeyim.", "Yardım ediyim."),
    ("Sana bir şey söyleyeyim.", "Sana bişey söyliyim."),
    # ile → -(y)la / -(y)le
    ("Okula araba ile geldim.", "Okula arabayla geldim."),
    ("Dün annem ile konuştum.", "Dün annemle konuştum."),
    ("Dün Ahmet ile buluştuk.", "Dün Ahmet'le buluştuk."),
    ("Dün Ayşe ile otobüs ile gittik.", "Dün Ayşe'yle otobüsle gittik."),
    ("Ahmet Gelecek ile konuştu.", "Ahmet Gelecek'le konuştu."),
    ("Lütfen dikkat ile dinle.", "Lütfen dikkatle dinle."),
    ("Bu iş saat ile ölçülmez.", "Bu iş saatle ölçülmez."),
    ("Ne ile gittin?", "Neyle gittin?"),
    ("Bir şey ile uğraşıyorum.", "Bişeyle uğraşıyorum."),
    ("Dün Ahmet’le değil, Ayşe ile gittim.", "Dün Ahmet’le değil, Ayşe’yle gittim."),  # tipografik kesme korunur
    # sözlük
    ("Herhalde yağmur yağacak.", "Heralde yağmur yağıcak."),
    ("Ağabeyimle konuştum.", "Abimle konuştum."),
    # noktalama ve boşluk olduğu gibi kalır
    ("  Yarın   geleceğim!!  ", "  Yarın   gelicem!!  "),
]


@pytest.mark.parametrize("src, expected", LIGHT_CASES)
def test_light(src, expected):
    assert colloquial_tr(src, "light") == expected


def test_default_level_is_light():
    for src, expected in LIGHT_CASES:
        assert colloquial_tr(src) == expected


# -------------------------------------------------------------------------------------------- full

FULL_CASES = [
    ("Geliyorum.", "Geliyom."),
    ("geliyor, geliyoruz, geliyorsun, geliyorsunuz, geliyorlar", "geliyo, geliyoz, geliyosun, geliyosunuz, geliyolar"),
    ("Bilmiyorum, biliyor musun?", "Bilmiyom, biliyo musun?"),
    ("Ne yapıyorsun?", "Napıyosun?"),
    ("Böyle olmaz, şöyle yap.", "Böle olmaz, şöle yap."),
    ("Öyle mi?", "Öle mi?"),
    ("Bu doğru değil.", "Bu doğru diil."),
    ("değilim, değilsin, değildi, değilmiş", "diilim, diilsin, diildi, diilmiş"),
    ("Bu doğru değil mi?", "Bu doğru di mi?"),
    ("Bir araba aldım.", "Bi araba aldım."),
    ("Bir zamanlar bir kral varmış.", "Bi zamanlar bi kral varmış."),
    ("bir takım kurduk", "bi takım kurduk"),
    ("Sıcak bir çorba içeceğim.", "Sıcak bi çorba içicem."),
    ("bir kalem ile yaz", "bi kalemle yaz"),
    ("Bir değil, iki değil.", "Bir diil, iki diil."),
    ("Öyle değil, bir araba geliyor.", "Öle diil, bi araba geliyo."),
    ("bir şeytan", "bi şeytan"),  # "şey" değil: "bişeytan" diye birleşmez
    # light kuralları full'da da geçerli
    ("Yarın geleceğim, sana bir şey göstereceğim.", "Yarın gelicem, sana bişey göstericem."),
    ("Ne yapacaksın? Hiçbir şey yapmayacağım.", "Napıcaksın? Hiçbişey yapmıycam."),
]


@pytest.mark.parametrize("src, expected", FULL_CASES)
def test_full(src, expected):
    assert colloquial_tr(src, "full") == expected


# full'a özgü kurallar light'ta uygulanmaz
LIGHT_KEEPS = [
    "Geliyorum.",
    "Biliyor musun?",
    "Geliyordu, geliyormuş, geliyorsa, geliyorken.",
    "Böyle olmaz, şöyle yap.",
    "Öyle mi?",
    "Bu doğru değil.",
    "Bir araba aldım.",
    "bir takım kurduk",
    "bir şeytan",
]


@pytest.mark.parametrize("src", LIGHT_KEEPS)
def test_light_skips_full_only_rules(src):
    assert colloquial_tr(src, "light") == src


# ------------------------------------------------------------------- koruma: iki seviyede de değişmez

PROTECTED = [
    # özel ad / cümle ortasında büyük harf, kesme işareti, kısaltma, karışık büyük harf
    "Dün Yapacak Bey geldi.",
    "Gelecek'i konuştuk.",
    "İSTANBUL'A GİDECEĞİM",
    "Ahmet Öyle dedi.",
    "Ne Yapacaksın",
    "Ahmet Bir gün",
    "Bunu Google ile ara.",
    "iPhone ile çektim.",
    "THY ile uçtuk.",
    "Kemal ile konuştum.",  # cümle başı: özel ad mı cins ad mı bilinmez
    # isim olarak -ecek / -acak ve gelecek zaman olmayan sonlar
    "Önemli olan gelecek.",
    "Gelecek nesiller",
    "Geçmiş de gelecek de önemli.",
    "Önemli olan hem geçmiş hem de gelecek.",
    "Geçmiş ya da gelecek.",
    "İçecek ne var?",
    "Silecek bozuldu.",
    "Alacaklar listesi",
    "uçak, bıçak, çiçek, böcek, gerçek, köpek, kelebek, sıcak, ocak, ancak",
    "Kocacağız çok yoruldu.",
    # sıfat-fiil (-acağım + isim), iyelik
    "Benim geleceğim parlak.",
    "Gideceğim yer çok uzak.",
    "Söyleyeceğim şey şu.",
    "Yapacakları belli.",
    "Ondan alacağım var.",
    "Yapacağım ve yapmayacağım şeyler var.",
    # sayı bağlamı
    "Bir milyon lira",
    "bir iki üç",
    "on bir gün",
    "yüz bir kişi",
    "bin bir gece",
    "bir bir saydı",
    "Saat bir buçukta",
    "Sadece bir.",
    "üç, iki, bir!",
    "on bir şey",
    "Saat beş ile altı arası.",
    # ünlüyle biten gövdede istek kipi, isim + ek-fiil, 1. çoğul istek
    "Okuyayım mı?",
    "Başlayayım.",
    "Hastayım, evdeyim.",
    "Buradayım.",
    "Şimdi yapalım.",
    # benzer görünen sözcükler
    "ne yaprak ne dal",
    "ne olay ama",
    "Ne için geldin?",
    "Nasıl yani?",
    "Şu anda içindeyim.",
    "",
    "123 456",
]


@pytest.mark.parametrize("src", PROTECTED)
@pytest.mark.parametrize("level", ["light", "full"])
def test_protected_unchanged(src, level):
    assert colloquial_tr(src, level) == src
    assert colloquial_report(src, level) == []


@pytest.mark.parametrize("word", sorted(FUTURE_EXCEPTIONS))
def test_future_exceptions_untouched(word):
    assert colloquial_tr(f"dün {word} vardı", "full") == f"dün {word} vardı"


def test_exception_list_covers_contract():
    for w in ("gelecek", "gelecekte", "geleceği", "yiyecek", "içecek", "giyecek", "yakacak", "sıcak", "ocak",
              "bucak", "kaçak", "ancak", "sancak", "kucak", "çiçek", "böcek", "gerçek", "gerçekten", "bebek",
              "köpek", "kelebek", "mercek", "direk", "tümsek", "kösele", "erek"):
        assert w in FUTURE_EXCEPTIONS


# ---------------------------------------------------------------------------------------- idempotence

CORPUS = sorted({s for s, _ in LIGHT_CASES} | {s for s, _ in FULL_CASES} | set(LIGHT_KEEPS) | set(PROTECTED))


@pytest.mark.parametrize("level", ["light", "full"])
def test_idempotent(level):
    for src in CORPUS:
        once = colloquial_tr(src, level)
        assert colloquial_tr(once, level) == once, src


# ---------------------------------------------------------------------------------------- off / bool

@pytest.mark.parametrize("off", ["off", False, None, "kapalı", "OFF"])
def test_off_returns_text_unchanged(off):
    for src in CORPUS:
        assert colloquial_tr(src, off) == src
        assert colloquial_report(src, off) == []


def test_bool_true_is_light():
    for src in CORPUS:
        assert colloquial_tr(src, True) == colloquial_tr(src, "light")


def test_levels_constant():
    assert LEVELS == ("off", "light", "full")


@pytest.mark.parametrize("value, expected", [
    ("light", "light"), ("LIGHT", "light"), (" full ", "full"), ("off", "off"), (True, "light"), (False, "off"),
    (None, "off"), ("hafif", "light"), ("HAFİF", "light"), ("Tam", "full"), ("samimi", "full"), ("KAPALI", "off"),
])
def test_normalize_level(value, expected):
    assert normalize_level(value) == expected


@pytest.mark.parametrize("value", ["orta", "xyz", 3, 1.5, ["light"]])
def test_invalid_level_raises(value):
    with pytest.raises(ValueError):
        colloquial_tr("Yarın geleceğim.", value)


# --------------------------------------------------------------------------------------------- rapor

def test_report_simple():
    assert colloquial_report("Yarın geleceğim.") == [{"from": "geleceğim", "to": "gelicem", "rule": "gelecek-zaman"}]


def test_report_combined_rules():
    assert colloquial_report("Ne yapacaksın?") == [
        {"from": "Ne yapacaksın", "to": "Napıcaksın", "rule": "gelecek-zaman+ne-kaynaşma"},
    ]
    assert colloquial_report("Bir bakayım, Ahmet ile gelirim.") == [
        {"from": "Bir bakayım", "to": "Bi bakıyım", "rule": "istek-kipi+bi"},
        {"from": "Ahmet ile", "to": "Ahmet'le", "rule": "ile"},
    ]


def test_report_levels():
    assert colloquial_report("Geliyorum, değil mi?", "light") == [{"from": "değil mi", "to": "di mi", "rule": "di-mi"}]
    assert colloquial_report("Geliyorum, değil mi?", "full") == [
        {"from": "Geliyorum", "to": "Geliyom", "rule": "yor"},
        {"from": "değil mi", "to": "di mi", "rule": "di-mi"},
    ]


@pytest.mark.parametrize("level", ["light", "full"])
def test_report_consistent_with_output(level):
    for src in CORPUS:
        out = colloquial_tr(src, level)
        report = colloquial_report(src, level)
        assert (out != src) == bool(report), src  # değişiklik varsa rapor da var, yoksa boş
        for item in report:
            assert set(item) == {"from", "to", "rule"}
            assert item["from"] != item["to"]
            assert item["from"] in unicodedata.normalize("NFC", src)
            assert item["to"] in out
            for rule in item["rule"].split("+"):
                assert rule in RULE_LABELS
