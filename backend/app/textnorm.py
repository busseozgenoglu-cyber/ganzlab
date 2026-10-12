"""Metin normalizasyonu: TTS modelinin sayıları, kısaltmaları ve sembolleri
insan gibi okuması için metni "söylendiği gibi" yazıya çevirir.

Türkçe için ayrıntılı, diğer diller için num2words destekliyorsa sayı dönüşümü yapılır.
"""
from __future__ import annotations

import json
import re

try:
    from num2words import num2words
except ImportError:  # pragma: no cover
    num2words = None

# Türkçe kısaltmalar (nokta ile biten) — cümle sonu noktasıyla karışmaması için ayrıca ele alınır
TR_ABBREV = {
    "vb": "ve benzeri", "vs": "vesaire", "vd": "ve diğerleri", "bkz": "bakınız", "örn": "örneğin",
    "dr": "doktor", "prof": "profesör", "doç": "doçent", "av": "avukat", "sn": "sayın",
    "yrd": "yardımcı", "müh": "mühendis", "sok": "sokak", "cad": "cadde", "mah": "mahalle",
    "no": "numara", "apt": "apartman", "tel": "telefon", "sy": "sayfa", "şti": "şirketi",
    "ltd": "limited", "a.ş": "anonim şirketi", "t.c": "te ce", "yy": "yüzyıl", "ms": "milattan sonra",
    "mö": "milattan önce", "hz": "hazreti", "bşk": "başkan", "md": "müdür", "gn": "genel",
}
TR_UNITS = {
    "km": "kilometre", "m": "metre", "cm": "santimetre", "mm": "milimetre", "kg": "kilogram",
    "g": "gram", "gr": "gram", "mg": "miligram", "lt": "litre", "l": "litre", "ml": "mililitre",
    "km/s": "kilometre saat", "m²": "metrekare", "m2": "metrekare", "m³": "metreküp", "°c": "derece",
    "gb": "gigabayt", "mb": "megabayt", "tb": "terabayt", "kb": "kilobayt", "mhz": "megahertz",
    "ghz": "gigahertz", "sn": "saniye", "dk": "dakika", "sa": "saat", "tl": "lira",
}
TR_SYMBOLS = {"&": " ve ", "+": " artı ", "%": "yüzde ", "₺": " lira", "$": " dolar", "€": " euro", "£": " sterlin", "@": " et ", "#": " ", "*": " "}
TR_MONTHS = ["ocak", "şubat", "mart", "nisan", "mayıs", "haziran", "temmuz", "ağustos", "eylül", "ekim", "kasım", "aralık"]

# Türkçe metinde geçen yabancı marka/terimlerin Türkçe okunuşu. data/pronunciations.json ile genişletilebilir.
DEFAULT_PRONUNCIATIONS = {
    "ElevenLabs": "İlevın Labs", "YouTube": "Yutub", "Instagram": "İnstagram", "TikTok": "Tiktok",
    "Shopify": "Şopifay", "Google": "Gugıl", "Gmail": "Cimeyl", "iPhone": "Ayfon", "iPad": "Aypet",
    "WhatsApp": "Vatsap", "Chrome": "Krom", "ChatGPT": "Çet Cipiti", "OpenAI": "Open Ey Ay",
    "Claude": "Klod", "Anthropic": "Antropik", "GitHub": "Githab", "LinkedIn": "Linktin",
    "Facebook": "Feysbuk", "Netflix": "Netfliks", "Spotify": "Spotifay", "Amazon": "Emızın",
    "Microsoft": "Maykrosoft", "Windows": "Vindovs", "macOS": "Mek O Es", "Android": "Endroid",
    "Wi-Fi": "Vay Fay", "wifi": "vay fay", "Bluetooth": "Blutut", "e-mail": "i meyl", "email": "i meyl",
    "online": "onlayn", "offline": "oflayn", "download": "davnlod", "upload": "aplod", "update": "apdeyt",
    "link": "link", "like": "layk", "story": "stori", "reels": "rils", "shorts": "şorts", "podcast": "podkest",
    "influencer": "influensır", "freelance": "frilens", "start-up": "startap", "startup": "startap",
    "AI": "yapay zeka", "SaaS": "Sas", "API": "Ey Pi Ay", "CEO": "Si İ O", "PDF": "Pe De Fe",
    "Railway": "Reylvey", "Vercel": "Vörsel", "Notion": "Noşın", "Figma": "Figma", "Canva": "Kanva",
    "CapCut": "Kepkat", "Premiere": "Primiyer", "Photoshop": "Fotoşop", "Excel": "Eksel", "Word": "Vörd",
    "Tesla": "Tesla", "Zara": "Zara", "Nike": "Nayk", "Apple": "Epıl", "Samsung": "Samsung",
}


