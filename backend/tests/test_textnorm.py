"""textnorm — Türkçe normalizasyon kuralları için kapsamlı testler.

Her kural için en az iki örnek (parametreli pytest). Beklenen çıktılar, bir Türk spikerin metni okurken
söyleyeceği sözcüklerdir; `normalize` sonrasındaki noktalama temizliği de dahildir.
"""
import json
import re
import time

import pytest

from app import config
from app.textnorm import (
    attach_suffix,
    normalize,
    normalize_tr,
    read_money_tr,
    read_number_tr,
    read_time_tr,
    spell_acronym,
    tr_int_to_words,
    tr_ordinal,
)


def tr(metin: str) -> str:
    """Kısa yol: Türkçe normalizasyon."""
    return normalize(metin, "tr")


def kontrol(girdi: str, beklenen: str) -> None:
    sonuc = tr(girdi)
    assert sonuc == beklenen, f"\n girdi   : {girdi!r}\n beklenen: {beklenen!r}\n sonuç   : {sonuc!r}"


# =============================================================================
# 0. Temel sayı okuma
# =============================================================================

@pytest.mark.parametrize("n, beklenen", [
    (0, "sıfır"), (7, "yedi"), (10, "on"), (19, "on dokuz"), (100, "yüz"), (101, "yüz bir"),
    (1000, "bin"), (1001, "bin bir"), (2026, "iki bin yirmi altı"), (1_000_000, "bir milyon"),
    (1_250_000, "bir milyon iki yüz elli bin"), (3_000_000_000, "üç milyar"), (-5, "eksi beş"),
])
def test_tam_sayi_okuma(n, beklenen):
    assert tr_int_to_words(n) == beklenen


@pytest.mark.parametrize("n, beklenen", [
    (1, "birinci"), (2, "ikinci"), (3, "üçüncü"), (4, "dördüncü"), (6, "altıncı"), (9, "dokuzuncu"),
    (10, "onuncu"), (20, "yirminci"), (40, "kırkıncı"), (100, "yüzüncü"), (1000, "bininci"),
])
def test_sira_sayisi_okuma(n, beklenen):
    assert tr_ordinal(n) == beklenen


@pytest.mark.parametrize("rakamlar, beklenen", [
    ("0", "sıfır"), ("00", "sıfır sıfır"), ("05", "sıfır beş"), ("0850", "sıfır sekiz yüz elli"),
    ("007", "sıfır sıfır yedi"), ("123", "yüz yirmi üç"),
])
def test_bastaki_sifirlar_tek_tek_okunur(rakamlar, beklenen):
    assert read_number_tr(rakamlar) == beklenen


# =============================================================================
# 1. Türkçe büyük/küçük harf (İ/ı) — str.lower() hatası olmamalı
# =============================================================================

@pytest.mark.parametrize("girdi, beklenen", [
    ("instagram", "İnstagram"),
    ("INSTAGRAM", "İnstagram"),
    ("İnstagram'da", "İnstagramda"),
    ("TÜBİTAK", "tübitak"),
    ("İst. ve Ank.", "İstanbul ve Ankara"),
])
def test_turkce_buyuk_kucuk_harf(girdi, beklenen):
    kontrol(girdi, beklenen)


def test_birlesik_nokta_kalmaz():
    # "İ".lower() → "i\u0307" (i + U+0307) hatası çıktıya sızmamalı
    assert "\u0307" not in tr("TÜBİTAK ve TOKİ İSTANBUL'da")


# =============================================================================
# 2. Para
# =============================================================================

@pytest.mark.parametrize("tutar, birim, beklenen", [
    ("12,50", "lira", "on iki lira elli kuruş"),
    ("1.250,75", "TL", "bin iki yüz elli lira yetmiş beş kuruş"),
    ("12,00", "TL", "on iki lira"),
    ("0,50", "₺", "elli kuruş"),
    ("12.50", "$", "on iki dolar elli sent"),
    ("3,25", "€", "üç euro yirmi beş sent"),
    ("3,25", "£", "üç sterlin yirmi beş peni"),
    ("12,5", "lira", "on iki lira elli kuruş"),
])
def test_read_money_tr(tutar, birim, beklenen):
    assert read_money_tr(tutar, birim) == beklenen


@pytest.mark.parametrize("girdi, beklenen", [
    ("₺150", "yüz elli lira"),
    ("150₺", "yüz elli lira"),
    ("150 TL", "yüz elli lira"),
    ("150 tl", "yüz elli lira"),
    ("150 TRY", "yüz elli lira"),
    ("$100", "yüz dolar"),
    ("100$", "yüz dolar"),
    ("100 USD", "yüz dolar"),
    ("100 dolar", "yüz dolar"),
    ("€20", "yirmi euro"),
    ("20 EUR", "yirmi euro"),
    ("£5", "beş sterlin"),
    ("5 GBP", "beş sterlin"),
    ("12.50$", "on iki dolar elli sent"),
    ("12,50 TL", "on iki lira elli kuruş"),
    ("1.250,75 TL", "bin iki yüz elli lira yetmiş beş kuruş"),
    ("12,00 TL", "on iki lira"),
    ("₺1.250", "bin iki yüz elli lira"),
    ("$1,250.75", "bin iki yüz elli dolar yetmiş beş sent"),
])
def test_para_bicimleri(girdi, beklenen):
    kontrol(girdi, beklenen)


