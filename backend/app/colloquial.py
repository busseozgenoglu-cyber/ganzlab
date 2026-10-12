"""Türkçe konuşma dili katmanı.

Yazı dilindeki biçimler, İstanbul Türkçesinde günlük konuşmada söylendiği gibi yeniden yazılır;
böylece TTS "geleceğim" yerine "gelicem", "bir şey" yerine "bişey" der. Yalnızca Türkçe için.

Kural sırası önemlidir: önce kalıp ifadeler, sonra olumsuz gelecek zaman, sonra genel gelecek zaman.
"""
from __future__ import annotations

import re

# ---- Kalıp ifadeler (kelime sınırı duyarlı, büyük/küçük harf korunur) ----
PHRASES = [
    (r"\bhiç ?bir şey\b", "hiçbişey"),
    (r"\bbir şeyler\b", "bişeyler"),
    (r"\bbir şey\b", "bişey"),
    (r"\bher şey\b", "herşey"),
    (r"\bbir ?takım\b", "bitakım"),
    (r"\bbir dakika\b", "bi dakka"),
    (r"\bbir saniye\b", "bi saniye"),
    (r"\bbir tane\b", "bi tane"),
    (r"\bbir de\b", "bi de"),
    (r"\bbir daha\b", "bi daha"),
    (r"\bbir kere\b", "bi kere"),
    (r"\bbir an\b", "bi an"),
    (r"\bbir türlü\b", "bi türlü"),
    (r"\bbir bakalım\b", "bi bakalım"),
    (r"\bbir ara\b", "bi ara"),
    (r"\bne haber\b", "naber"),
    (r"\bne oluyor\b", "noluyor"),
    (r"\bne olur\b", "nolur"),
    (r"\bne olacak\b", "nolucak"),
    (r"\bne oldu\b", "noldu"),
    (r"\bne yap", "nap"),                 # ne yapıyorsun → napıyorsun, ne yapacağız → napıcaz
    (r"\bdeğil mi\b", "di mi"),
    (r"\bşey yani\b", "şey yani"),
    (r"\bböyle\b", "böle"),
    (r"\bşöyle\b", "şöle"),
    (r"\böyle\b", "öle"),
    (r"\bnasıl yani\b", "nasıl yani"),
    (r"\bbiliyor musun\b", "biliyo musun"),
    (r"\bistiyor musun\b", "istiyo musun"),
    (r"\bgeliyor musun\b", "geliyo musun"),
    (r"\bağabey\b", "abi"),
    (r"\byapayım\b", "yapıyım"),
    (r"\bedeyim\b", "ediyim"),
    (r"\bbakayım\b", "bakıyım"),
    (r"\bgeleyim\b", "geliyim"),
    (r"\bgideyim\b", "gidiyim"),
    (r"\bsöyleyeyim\b", "söyliyim"),
    (r"\bvereyim\b", "veriyim"),
    (r"\balayım\b", "alıyım"),
    (r"\bdeneyeyim\b", "deniyim"),
    (r"\bgöstereyim\b", "göstereyim"),
]

# ---- Gelecek zaman: olumsuz (-mayacağım → -mıycam) ----
NEG_FUTURE = [
    (r"mayacağım\b", "mıycam"), (r"meyeceğim\b", "miycem"),
    (r"mayacağız\b", "mıycaz"), (r"meyeceğiz\b", "miycez"),
    (r"mayacaksın\b", "mıycaksın"), (r"meyeceksin\b", "miyceksin"),
    (r"mayacaksınız\b", "mıycaksınız"), (r"meyeceksiniz\b", "miyceksiniz"),
    (r"mayacaklar\b", "mıycaklar"), (r"meyecekler\b", "miycekler"),
    (r"mayacak\b", "mıycak"), (r"meyecek\b", "miycek"),
    (r"mayacağ", "mıycağ"), (r"meyeceğ", "miyceğ"),
    (r"mayacak", "mıycak"), (r"meyecek", "miycek"),
]

# ---- Gelecek zaman: ünlüyle biten gövde + y kaynaştırma (başlayacağım → başlaycam) ----
Y_FUTURE = [
    (r"yacağım\b", "ycam"), (r"yeceğim\b", "ycem"),
    (r"yacağız\b", "ycaz"), (r"yeceğiz\b", "ycez"),
    (r"yacaksın\b", "ycaksın"), (r"yeceksin\b", "yceksin"),
    (r"yacaksınız\b", "ycaksınız"), (r"yeceksiniz\b", "yceksiniz"),
    (r"yacaklar\b", "ycaklar"), (r"yecekler\b", "ycekler"),
    (r"yacak\b", "ycak"), (r"yecek\b", "ycek"),
    (r"yacağ", "ycağ"), (r"yeceğ", "yceğ"),
    (r"yacak", "ycak"), (r"yecek", "ycek"),
]