def _load_pronunciations() -> dict:
    d = dict(DEFAULT_PRONUNCIATIONS)
    try:
        from .config import DATA_DIR

        p = DATA_DIR / "pronunciations.json"
        if p.exists():
            d.update(json.loads(p.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        pass
    return d


def apply_pronunciations(text: str, lang: str) -> str:
    """Sözlükteki terimleri okunuşlarıyla değiştirir (yalnızca Türkçe için)."""
    if lang != "tr":
        return text
    table = _load_pronunciations()
    # Uzun anahtarlar önce; kelime sınırı duyarlı, büyük/küçük harf duyarsız
    for key in sorted(table, key=len, reverse=True):
        text = re.sub(rf"(?<![\w])({re.escape(key)})(?![\w])", table[key], text, flags=re.IGNORECASE)
    return text


_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF⭐✅❌️]+"
)


def _n2w(n: float | int, lang: str, to: str = "cardinal") -> str:
    if num2words is None:
        return str(n)
    try:
        return num2words(n, lang=lang, to=to)
    except Exception:  # noqa: BLE001 — dil desteklenmiyorsa rakam kalsın
        return str(n)


_ONES = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
_TENS = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]
_SCALES = [(10**12, "trilyon"), (10**9, "milyar"), (10**6, "milyon"), (1000, "bin")]


def tr_int_to_words(n: int) -> str:
    """0–999 trilyon arası tam sayıları boşluklu Türkçe yazıya çevirir (1250 → 'bin iki yüz elli')."""
    if n < 0:
        return "eksi " + tr_int_to_words(-n)
    if n == 0:
        return "sıfır"
    if n >= 10**15:
        return " ".join(_ONES[int(c)] if c != "0" else "sıfır" for c in str(n))

    def below_thousand(k: int) -> str:
        parts = []
        h, r = divmod(k, 100)
        if h:
            parts.append("yüz" if h == 1 else f"{_ONES[h]} yüz")
        t, o = divmod(r, 10)
        if t:
            parts.append(_TENS[t])
        if o:
            parts.append(_ONES[o])
        return " ".join(parts)

    parts = []
    for value, name in _SCALES:
        q, n = divmod(n, value)
        if q:
            parts.append(name if (q == 1 and value == 1000) else f"{below_thousand(q)} {name}")
    if n:
        parts.append(below_thousand(n))
    return " ".join(parts)


def tr_ordinal(n: int) -> str:
    w = tr_int_to_words(n)
    last = w.split()[-1]
    vowels = [c for c in last if c in "aeıioöuü"]
    v = vowels[-1] if vowels else "i"
    suffix = {"a": "ıncı", "ı": "ıncı", "e": "inci", "i": "inci", "o": "uncu", "u": "uncu", "ö": "üncü", "ü": "üncü"}[v]
    if last == "dört":
        last = "dörd"
    if last[-1] in "aeıioöuü":
        suffix = suffix[1:]
    return " ".join(w.split()[:-1] + [last + suffix])


def _int_tr(s: str) -> str:
    return tr_int_to_words(int(s))


def _n2w_tr(n: int, to: str = "cardinal") -> str:
    return tr_ordinal(n) if to == "ordinal" else tr_int_to_words(n)