@pytest.mark.parametrize("girdi, beklenen", [
    ("150 TL'ye", "yüz elli liraya"),
    ("12,50 TL'ye", "on iki lira elli kuruşa"),
    ("50 TL'lik", "elli liralık"),
    ("5 liralık", "beş liralık"),
    ("100 TL'den", "yüz liradan"),
])
def test_para_ekleri_okunusa_uyar(girdi, beklenen):
    kontrol(girdi, beklenen)


@pytest.mark.parametrize("girdi, beklenen", [
    ("1 milyon TL", "bir milyon lira"),
    ("2,5 milyar $", "iki buçuk milyar dolar"),
    ("500 bin TL'ye", "beş yüz bin liraya"),
    ("beş yüz TL", "beş yüz lira"),
    ("100-150 TL arası", "yüz, yüz elli lira arası"),
])
def test_olcekli_ve_aralikli_para(girdi, beklenen):
    kontrol(girdi, beklenen)


def test_fiyat_etiketi_eski_sozlesme():
    # Eski sözleşme (test_text.py): 999,90 ₺ fiyat etiketi gibi "virgül"le okunur.
    assert "dokuz yüz doksan dokuz virgül doksan lira" in tr("İndirimle 999,90 ₺.")
    # Fiyat etiketi olmayan kuruşlu tutar kuruşla okunur.
    kontrol("1.250,90 TL", "bin iki yüz elli lira doksan kuruş")


@pytest.mark.parametrize("girdi, beklenen", [
    ("USD 100", "yüz dolar"),                 # önekli kod
    ("try 5 times", "try beş times"),         # İngilizce "try" para kodu değildir
    ("5,2 mly dolar", "beş virgül iki milyar dolar"),
    ("$5 milyon", "beş milyon dolar"),
])
def test_para_kod_ve_olcek_ayrintilari(girdi, beklenen):
    kontrol(girdi, beklenen)


# =============================================================================
# 3. Yüzde / binde
# =============================================================================

@pytest.mark.parametrize("girdi, beklenen", [
    ("%20", "yüzde yirmi"),
    ("20%", "yüzde yirmi"),
    ("% 20", "yüzde yirmi"),
    ("%12,5", "yüzde on iki buçuk"),
    ("%0,5", "yüzde sıfır virgül beş"),
    ("%20'lik indirim", "yüzde yirmilik indirim"),
    ("%50'si", "yüzde ellisi"),
    ("%100 pamuk", "yüzde yüz pamuk"),
    ("%20-30", "yüzde yirmi otuz"),
    ("‰5", "binde beş"),
    ("Oran %3,5'ten %4'e çıktı.", "Oran yüzde üç buçuktan yüzde dörde çıktı."),
])
def test_yuzde(girdi, beklenen):
    kontrol(girdi, beklenen)


# =============================================================================
# 4. Ondalık ve binlik
# =============================================================================

@pytest.mark.parametrize("girdi, beklenen", [
    ("2,5", "iki buçuk"),
    ("1,5 kg", "bir buçuk kilogram"),
    ("0,5", "sıfır virgül beş"),
    ("2,75", "iki virgül yetmiş beş"),
    ("2,05", "iki virgül sıfır beş"),
    ("2.5", "iki buçuk"),
    ("3.14", "üç nokta on dört"),
    ("1.250.000 kişi", "bir milyon iki yüz elli bin kişi"),
    ("3,14159", "üç virgül bir dört bir beş dokuz"),
    ("192.168.1.1", "yüz doksan iki nokta yüz altmış sekiz nokta bir nokta bir"),
])
def test_ondalik_ve_binlik(girdi, beklenen):
    kontrol(girdi, beklenen)


# =============================================================================
# 5. Saat
# =============================================================================

@pytest.mark.parametrize("saat, dakika, beklenen", [
    (14, 30, "on dört otuz"),
    (14, 5, "on dört sıfır beş"),
    (14, 0, "on dört"),
    (9, 0, "dokuz"),
    (0, 15, "sıfır on beş"),
])
def test_read_time_tr(saat, dakika, beklenen):
    assert read_time_tr(saat, dakika) == beklenen