# ---- Gelecek zaman: ünsüzle biten gövde (geleceğim → gelicem, yapacağım → yapıcam) ----
FUTURE = [
    (r"acağım\b", "ıcam"), (r"eceğim\b", "icem"),
    (r"acağız\b", "ıcaz"), (r"eceğiz\b", "icez"),
    (r"acaksın\b", "ıcaksın"), (r"eceksin\b", "iceksin"),
    (r"acaksınız\b", "ıcaksınız"), (r"eceksiniz\b", "iceksiniz"),
    (r"acaklar\b", "ıcaklar"), (r"ecekler\b", "icekler"),
    (r"acak\b", "ıcak"), (r"ecek\b", "icek"),
    (r"acağ", "ıcağ"), (r"eceğ", "iceğ"),
    (r"acak", "ıcak"), (r"ecek", "icek"),
]

# Gelecek zaman kuralına girmemesi gereken sözcükler (isim/sıfat olarak kullanılan -ecek/-acak)
FUTURE_EXCEPTIONS = {
    "gelecek", "gelecekte", "gelecekteki", "gelecekten", "geleceğe", "geleceği", "geleceğin", "geleceğimiz",
    "gelecekler",  # "gelecek nesiller"
    "yiyecek", "yiyecekler", "içecek", "içecekler", "giyecek", "yakacak", "ocak", "bucak", "kaçak", "sıcak",
    "alacaklı", "alacaklar", "gerçek", "ekmek", "bıçak", "uçak", "ancak", "sancak", "kucak", "çiçek", "böcek", "gerçekten", "bebek", "köpek", "kelebek", "kepçe", "mercek",
}

# Kelime sonundaki -r düşmesi: "geliyor" → "geliyo" (yalnızca -yor'dan sonra ek yoksa)
YOR = [(r"([ıiuü])yor\b", r"\1yo"), (r"([ıiuü])yorum\b", r"\1yom"), (r"([ıiuü])yoruz\b", r"\1yoz"),
       (r"([ıiuü])yorsun\b", r"\1yosun"), (r"([ıiuü])yorsunuz\b", r"\1yosunuz"), (r"([ıiuü])yorlar\b", r"\1yolar")]


def _keep_case(src: str, rep: str) -> str:
    return rep[:1].upper() + rep[1:] if src[:1].isupper() else rep


def _apply_rules(text: str, rules: list[tuple[str, str]]) -> str:
    for pat, rep in rules:
        if "\\1" in rep:
            text = re.sub(pat, rep, text, flags=re.IGNORECASE)
        else:
            text = re.sub(pat, lambda m, r=rep: _keep_case(m.group(0), r), text, flags=re.IGNORECASE)
    return text


_VOWEL_MAP = {"a": "ı", "ı": "ı", "o": "u", "u": "u", "e": "i", "i": "i", "ö": "ü", "ü": "ü"}


def _harmonize(stem: str, rep: str) -> str:
    """-ıcak/-icek ekinin ünlüsünü gövdenin son ünlüsüne göre seçer (olacak → olucak, görecek → görücek)."""
    vowels = [c for c in stem.lower() if c in _VOWEL_MAP]
    if not vowels:
        return rep
    v = _VOWEL_MAP[vowels[-1]]
    if rep.startswith("ı") or rep.startswith("i"):
        return v + rep[1:]
    if rep.startswith("mı") or rep.startswith("mi"):
        return "m" + v + rep[2:]
    return rep


def _apply_future(word: str) -> str:
    low = word.lower()
    if low in FUTURE_EXCEPTIONS:
        return word
    # Kısa gövdeler (yalın isimler) için koruma: -acak/-ecek'ten önce en az 2 harf olmalı
    for rules in (NEG_FUTURE, Y_FUTURE, FUTURE):
        for pat, rep in rules:
            m = re.search(pat, low)
            if m and m.start() >= 2:
                stem = word[: m.start()]
                return stem + (_harmonize(stem, rep) if rules is FUTURE else rep)
    return word


def colloquial_tr(text: str, drop_yor_r: bool = False) -> str:
    """Yazı dilini konuşma diline çevirir. drop_yor_r=True ise 'geliyorum' → 'geliyom' (daha samimi)."""
    t = _apply_rules(text, PHRASES)
    # Gelecek zaman kelime kelime (istisna listesi için)
    t = re.sub(r"[A-Za-zÇĞİÖŞÜçğıöşü]+", lambda m: _apply_future(m.group(0)), t)
    if drop_yor_r:
        t = _apply_rules(t, YOR)
    return t