def normalize_tr(text: str) -> str:
    t = text

    # Semboller ve para birimleri
    t = re.sub(r"%\s*(\d+(?:[.,]\d+)?)", lambda m: "yüzde " + m.group(1), t)
    t = re.sub(r"(\d+(?:[.,]\d+)?)\s*%", lambda m: "yüzde " + m.group(1), t)
    t = re.sub(r"(\d+(?:[.,]\d+)?)\s*(?:₺|\b[tT][lL]\b)", lambda m: m.group(1) + " lira", t)
    t = re.sub(r"\$\s*(\d+(?:[.,]\d+)?)", lambda m: m.group(1) + " dolar", t)
    t = re.sub(r"€\s*(\d+(?:[.,]\d+)?)", lambda m: m.group(1) + " euro", t)
    for sym, word in TR_SYMBOLS.items():
        if sym in ("%", "$", "€", "₺"):
            continue
        t = t.replace(sym, word)

    # Tarihler: 12.10.2026 / 12/10/2026
    def _date(m):
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        if 1 <= mo <= 12:
            s = f"{_n2w_tr(d)} {TR_MONTHS[mo - 1]}"
            if y:
                s += f" {_n2w_tr(int(y))}"
            return s
        return m.group(0)
    t = re.sub(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?\b(?!\d)", _date, t)

    # Saat: 14:30 / 9.45 (nokta ile saatleri yalnızca 'saat' sözcüğünden sonra)
    def _time(m):
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h < 24 and 0 <= mi < 60:
            return f"{_n2w_tr(h)} {_n2w_tr(mi) if mi else ''}".strip()
        return m.group(0)
    t = re.sub(r"\b(\d{1,2}):(\d{2})\b", _time, t)

    # Sıra sayıları: 3. sınıf, 21'inci → "üçüncü sınıf"
    t = re.sub(r"\b(\d+)\.(?=\s+[a-zçğıöşü])", lambda m: _n2w_tr(int(m.group(1)), "ordinal"), t)
    t = re.sub(r"\b(\d+)'?(?:inci|ıncı|uncu|üncü|nci|ncı|ncu|ncü)\b", lambda m: _n2w_tr(int(m.group(1)), "ordinal"), t)

    # Birimler: 5 km, 2,5 kg
    unit_pat = "|".join(sorted(map(re.escape, TR_UNITS), key=len, reverse=True))
    t = re.sub(
        rf"(\d+(?:[.,]\d+)?)\s*({unit_pat})\b",
        lambda m: f"{m.group(1)} {TR_UNITS[m.group(2).lower()]}",
        t,
        flags=re.IGNORECASE,
    )

    # Binlik ayraçlı sayılar: 1.250.000 → 1250000 ; ondalık: 2,5 → iki virgül beş
    t = re.sub(r"\b\d{1,3}(?:\.\d{3})+\b", lambda m: m.group(0).replace(".", ""), t)
    t = re.sub(r"\b(\d+),(\d+)\b", lambda m: f"{_int_tr(m.group(1))} virgül {_int_tr(m.group(2))}", t)
    t = re.sub(r"\b(\d+)\.(\d+)\b", lambda m: f"{_int_tr(m.group(1))} nokta {_int_tr(m.group(2))}", t)

    # Telefon benzeri uzun rakam dizileri: haneleri tek tek oku
    t = re.sub(r"\b0?\d{10,}\b", lambda m: " ".join(_int_tr(c) for c in m.group(0)), t)

    # Kalan tam sayılar
    t = re.sub(r"\b\d+\b", lambda m: _int_tr(m.group(0)), t)

    # Kısaltmalar (Dr., vb., A.Ş.)
    def _abbr(m):
        key = m.group(1).lower()
        return TR_ABBREV.get(key, m.group(0))
    abbr_pat = "|".join(sorted(map(re.escape, TR_ABBREV), key=len, reverse=True))
    t = re.sub(rf"\b({abbr_pat})\.", _abbr, t, flags=re.IGNORECASE)

    # "lira'lik", "otuz'da" gibi dönüşümden kalan kesme işaretlerini kaldır
    tail_words = set(_ONES[1:] + _TENS[1:] + ["yüz", "bin", "milyon", "milyar", "sıfır"] + list(TR_UNITS.values()) + ["dolar", "euro", "sterlin"])
    t = re.sub(r"\b([a-zçğıöşü]+)'([a-zçğıöşü]+)\b",
               lambda m: m.group(1) + m.group(2) if m.group(1).lower() in tail_words else m.group(0), t)

    # URL / e-posta: nokta → "nokta"
    t = re.sub(r"https?://(?:www\.)?", "", t)
    t = re.sub(r"\b([a-z0-9-]+)\.(com|net|org|co|io|tr|dev|app|digital|ai|me|info|biz|xyz|tech|store|shop|online|site|beauty|fit)\b(?:\.tr)?",
               lambda m: m.group(0).replace(".", " nokta "), t, flags=re.IGNORECASE)
    t = t.replace("@", " et ")

    return t


def normalize_generic(text: str, lang: str) -> str:
    t = text
    t = re.sub(r"%\s*(\d+)", lambda m: m.group(1) + " percent" if lang == "en" else m.group(0), t)
    t = re.sub(r"\b(\d+)[.,](\d+)\b",
               lambda m: f"{_n2w(int(m.group(1)), lang)} point {_n2w(int(m.group(2)), lang)}" if lang == "en" else m.group(0), t)
    t = re.sub(r"\b\d+\b", lambda m: _n2w(int(m.group(0)), lang), t)
    return t


def normalize(text: str, lang: str = "tr") -> str:
    """Dile göre normalize eder, fazla noktalama ve emojileri temizler."""
    t = _EMOJI.sub(" ", text)
    t = t.replace("…", "...")
    t = re.sub(r"[“”„]", '"', t)
    t = re.sub(r"[‘’]", "'", t)
    t = re.sub(r"[–—]", ", ", t)          # tire → kısa duraklama
    t = re.sub(r"\s*\(\s*", ", ", t)                 # parantez → duraklama
    t = re.sub(r"\s*\)\s*", ", ", t)
    t = re.sub(r"\s*\[[^\]]*\]\s*", " ", t)          # köşeli parantez içini at
    t = re.sub(r"\s*\{[^}]*\}\s*", " ", t)

    t = apply_pronunciations(t, lang)
    if lang == "tr":
        t = normalize_tr(t)
    else:
        t = normalize_generic(t, lang)

    t = re.sub(r"!{2,}", "!", t)
    t = re.sub(r"\?{2,}", "?", t)
    t = re.sub(r"\?!|!\?", "?", t)
    t = re.sub(r"\.{4,}", "...", t)
    t = re.sub(r"\s*,\s*,+", ",", t)                 # ardışık virgül
    t = re.sub(r"([.!?])\s*,", r"\1", t)             # "?," → "?"
    t = re.sub(r",\s*([.!?])", r"\1", t)             # ",." → "."
    t = re.sub(r"\s+([,.!?;:])", r"\1", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()