@pytest.mark.parametrize("girdi, beklenen", [
    ("14:30", "on dört otuz"),
    ("9:05", "dokuz sıfır beş"),
    ("14.30", "on dört otuz"),
    ("saat 14.30", "saat on dört otuz"),
    ("Saat: 09.30", "Saat: dokuz otuz"),
    ("saat 10.05", "saat on sıfır beş"),
    ("saat 5'te", "saat beşte"),
    ("14:30'da", "on dört otuzda"),
    ("14.30'da", "on dört otuzda"),
    ("9.45'te", "dokuz kırk beşte"),
    ("Saat 18:00'de kapanıyoruz.", "Saat on sekizde kapanıyoruz."),
    ("09:00-18:00 arası", "dokuz, on sekiz arası"),
])
def test_saat(girdi, beklenen):
    kontrol(girdi, beklenen)


# =============================================================================
# 6. Tarih ve sayı + kesme + ek
# =============================================================================

@pytest.mark.parametrize("girdi, beklenen", [
    ("12.10.2026", "on iki ekim iki bin yirmi altı"),
    ("12/10/2026", "on iki ekim iki bin yirmi altı"),
    ("12-10-2026", "on iki ekim iki bin yirmi altı"),
    ("2026-10-12", "on iki ekim iki bin yirmi altı"),
    ("12.10", "on iki ekim"),
    ("01.05.2026", "bir mayıs iki bin yirmi altı"),
    ("12.10.2026'da", "on iki ekim iki bin yirmi altıda"),
    ("12/2024", "aralık iki bin yirmi dört"),
])
def test_tarih(girdi, beklenen):
    kontrol(girdi, beklenen)


@pytest.mark.parametrize("girdi, beklenen", [
    ("1990'larda", "bin dokuz yüz doksanlarda"),
    ("2024'te", "iki bin yirmi dörtte"),
    ("2023'ten", "iki bin yirmi üçten"),
    ("5'e", "beşe"),
    ("2'ye", "ikiye"),
    ("100'ü", "yüzü"),
    ("3'ün", "üçün"),
    ("4'e", "dörde"),
    ("24'ü", "yirmi dördü"),
    ("50'li yıllar", "ellili yıllar"),
    ("5'er kişi", "beşer kişi"),
    ("1'den 10'a kadar", "birden ona kadar"),
])
def test_sayi_kesme_ek(girdi, beklenen):
    kontrol(girdi, beklenen)


# =============================================================================
# 7. Sıra sayıları ve Roma rakamları
# =============================================================================

@pytest.mark.parametrize("girdi, beklenen", [
    ("3. sınıf", "üçüncü sınıf"),
    ("21. yüzyılda", "yirmi birinci yüzyılda"),
    ("1'inci", "birinci"),
    ("2'nci", "ikinci"),
    ("3'üncüsü", "üçüncüsü"),
    ("II. Dünya Savaşı", "ikinci Dünya Savaşı"),
    ("XX. yüzyıl", "yirminci yüzyıl"),
    ("III. Selim", "üçüncü Selim"),
    ("XIV. Louis", "on dördüncü Louis"),
    ("Gül Mah. 5. Sok.", "Gül mahallesi beşinci sokak"),
    ("Bölüm II", "Bölüm iki"),
])
def test_sira_sayilari(girdi, beklenen):
    kontrol(girdi, beklenen)


@pytest.mark.parametrize("girdi, beklenen", [
    ("Saat 5. Ahmet geldi.", "Saat beş. Ahmet geldi."),   # büyük harf: cümle sonu sayılır
    ("Bu bir CD. Sonra bakarız.", "Bu bir si di. Sonra bakarız."),   # CD Roma rakamı sayılmaz
])
def test_sira_sayisi_olmayanlar(girdi, beklenen):
    kontrol(girdi, beklenen)


# =============================================================================
# 8. Kısaltmalar — harf harf okuma
# =============================================================================

@pytest.mark.parametrize("kisaltma, beklenen", [
    ("ABD", "a be de"), ("KDV", "ka de ve"), ("TBMM", "te be me me"), ("CHP", "ce he pe"),
    ("PTT", "pe te te"), ("THY", "te he ye"), ("TRT", "te re te"), ("ÖSYM", "ö se ye me"),
    ("YKS", "ye ka se"), ("KPSS", "ka pe se se"), ("LGS", "le ge se"), ("AB", "a be"), ("BM", "be me"),
    ("TC", "te ce"), ("TL", "te le"), ("SGK", "se ge ka"), ("ÇĞ", "çe yumuşak ge"), ("QWX", "kü çift ve iks"),
])
def test_spell_acronym(kisaltma, beklenen):
    assert spell_acronym(kisaltma) == beklenen


