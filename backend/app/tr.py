"""Türkçe metin yardımcıları — tüm modüllerin ortak kullandığı küçük araçlar.

Python'un `str.lower()` metodu Türkçe için yanlıştır: "İ".lower() → "i̇" (i + birleşik nokta), "I".lower() → "i"
(doğrusu "ı"). Bu modül Türkçe doğru küçük/büyük harf dönüşümü, ünlü uyumu ve hece sayma sağlar.
"""
from __future__ import annotations

import re

TR_VOWELS = "aeıioöuü"
TR_BACK_VOWELS = "aıou"       # kalın
TR_FRONT_VOWELS = "eiöü"      # ince
TR_ROUND_VOWELS = "oöuü"      # yuvarlak
TR_UNROUND_VOWELS = "aeıi"    # düz
TR_HARD_CONSONANTS = "fstkçşhp"   # sert ünsüzler (ünsüz benzeşmesi için)

_LOWER_MAP = str.maketrans({"İ": "i", "I": "ı"})
_UPPER_MAP = str.maketrans({"i": "İ", "ı": "I"})


def tr_lower(s: str) -> str:
    """Türkçe'ye uygun küçük harf: İ→i, I→ı."""
    return s.translate(_LOWER_MAP).lower()


def tr_upper(s: str) -> str:
    """Türkçe'ye uygun büyük harf: i→İ, ı→I."""
    return s.translate(_UPPER_MAP).upper()


def tr_capitalize(s: str) -> str:
    if not s:
        return s
    return tr_upper(s[0]) + s[1:]


def last_vowel(word: str) -> str | None:
    """Sözcüğün son ünlüsü (küçük harf) ya da None."""
    for ch in reversed(tr_lower(word)):
        if ch in TR_VOWELS:
            return ch
    return None


def harmony_vowel_2(word: str) -> str:
    """Büyük ünlü uyumu (2'li): a / e."""
    v = last_vowel(word)
    return "e" if v in TR_FRONT_VOWELS else "a"


def harmony_vowel_4(word: str) -> str:
    """Küçük ünlü uyumu (4'lü): ı / i / u / ü."""
    v = last_vowel(word)
    if v is None:
        return "i"
    if v in "aı":
        return "ı"
    if v in "ei":
        return "i"
    if v in "ou":
        return "u"
    return "ü"


def ends_with_vowel(word: str) -> bool:
    w = tr_lower(word.rstrip("'’"))
    return bool(w) and w[-1] in TR_VOWELS


def ends_with_hard_consonant(word: str) -> bool:
    w = tr_lower(word.rstrip("'’"))
    return bool(w) and w[-1] in TR_HARD_CONSONANTS


def count_syllables(word: str) -> int:
    """Türkçede hece sayısı = ünlü sayısı (yaklaşık; yabancı sözcüklerde sapabilir)."""
    return sum(1 for ch in tr_lower(word) if ch in TR_VOWELS)


def count_syllables_text(text: str) -> int:
    return sum(count_syllables(w) for w in re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşüÂâÎîÛû]+", text))


_WORD_RE = re.compile(r"[A-Za-zÇĞİÖŞÜçğıöşüÂâÎîÛû]+(?:['’][A-Za-zÇĞİÖŞÜçğıöşü]+)?")


def words(text: str) -> list[str]:
    """Metindeki sözcükler (kesme işaretli ekler sözcüğe dahil)."""
    return _WORD_RE.findall(text)


def locative_suffix(word: str) -> str:
    """-de/-da/-te/-ta: 'saat beş' → 'beşte', 'iki' → 'ikide', 'on' → 'onda'."""
    v = harmony_vowel_2(word)
    c = "t" if ends_with_hard_consonant(word) else "d"
    return f"{c}{v}"


def dative_suffix(word: str) -> str:
    """-e/-a (ünlüyle bitiyorsa -ye/-ya): 'iki' → 'ikiye', 'on' → 'ona', 'beş' → 'beşe'."""
    v = harmony_vowel_2(word)
    return f"y{v}" if ends_with_vowel(word) else v


def ablative_suffix(word: str) -> str:
    """-den/-dan/-ten/-tan."""
    v = harmony_vowel_2(word)
    c = "t" if ends_with_hard_consonant(word) else "d"
    return f"{c}{v}n"


def genitive_suffix(word: str) -> str:
    """-in/-ın/-un/-ün (ünlüyle bitiyorsa -nin…)."""
    v = harmony_vowel_4(word)
    return f"n{v}n" if ends_with_vowel(word) else f"{v}n"


def plural_suffix(word: str) -> str:
    """-ler/-lar."""
    return f"l{harmony_vowel_2(word)}r"


def is_turkish_word_like(word: str) -> bool:
    """Kaba sezgi: sözcük Türkçe ünlü uyumuna ve ünsüz dizilimine uyuyor mu (yabancı/kısaltma tespiti için)."""
    w = tr_lower(word)
    if not w or not any(ch in TR_VOWELS for ch in w):
        return False
    # üç ardışık ünsüz Türkçede nadirdir (kısaltma / yabancı sözcük işareti)
    if re.search(r"[^aeıioöuü]{3,}", w) and not re.search(r"(nk|rt|st|lt|ns|rs|ks|lk|rk)$", w):
        return False
    return True