@pytest.mark.parametrize("girdi, beklenen", [
    # İngilizce harf adlarıyla bilinen okunuşlar
    ("SMS", "es em es"), ("PDF", "pe de fe"), ("CD", "si di"), ("DVD", "di vi di"), ("USB", "yu es bi"),
    ("TV", "te ve"), ("ATM", "a te me"), ("PC", "pi si"), ("CV", "si vi"), ("DJ", "di cey"),
    ("AI", "yapay zeka"), ("IT", "ay ti"), ("HR", "eyç ar"), ("DNA", "de en a"), ("URL", "yu ar el"),
    ("HTML", "eyç ti em el"), ("CPU", "si pi yu"), ("GPU", "ci pi yu"), ("SSD", "es es di"),
    ("HDD", "eyç di di"), ("AVM", "a ve me"), ("GSM", "ge se me"), ("BMW", "be me ve"),
    ("4K", "dört ka"), ("5G", "beş ge"), ("3D", "üç de"), ("2D", "iki de"), ("MP3", "em pe üç"),
    # sözcük gibi okunanlar (küçük harfe çevrilir)
    ("NATO", "nato"), ("NASA", "nasa"), ("UNICEF", "unisef"), ("UNESCO", "unesko"), ("FIFA", "fifa"),
    ("UEFA", "uefa"), ("TÜBİTAK", "tübitak"), ("ASELSAN", "aselsan"), ("TOKİ", "toki"), ("MEB", "meb"),
    ("TÜİK", "tüik"), ("TEOG", "teog"), ("TOEFL", "tofıl"), ("IELTS", "aylts"), ("LASER", "lazer"),
    ("RADAR", "radar"), ("VIP", "vip"), ("RAM", "ram"), ("LED", "led"), ("OLED", "oled"),
])
def test_bilinen_kisaltmalar(girdi, beklenen):
    kontrol(girdi, beklenen)


@pytest.mark.parametrize("girdi, beklenen", [
    ("AKP İBB EYT DSİ", "a ka pe i be be e ye te de se i"),   # sözlükte yok, hece yapısı Türkçe değil
    ("A4 kağıt", "a dört kağıt"),
    ("H2O", "he iki o"),
    ("A101", "a yüz bir"),
])
def test_bilinmeyen_kisaltma_kurali(girdi, beklenen):
    kontrol(girdi, beklenen)


@pytest.mark.parametrize("girdi, beklenen", [
    ("ABD'de", "a be dede"),
    ("KDV'si", "ka de vesi"),
    ("TBMM'de", "te be me mede"),
    ("NATO'ya", "natoya"),
    ("SMS'i", "es em esi"),
    ("ATM'den", "a te meden"),
    ("5G'ye", "beş geye"),
])
def test_kisaltma_ekleri(girdi, beklenen):
    kontrol(girdi, beklenen)


@pytest.mark.parametrize("girdi", [
    "ARTIK YETER", "BU KAMPANYA ÇOK İYİ", "STOK PLAN TREN", "STRES SPREY", "AL ON EV", "ŞİMDİ HEMEN GEL",
])
def test_bagirma_yazimina_dokunulmaz(girdi):
    kontrol(girdi, girdi)


@pytest.mark.parametrize("girdi, beklenen", [
    ("sms at", "es em es at"),
    ("pdf dosyası", "pe de fe dosyası"),
    ("it ürür kervan yürür", "it ürür kervan yürür"),   # küçük "it" Türkçe sözcüktür
])
def test_kucuk_harfli_kisaltmalar(girdi, beklenen):
    kontrol(girdi, beklenen)


# =============================================================================
# 9. Aralık ve matematik
# =============================================================================

@pytest.mark.parametrize("girdi, beklenen", [
    ("3-4 kişi", "üç dört kişi"),
    ("10-15 dk", "on on beş dakika"),
    ("2010-2015", "iki bin on, iki bin on beş"),
    ("2010–2015", "iki bin on, iki bin on beş"),
    ("70-85 milyon", "yetmiş, seksen beş milyon"),
    ("Fenerbahçe 3-1 kazandı.", "Fenerbahçe üç bir kazandı."),
    ("5x3", "beş çarpı üç"),
    ("5 x 3", "beş çarpı üç"),
    ("120x60x75 cm", "yüz yirmi çarpı altmış çarpı yetmiş beş santimetre"),
    ("10/2", "on bölü iki"),
    ("1/2", "yarım"),
    ("1/4", "çeyrek"),
    ("3/4", "dörtte üç"),
    ("2/3", "üçte iki"),
    ("1/2'si", "yarısı"),
    ("7/24 açık", "yedi yirmi dört açık"),
    ("5+3", "beş artı üç"),
    ("3+1 daire", "üç artı bir daire"),
    ("5-3=2", "beş eksi üç eşittir iki"),
    ("2x3=6", "iki çarpı üç eşittir altı"),
    ("-5 derece", "eksi beş derece"),
    ("±5", "artı eksi beş"),
    ("5 < 10", "beş küçüktür on"),
    ("5 > 3", "beş büyüktür üç"),
    ("3:1", "üçe bir"),
    ("2x daha hızlı", "iki kat daha hızlı"),
])
def test_aralik_ve_matematik(girdi, beklenen):
    kontrol(girdi, beklenen)


# =============================================================================
# 10. Birimler
# =============================================================================

@pytest.mark.parametrize("girdi, beklenen", [
    ("5 km", "beş kilometre"),
    ("5km", "beş kilometre"),
    ("5 km²", "beş kilometrekare"),
    ("5 km2", "beş kilometrekare"),
    ("20 cm²", "yirmi santimetrekare"),
    ("100 m2", "yüz metrekare"),
    ("10 m/s", "on metre saniye"),
    ("40 km/sa", "kırk kilometre saat"),
    ("250 kcal", "iki yüz elli kilokalori"),
    ("90 cal", "doksan kalori"),
    ("5000 mAh", "beş bin miliamper saat"),
    ("100 W", "yüz vat"),
    ("2 kW", "iki kilovat"),
    ("3 kWh", "üç kilovatsaat"),
    ("220 V", "iki yüz yirmi volt"),
    ("50 Hz", "elli hertz"),
    ("80 dB", "seksen desibel"),
    ("1080 px", "bin seksen piksel"),
    ("60 fps", "altmış ef pi es"),
    ("200 ms", "iki yüz milisaniye"),
    ("5 dk'da", "beş dakikada"),
    ("5 min", "beş dakika"),
    ("5 cm'lik", "beş santimetrelik"),
    ("25°C", "yirmi beş derece"),
    ("25 °F", "yirmi beş fahrenhayt derece"),
    ("45°", "kırk beş derece"),
    ("180°'ye ısıtın", "yüz seksen dereceye ısıtın"),
    ("5 g", "beş gram"),
    ("2 L", "iki litre"),
    ("10K takipçi", "on bin takipçi"),
    ("1.5M", "bir buçuk milyon"),
])
def test_birimler(girdi, beklenen):
    kontrol(girdi, beklenen)


@pytest.mark.parametrize("girdi, beklenen", [
    ("MS 500", "milattan sonra beş yüz"),
    ("M.Ö. 300", "milattan önce üç yüz"),
    ("M.S. 1453", "milattan sonra bin dört yüz elli üç"),
])
def test_milattan_once_sonra(girdi, beklenen):
    kontrol(girdi, beklenen)


# =============================================================================
# 11. Telefon / IBAN / kart
# =============================================================================

@pytest.mark.parametrize("girdi, beklenen", [
    ("0532 123 45 67", "sıfır beş yüz otuz iki, yüz yirmi üç, kırk beş, altmış yedi"),
    ("0 (532) 123 45 67", "sıfır beş yüz otuz iki, yüz yirmi üç, kırk beş, altmış yedi"),
    ("(0532) 123 45 67", "sıfır beş yüz otuz iki, yüz yirmi üç, kırk beş, altmış yedi"),
    ("+90 532 123 45 67", "artı doksan, beş yüz otuz iki, yüz yirmi üç, kırk beş, altmış yedi"),
    ("05321234567", "sıfır beş yüz otuz iki, yüz yirmi üç, kırk beş, altmış yedi"),
    ("5321234567", "beş yüz otuz iki, yüz yirmi üç, kırk beş, altmış yedi"),
    ("0850 222 00 00", "sıfır sekiz yüz elli, iki yüz yirmi iki, sıfır sıfır, sıfır sıfır"),
    ("0532-123-45-67", "sıfır beş yüz otuz iki, yüz yirmi üç, kırk beş, altmış yedi"),
    ("444 0 444", "dört yüz kırk dört, sıfır, dört yüz kırk dört"),
    ("1234 5678 9012 3456", "bin iki yüz otuz dört, beş bin altı yüz yetmiş sekiz, dokuz bin on iki, "
                            "üç bin dört yüz elli altı"),
    ("0850 123 45 67'yi arayın", "sıfır sekiz yüz elli, yüz yirmi üç, kırk beş, altmış yediyi arayın"),
    ("Tel: 0532 123 45 67", "telefon sıfır beş yüz otuz iki, yüz yirmi üç, kırk beş, altmış yedi"),
])
def test_telefon(girdi, beklenen):
    kontrol(girdi, beklenen)


def test_iban():
    kontrol("TR12 0006 1005 1978 6457 8413 26",
            "te re on iki, sıfır sıfır sıfır altı, bin beş, bin dokuz yüz yetmiş sekiz, altı bin dört yüz elli yedi, "
            "sekiz bin dört yüz on üç, yirmi altı")


# =============================================================================
# 12. Semboller, emoji, emotikon, noktalama
# =============================================================================

@pytest.mark.parametrize("girdi, beklenen", [
    ("A & B", "A ve B"),
    ("@sesklon", "et sesklon"),
    ("#1", "numara bir"),
    ("#tatil #deniz", "tatil deniz"),
    ("ve/veya", "ve veya"),
    ("kadın/erkek", "kadın, erkek"),
    ("~5 kg", "yaklaşık beş kilogram"),
    ("x = 5", "x eşittir beş"),
    ("*önemli*", "önemli"),
    ("Merhaba - nasılsın", "Merhaba, nasılsın"),
    ("Disney+", "Dizni artı"),
    ("Giriş -> Çıkış", "Giriş, Çıkış"),                         # ok "eşittir"/"büyüktür" olmaz
    ("x² + y²", "x kare artı y kare"),
    ("½ bardak süt", "yarım bardak süt"),
    ("1½ kg un", "bir buçuk kilogram un"),
])
def test_semboller(girdi, beklenen):
    kontrol(girdi, beklenen)


@pytest.mark.parametrize("girdi, beklenen", [
    ("Harika 🎉🔥", "Harika"),
    ("Selam 👋🏽 Ahmet geldi", "Selam. Ahmet geldi"),           # ten rengi + cümle sınırı korunur
    ("Aile 👨\u200d👩\u200d👧 tatilde", "Aile tatilde"),          # ZWJ dizisi
    ("Bu çok iyi :) gerçekten :D", "Bu çok iyi gerçekten"),
    ("Bu çok iyi :) Yarın görüşürüz", "Bu çok iyi. Yarın görüşürüz"),
    ("Seni seviyorum <3", "Seni seviyorum"),
    ("xD çok komik ;)", "çok komik"),
    ("5 <3 değildir", "beş küçüktür üç değildir"),            # sayıdan sonra kalp değil karşılaştırma
    ("çoooook güzel", "çoooook güzel"),                         # uzatmaya dokunulmaz
    ("Ne!?!", "Ne?"),
    ("Hadi!!!", "Hadi!"),
    ("<b>Kalın</b> yazı", "Kalın yazı"),
])
def test_emoji_emotikon_noktalama(girdi, beklenen):
    kontrol(girdi, beklenen)


# =============================================================================
# 13. Noktalı kısaltmalar
# =============================================================================

@pytest.mark.parametrize("girdi, beklenen", [
    ("elma, armut vb.", "elma, armut ve benzeri."),
    ("elma, armut vb. Sonra gittik.", "elma, armut ve benzeri. Sonra gittik."),
    ("Prof. Dr. Ahmet Yılmaz", "profesör doktor Ahmet Yılmaz"),
    ("Doç. Dr. Ayşe", "doçent doktor Ayşe"),
    ("Av. Mehmet Kaya", "avukat Mehmet Kaya"),
    ("Atatürk Cad. No: 5 D. 3", "Atatürk caddesi numara beş daire üç"),
    ("ABC San. ve Tic. Ltd. Şti. Genel Müdürü", "a be ce sanayi ve ticaret limited şirketi Genel Müdürü"),
    ("XYZ A.Ş.", "iks ye ze anonim şirketi."),
    ("T.C. Kimlik", "te ce Kimlik"),
    ("19. yy. sonları", "on dokuzuncu yüzyıl sonları"),
    ("bkz. s. 45", "bakınız sayfa kırk beş"),
    ("Arş. Gör. Ali", "araştırma görevlisi Ali"),
    ("Dr. Öğr. Üyesi Ayşe", "doktor öğretim üyesi Ayşe"),
    ("Gn. Md. Yrd. Ali", "genel müdür yardımcısı Ali"),
    ("Gazi Cd. 5. Sk. Merkez Mh.", "Gazi caddesi beşinci sokak Merkez mahallesi"),
    ("yak. 5 km", "yaklaşık beş kilometre"),
    ("max. 10 kişi", "maksimum on kişi"),
    ("Hz. Muhammed", "hazreti Muhammed"),
    ("TCK md. 5", "te ce ka madde beş"),
    ("Ltd.Şti.", "limited şirketi"),
    ("Dr.Ayşe geldi.", "doktor Ayşe geldi."),
])
def test_noktali_kisaltmalar(girdi, beklenen):
    kontrol(girdi, beklenen)


@pytest.mark.parametrize("girdi", [
    "Bu bir av.",          # av: avlanma (unvan değil)
    "Onu bul.",            # bul: fiil (bulvar değil)
    "Elini sok.",          # sok: fiil (sokak değil)
])
def test_kisaltma_sanilmayan_sozcukler(girdi):
    kontrol(girdi, girdi)


# =============================================================================
# 14. Okunuş sözlüğü
# =============================================================================

@pytest.mark.parametrize("girdi, beklenen", [
    ("ElevenLabs yerine", "İlevın Labs yerine"),
    ("YouTube kanalı", "Yutub kanalı"),
    ("YouTube'da", "Yutubda"),
    ("Twitter'da", "Tivitırda"),
    ("Netflix'te", "Netflikste"),
    ("Disney'e", "Dizniye"),                  # ek okunuşa uyar: Dizni + y + e
    ("H&M", "Haşem"),
    ("McDonald's'ta", "Mekdonaldsta"),
    ("Coca-Cola", "Koka Kola"),
    ("LC Waikiki", "Le Ce Vaykiki"),
    ("Apple Music", "Epıl Müzik"),
    ("iPhone'u", "Ayfonu"),
    ("Zoom toplantısı", "Zum toplantısı"),
    ("check-in yaptık", "çekin yaptık"),
    ("full HD ekran", "ful eyç di ekran"),
    ("USB-C kablo", "yu es bi si kablo"),
    ("OK, anladım.", "okey, anladım."),
    ("like ve follow", "layk ve folov"),
    ("Apple'ın CEO'su", "Epılın si i osu"),
])
def test_okunus_sozlugu(girdi, beklenen):
    kontrol(girdi, beklenen)


@pytest.mark.parametrize("girdi", [
    "ok ve yay",            # küçük "ok" Türkçe sözcüktür
    "meme kanseri",         # "meme" sözlükte yok
    "Amazon ormanları",     # Amazon yazıldığı gibi okunur
    "link trend viral",     # yazılışı değişmeyenler sözlükte yok
])
def test_okunus_sozlugu_dokunmaz(girdi):
    kontrol(girdi, girdi)


def test_okunus_sozlugu_json_ile_genisler():
    yol = config.DATA_DIR / "pronunciations.json"
    try:
        yol.write_text(json.dumps({"SesKlon": "Ses Klon", "Fumor": "Fümor"}), encoding="utf-8")
        assert tr("SesKlon ile Fumor'da") == "Ses Klon ile Fümorda"
    finally:
        yol.unlink(missing_ok=True)
    assert tr("SesKlon") == "SesKlon"             # dosya silinince önbellek yenilenir


# =============================================================================
# 15. Şapkalı harfler korunur
# =============================================================================

@pytest.mark.parametrize("girdi", ["kâr marjı", "hâlâ bekliyor", "Kâzım ve İsmâil"])
def test_sapkali_harfler(girdi):
    kontrol(girdi, girdi)


# =============================================================================
# 16. URL / e-posta
# =============================================================================

@pytest.mark.parametrize("girdi, beklenen", [
    ("www.sesklon.com", "sesklon nokta com"),
    ("https://sesklon.com/tr", "sesklon nokta com bölü tr"),
    ("sesklon.com/tr", "sesklon nokta com bölü tr"),
    ("info@firma.com.tr", "info et firma nokta com nokta te re"),
    ("ali.veli_01@gmail.com", "ali nokta veli alt çizgi sıfır bir et Cimeyl nokta com"),
    ("claude.ai", "Klod nokta ey ay"),
    ("trendyol.com'dan", "trendyol nokta comdan"),
    ("https://www.sesklon.com/urun/123?ref=x", "sesklon nokta com bölü urun bölü yüz yirmi üç"),
    ("Geldim.De ki", "Geldim. De ki"),           # yazım hatası URL sayılmaz
])
def test_url_eposta(girdi, beklenen):
    kontrol(girdi, beklenen)


# =============================================================================
# 17. Sıra / çakışma doğrulamaları
# =============================================================================

@pytest.mark.parametrize("girdi, beklenen", [
    ("1.5 kg", "bir buçuk kilogram"),                  # tarih değil (tek haneli ay)
    ("12.50 kg", "on iki nokta elli kilogram"),        # saat değil (ardından birim)
    ("10.05", "on mayıs"),                             # bağlamsız: önce tarih
    ("saat 10.05", "saat on sıfır beş"),               # "saat" bağlamı: saat
    ("3.14", "üç nokta on dört"),                      # tek haneli "saat" + ek yok: ondalık
    ("v2.0 çıktı", "versiyon iki nokta sıfır çıktı"),
    ("Sürüm 1.10 yayında", "Sürüm bir nokta on yayında"),
    ("1.250 TL", "bin iki yüz elli lira"),             # binlik, tarih değil
])
def test_asama_sirasi(girdi, beklenen):
    kontrol(girdi, beklenen)


def test_cikti_rakamsiz():
    metin = ("iPhone15, 3D, H2O, 4.5G, 2x, %5, 12:30, 1/3, 0532 123 45 67, 1.250,75 TL, XX. yüzyıl, "
             "No: 7, 5 km'lik, ₺99, 2026'da, A4, MP3, 10K, #3")
    assert not re.search(r"\d", tr(metin))


# =============================================================================
# 18. Ek uyumu (attach_suffix)
# =============================================================================

@pytest.mark.parametrize("okunus, ek, beklenen", [
    ("iki bin yirmi dört", "te", "iki bin yirmi dörtte"),
    ("iki bin yirmi dört", "de", "iki bin yirmi dörtte"),      # yanlış yazılmış ek düzeltilir
    ("yirmi dört", "ü", "yirmi dördü"),                         # dört → dördü (yumuşama)
    ("lira", "ye", "liraya"),
    ("kuruş", "ye", "kuruşa"),                                  # kaynaştırma y düşer
    ("kuruş", "nin", "kuruşun"),
    ("kuruş", "si", "kuruşu"),
    ("kuruş", "siz", "kuruşsuz"),                               # -siz iyelik değildir
    ("yapay zeka", "ın", "yapay zekanın"),                      # ünlüden sonra ilgi eki -nın
    ("iki", "e", "ikiye"),
    ("iki bin yirmi dört", "teki", "iki bin yirmi dörtteki"),   # -ki uyuma girmez
    ("saat", "a", "saate"),                                     # kural dışı ince uyum
    ("doksan", "s", "doksanlar"),                               # 1990's → doksanlar
])
def test_attach_suffix(okunus, ek, beklenen):
    assert attach_suffix(okunus, ek) == beklenen


# =============================================================================
# 19. Bütünleşik metinler
# =============================================================================

def test_urun_aciklamasi():
    metin = ("Koltuk Takımı (3+3+1) — Ölçüler: 220x95x85 cm. Fiyat: ₺24.999,00 yerine ₺19.999! "
             "%20 indirim, 12 aya varan taksit. Kargo 3-5 iş günü.")
    assert tr(metin) == (
        "Koltuk Takımı, üç artı üç artı bir, Ölçüler: iki yüz yirmi çarpı doksan beş çarpı seksen beş santimetre. "
        "Fiyat: yirmi dört bin dokuz yüz doksan dokuz lira yerine on dokuz bin dokuz yüz doksan dokuz lira! "
        "yüzde yirmi indirim, on iki aya varan taksit. Kargo üç beş iş günü."
    )


def test_haber_metni():
    metin = "TBMM'de bugün KDV'nin %18'den %20'ye çıkarılması görüşüldü. Oturum 14.30'da başladı."
    assert tr(metin) == ("te be me mede bugün ka de venin yüzde on sekizden yüzde yirmiye çıkarılması görüşüldü. "
                         "Oturum on dört otuzda başladı.")


def test_tarif_metni():
    metin = "1/2 su bardağı şeker, 3/4 çay kaşığı tuz, 250 g tereyağı. Fırını 180°'ye ısıtın, 25-30 dk pişirin."
    assert tr(metin) == ("yarım su bardağı şeker, dörtte üç çay kaşığı tuz, iki yüz elli gram tereyağı. "
                         "Fırını yüz seksen dereceye ısıtın, yirmi beş otuz dakika pişirin.")


def test_normalize_tr_dogrudan_cagrilabilir():
    assert normalize_tr("Fiyat 150 TL, %20 indirim.") == "Fiyat yüz elli lira, yüzde yirmi indirim."


def test_diger_diller_num2words():
    assert normalize("I have 3 cats", "en") == "I have three cats"
    assert normalize("Ich habe 3 Katzen.", "de") == "Ich habe drei Katzen."


@pytest.mark.parametrize("girdi", ["", "   ", "\n\n"])
def test_bos_metin(girdi):
    assert normalize(girdi, "tr") == ""


# =============================================================================
# 20. Performans: 5000 karakter < 50 ms
# =============================================================================

def test_performans_5000_karakter():
    parca = ("Fiyatı 1.250,75 TL, %20 indirimle 999,90 ₺. Randevu 12.10.2026 saat 14:30'da; ABD'de KDV yok. "
             "Tel: 0532 123 45 67, info@firma.com.tr. YouTube'da 10K takipçi! 3-4 kişilik 120x60 cm masa. ")
    metin = (parca * (5000 // len(parca) + 1))[:5000]
    tr(metin)                                            # ısınma (regex derleme, önbellek)
    sureler = []
    for _ in range(5):
        t0 = time.perf_counter()
        tr(metin)
        sureler.append(time.perf_counter() - t0)
    assert min(sureler) < 0.050, f"en iyi süre {min(sureler) * 1000:.1f} ms"


# =============================================================================
# 21. Sağlamlık: rastgele parçalardan kurulan metinlerde hata, rakam ve çift boşluk olmamalı
# =============================================================================

_PARCALAR = [
    "0", "5", "12", "2024", "0532", "1.250", "2,5", "3.14", ".", ",", ":", "/", "-", "–", "+", "x", "*", "=", "<", ">",
    "%", "‰", "°", "₺", "$", "€", "TL", "'", "'te", "'ye", "(", ")", "[", "]", "#", "@", "&", "~", "±", "ABD", "Dr.",
    "vb.", "s.", "D.", "No:", "saat", "km", "kg", "m", "g", "W", "K", "M", "II", "XX.", "www.", ".com", ".tr", "🎉",
    ":)", "<3", "xD", "\n", "İ", "ı", "I", "Instagram", "OK", "4K", "5G", "A4", "MS", "...", "!!!", "?!", "²", "½",
    chr(0x200B), chr(0x00A0), chr(0x0663), "１２", "9" * 16, "TR12", " ", " ", " ",
]


def test_rastgele_girdilerde_saglamlik():
    import random

    rnd = random.Random(2026)
    for _ in range(2000):
        girdi = "".join(rnd.choice(_PARCALAR) for _ in range(rnd.randint(1, 12)))
        sonuc = tr(girdi)
        assert isinstance(sonuc, str)
        assert not re.search(r"\d", sonuc), (girdi, sonuc)
        assert "  " not in sonuc and sonuc == sonuc.strip(), (girdi, sonuc)
