"""Türkçe konuşma dili katmanı: yazı dilini İstanbul Türkçesinin günlük konuşmasına çevirir.

TTS modeli yazılanı harfiyen okur: "geleceğim" yazılırsa "ge-le-ce-ğim" der; oysa konuşmada herkes
"gelicem" der. Bu modül metni konuşulduğu gibi yeniden yazar — anlamı bozmadan, özel adlara ve yabancı
sözcüklere dokunmadan. Yalnızca Türkçe metin içindir.

Seviyeler (``LEVELS``):

* ``"off"``   — metne dokunulmaz.
* ``"light"`` — güvenli, varsayılan. Gelecek zaman kısaltması (geleceğim → gelicem, yapmayacağım → yapmıycam),
  bişey / hiçbişey / herşey, kalıp "bi"ler (bi dakka, bi tane, bikaç…), "ne" kaynaşmaları (naber, noldu,
  napıcaksın), "değil mi → di mi", istek kipi (yapayım → yapıyım), "X ile → Xle / X'le", heralde, abi.
* ``"full"``  — samimi / sokak ağzı: light + "-yor" r düşmesi (geliyorum → geliyom), böle / şöle / öle,
  değil → diil, "bir + isim → bi + isim".

Koruma ilkeleri (bütün seviyelerde):

* Cümle ortasında büyük harfle başlayan sözcük özel ad sayılır, ona dokunulmaz ("Ahmet Gelecek").
  Cümle başı: metin başı, önceki ayraçta ``. ! ? … :`` ya da satır sonu bulunması veya sözcüğün hemen önünde
  açılış tırnağı olması. Cümle başındaki büyük harfli sözcük çevrilebilir ("Yapacağım." → "Yapıcam.").
* Kesme işaretli ("Gelecek'i"), tamamı büyük harfli (kısaltma / bağırma) ve içinde büyük harf geçen
  (iPhone, ElevenLabs) sözcüklere dokunulmaz.
* Noktalama ve boşluklar olduğu gibi korunur. Tırnak içi de işlenir (o da konuşulan metindir).
* Büyük/küçük harf ``tr.tr_lower`` / ``tr.tr_capitalize`` ile yapılır; ``re.IGNORECASE`` kullanılmaz
  (Türkçe "İ" / "ı" harflerini tanımaz).
* Dönüşüm idempotenttir: çıktıya yeniden uygulamak sonucu değiştirmez.

Kural sırası: önce tek sözcük kuralları (gelecek zaman, istek kipi, sözlük), sonra çok sözcüklü kalıplar
(bişey, bi …, ne + fiil, di mi, ile). Böylece "ne yapacaksın" önce "ne yapıcaksın", sonra "napıcaksın" olur.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .tr import (
    TR_VOWELS,
    count_syllables,
    ends_with_vowel,
    harmony_vowel_2,
    harmony_vowel_4,
    tr_capitalize,
    tr_lower,
)

__all__ = [
    "LEVELS",
    "RULE_LABELS",
    "FUTURE_EXCEPTIONS",
    "normalize_level",
    "colloquial_tr",
    "colloquial_report",
]

LEVELS = ("off", "light", "full")

# Arayüzdeki "ne değişti" listesi için kural kimlikleri ve Türkçe açıklamaları.
RULE_LABELS: dict[str, str] = {
    "gelecek-zaman": "Gelecek zaman kısaltması (geleceğim → gelicem)",
    "istek-kipi": "İstek kipi (yapayım → yapıyım)",
    "bişey": "bir şey → bişey",
    "herşey": "her şey → herşey",
    "bi": "bir → bi (bi dakka, bi tane…)",
    "ne-kaynaşma": "ne + fiil kaynaşması (ne oldu → noldu)",
    "di-mi": "değil mi → di mi",
    "ile": "ile → -(y)la / -(y)le",
    "heralde": "herhalde → heralde",
    "abi": "ağabey → abi",
    "yor": "-yor ekinde r düşmesi (geliyorum → geliyom)",
    "böle": "böyle / şöyle / öyle → böle / şöle / öle",
    "diil": "değil → diil",
}

# ---------------------------------------------------------------------------------------------- seviye

_LEVEL_ALIASES = {
    "off": "off", "kapalı": "off", "kapali": "off", "yok": "off", "hayır": "off", "false": "off", "0": "off",
    "": "off",
    "light": "light", "hafif": "light", "açık": "light", "acik": "light", "evet": "light", "true": "light",
    "1": "light", "on": "light",
    "full": "full", "tam": "full", "samimi": "full", "sokak": "full",
}
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def normalize_level(level: str | bool | None) -> str:
    """Seviye değerini ``LEVELS`` öğelerinden birine çevirir.

    ``True`` → "light", ``False`` / ``None`` → "off". Dizgeler büyük/küçük harf duyarsızdır; Türkçe takma adlar
    da kabul edilir ("hafif", "tam", "kapalı"). Geçersiz değerde ``ValueError`` fırlatır.
    """
    if level is None or level is False:
        return "off"
    if level is True:
        return "light"
    if isinstance(level, str):
        s = level.strip()
        # "LIGHT" için tr_lower "lıght" verir; ASCII küçültme de denenir ("HAFİF" ise tr_lower ile bulunur).
        for key in (tr_lower(s), s.translate(_ASCII_LOWER)):
            if key in _LEVEL_ALIASES:
                return _LEVEL_ALIASES[key]
    raise ValueError(f"Geçersiz konuşma dili seviyesi: {level!r} (geçerli değerler: {', '.join(LEVELS)})")


# ------------------------------------------------------------------------------------------- sözlükler

_VOWELS = frozenset(TR_VOWELS)

# Sayı sözcükleri: "bir" bunlara komşuysa sayıdır ("bir milyon", "yüz bir", "bir iki üç") → "bi" yapılmaz.
_NUMBER_WORDS = frozenset({
    "sıfır", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz", "on", "yirmi", "otuz", "kırk",
    "elli", "altmış", "yetmiş", "seksen", "doksan", "yüz", "bin", "milyon", "milyar", "trilyon", "katrilyon",
    "buçuk", "çeyrek", "virgül", "nokta",
})
_MATH_WORDS = frozenset({"artı", "eksi", "çarpı", "bölü", "eşittir"})
_NUMERIC = _NUMBER_WORDS | _MATH_WORDS
# Ek almış hali de yalnız sayı olabilen sözcükler ("bir buçukta", "bir milyonluk"); kısa olanlar ("on", "bin",
# "yüz") ek alınca başka sözcüklere karışır ("ona", "bina", "yüzme"), onlar yalnız yalın halde sayılır.
_NUMERIC_PREFIXES = ("buçuk", "çeyrek", "milyon", "milyar", "trilyon", "katrilyon", "virgül")


def _is_numeric(low: str) -> bool:
    return low in _NUMERIC or low.startswith(_NUMERIC_PREFIXES)


# Gelecek zaman kuralına girmeyen sözcükler. -(y)acak/-(y)ecek ile kalıplaşmış isimler ve onların ad
# çekimleri (gelecek = "istikbal") burada; "geleceğim" ise (1. tekil fiil) ayrıca bağlamla denetlenir.
# Sonu -cak/-cek olup gelecek zaman deseni taşımayan sözcükler (sıcak, ocak, çiçek…) desene zaten uymaz;
# niyeti belgelemek ve desen ileride genişlerse korumak için yine de listede.
FUTURE_EXCEPTIONS = frozenset({
    "gelecek", "gelecekte", "gelecekteki", "gelecekten", "gelecekle", "geleceğe", "geleceği", "geleceğin",
    "geleceğini", "geleceğine", "geleceğinde", "geleceğinden", "geleceğimiz", "geleceğimizi", "geleceğimize",
    "geleceğimizin", "geleceğimizde", "geleceğiniz", "geleceğinizi", "geleceğimi", "geleceğime",
    "yiyecek", "yiyecekler", "içecek", "içecekler", "giyecek", "giyecekler", "yakacak", "yakacaklar",
    "silecek", "silecekler", "alacaklar", "alacaklı", "alacaklılar",
    # -cağız/-ceğiz küçültme eki (1. çoğul gelecek zamanla aynı yazılır)
    "kocacağız", "babacağız", "anacağız", "halacağız", "anneceğiz", "teyzeceğiz", "dedeceğiz", "nineceğiz",
    "sıcak", "ocak", "bucak", "kaçak", "ancak", "sancak", "kucak", "bacak", "uçak", "bıçak", "çiçek", "böcek",
    "gerçek", "gerçekten", "bebek", "köpek", "kelebek", "mercek", "direk", "tümsek", "kösele", "erek", "ekmek",
    "kepçe", "dilekçe",
})
# İsim de olabilen yalın biçimler: hemen ardından soru eki gelirse kesin fiildir ("Gelecek misin?" → "Gelicek misin?").
_NOUN_FUTURE_LEMMAS = frozenset({"gelecek", "yiyecek", "içecek", "giyecek", "yakacak", "silecek"})
_QUESTION_RE = re.compile(r"m[ıiuü](?:s[ıiuü]n(?:[ıiuü]z)?|y[ıiuü][mz]|yd[ıiuü][mnkz]?|ym[ıiuü]ş)?")
# "gelecek" bu sözcüklerden sonra ve yan cümle sonunda kesin fiildir: "Ahmet de gelecek." → "Ahmet de gelicek."
# ("Önemli olan gelecek." ise isim olabilir → dokunulmaz.)
_GELECEK_VERB_PREV = frozenset({
    "yarın", "bugün", "birazdan", "sonra", "hemen", "şimdi", "de", "da", "geri", "yine", "tekrar", "mutlaka",
    "kesin", "kesinlikle", "elbet", "elbette", "belki", "herhalde", "heralde", "akşam", "sabah", "bana", "sana",
    "ona", "bize", "size", "onlara", "buraya", "oraya", "şuraya", "yanıma", "yanına", "eve",
})

# -(y)acak/-(y)ecek + kişi eki. Yalnız fiil çekimi olan sonlar kabul edilir: yalın (3. tekil), -sın, -sınız,
# -lar, birleşik zamanlar (-tı/-tım…, -sa/-sam…, -mış…, -ken, -tır). Sıfat-fiil + iyelik (-acağı, -acağını,
# -acakları…) kapsam dışıdır; "-acağım" (1. tekil) ile "-acağız" (1. çoğul) "ğ" kolu ile yakalanır.
_K_TAIL = (
    r"(?:s[ıi]n(?:[ıi]z)?"
    r"|l[ae]r(?:d[ıi]r?|s[ae]|m[ıi]ş)?"
    r"|t[ıi](?:m|n|k|n[ıi]z|r)?"
    r"|s[ae](?:m|n|k|n[ıi]z)?"
    r"|m[ıi]ş(?:[ıi]m|s[ıi]n(?:[ıi]z)?|[ıi]z)?"
    r"|ken)?"
)
_FUTURE_RE = re.compile(rf"(?P<pre>.+?)(?P<v>[ae])c(?P=v)(?:k(?P<tail>{_K_TAIL})|ğ(?P<p>[ıi][mz]))")
# Sonu "y" olan ünsüz gövdeler (y kaynaştırma sanılmasın): sayacak → sayıcak, uyacak → uyucak.
_Y_CONSONANT_STEMS = frozenset({"say", "kay", "yay", "uy"})
_RAISE = {"a": "ı", "e": "i"}  # y'den önce daralma: başlayacak → başlıycak, söyleyecek → söyliycek

# "-acağım" hem "yapacağım" (fiil) hem "yapacağım iş" (sıfat-fiil) olabilir. Yalnız fiil olduğu kesin
# bağlamda kısaltılır: ardından noktalama / metin sonu ya da aşağıdaki sözcüklerden biri gelirse.
_CLAUSE_PUNCT = frozenset(".,!?;:…)]}\"“”«»'‘’—–-\n")
_FINITE_NEXT = frozenset({
    "ve", "ama", "fakat", "lakin", "ancak", "ki", "de", "da", "diye", "yani", "çünkü", "zaten", "artık", "belki",
    "işte", "inşallah", "herhalde", "heralde", "galiba", "sanırım", "bence", "ya", "yoksa", "hem", "veya",
    "sonra", "hemen", "şimdi", "yarın", "bugün", "birazdan", "tabii", "tabi", "kesin", "kesinlikle", "mutlaka",
    "elbette", "valla", "vallahi", "ben", "sana", "size", "ona", "onlara", "seni", "sizi", "onu", "onları",
    "bunu", "şunu", "bunları", "seninle", "sizinle", "onunla", "onlarla", "abi", "abla", "canım", "hocam",
    "efendim", "dedim", "dedi",
})
_COORD = frozenset({"ve", "veya", "ama", "fakat", "ya"})
_POSSESSOR_BEFORE = frozenset({"benim", "kendi"})  # "benim geleceğim parlak" → isim, dokunma

# İstek kipi 1. tekil (-ayım/-eyim → -ıyım/-iyim…): yalnız ünsüzle biten FİİL gövdelerinde. Genel desen
# "hastayım", "evdeyim", "buradayım" gibi isim + ek-fiil biçimlerini bozacağından gövde listeyle sınırlıdır.
_OPT_VERB_STEMS = frozenset({
    "yap", "ed", "gid", "gel", "bak", "al", "ver", "gör", "bul", "ol", "kal", "sor", "çık", "gir", "dur", "otur",
    "yaz", "iç", "düşün", "anlat", "sat", "at", "tut", "aç", "kapat", "çalış", "dön", "göster", "getir", "götür",
    "gönder", "çal", "sil", "kes", "seç", "bas", "yat", "kalk", "in", "bin", "kur", "sür", "koy", "giy", "duy",
    "say", "sev", "öp", "yık", "kır", "bırak", "çek", "dök", "koş", "uç", "düş", "ek", "sık", "tak", "sok", "sal",
    "sus", "kaç", "gez", "gül", "konuş", "çağır", "bağır", "ısıt", "soğut", "uzat", "yedir", "içir", "bitir",
    "kaldır", "indir", "değiştir", "düzelt", "ört", "sök", "çiz", "çöz", "kurtar", "pişir", "süpür", "öğren",
    "öğret", "ilet", "bildir", "halled", "affed", "kaybed", "hissed", "seyred", "redded", "terked", "emred",
    "tanış", "buluş", "görüş", "barış", "yetiş", "uğraş", "yaklaş", "anlaş", "uzan", "dayan", "yıkan", "giyin",
    "soyun", "uyan", "taşın", "kaçın", "sevin",
})
_OPT_DERIVED_RE = re.compile(r"(?:[dt][ıiuü]r|l[ae][nş])$")  # ettirgen (yaptır), dönüşlü (hazırlan), işteş (yerleş)
_OPT_RE = re.compile(r"(?P<stem>.+?)(?:ayım|eyim)")
_OPT_LEXICAL = {"söyleyeyim": "söyliyim", "deneyeyim": "deniyim"}  # ünlüyle biten gövdede bilinen iki biçim

# Tek sözcüklük sözlük kuralları: yazılış → (konuşma biçimi, kural).
_ABI = {
    "ağabey": "abi", "ağabeyim": "abim", "ağabeyimi": "abimi", "ağabeyime": "abime", "ağabeyimin": "abimin",
    "ağabeyimle": "abimle", "ağabeyimden": "abimden", "ağabeyler": "abiler", "ağabeyimiz": "abimiz",
    "ağabeyiniz": "abiniz", "ağabeyciğim": "abiciğim", "ağabeye": "abiye", "ağabeyle": "abiyle",
    "ağabeyden": "abiden",
}
_LEXICAL: dict[str, tuple[str, str]] = {
    "herhalde": ("heralde", "heralde"),
    "birtakım": ("bitakım", "bi"),
    **{k: (v, "abi") for k, v in _ABI.items()},
}
_BIRKAC_RE = re.compile(r"birkaç(?P<s>ı|ını|ına|ında|ından|ımız|ımızı|ınız|ınızı|ıyla)?")

# "şey" ve çekimleri ("şeyh", "şeytan", "Şeyda" değil).
_SEY_RE = re.compile(r"şey(?:ler)?(?:imiz|iniz|im|in|i)?(?:[ny]?(?:i|e|in|de|den|le|ce|di|dir|miş|se|ken))?")

# light'taki "bir → bi" kalıpları: ikinci sözcük → (varsa) onun konuşma biçimi.
_BI_LIGHT: dict[str, str | None] = {
    "dakika": "dakka", "dakikalığına": "dakkalığına", "saniye": None, "tane": None, "de": None, "daha": None,
    "kere": None, "an": None, "türlü": None, "bakalım": None, "ara": None, "sürü": None, "yere": None,
    "yerde": None, "şekilde": None, "gün": None, "zamanlar": None,
    # yumuşatıcı "bi" + emir / istek: bi bak, bi bakıyım, bi düşün…
    "bak": None, "bakın": None, "baksana": None, "bakar": None, "bakıyım": None,
    "dur": None, "durun": None, "dursana": None, "duruyum": None,
    "gel": None, "gelin": None, "gelsene": None, "geliyim": None,
    "düşün": None, "düşünün": None, "düşünelim": None, "düşünüyüm": None,
    "dinle": None, "dinleyin": None, "dinlesene": None,
    "sor": None, "sorun": None, "sorsana": None, "soralım": None, "soruyum": None,
}
# full'daki genel "bir + X → bi X" kuralının uygulanmadığı sonraki sözcükler.
_BI_FULL_BLOCK = _NUMERIC | frozenset({
    "ve", "veya", "ya", "ile", "ila", "ki", "mi", "mı", "mu", "mü", "da", "değil", "diil",
})

# "ne" + olmak / yapmak biçimleri (noluyor, nolucak, napıcaksın…). Beyaz liste: "ne olay", "ne yaprak" değil.
_NE_OL_RE = re.compile(r"ol(?:uyo|ur|ucak|acak|ucağ|acağ|du|muş|sun|sa)\w*")
_NE_YAP_RE = re.compile(
    r"yap(?:[ıa]cak|[ıa]cağ|[ıa]ca[mz]|ıyo|ar|t[ıi]|mış|s[ıa]|ayım|ıyım|alım|ın|mak|malı|abil|ama|mıy|may|madı|maz|mam)\w*"
)

# "X ile → X(y)la/(y)le": önceki sözcük bunlardan biriyse birleştirilmez.
_ILE_SKIP = frozenset({
    "o", "bu", "şu", "ben", "sen", "biz", "siz", "ve", "veya", "ya", "ama", "fakat", "de", "da", "ki", "mi", "mı",
    "mu", "mü", "ile", "ise", "gibi", "kadar", "için", "bile", "hem",
})
# Cümle başında büyük harfle yazılsa da özel ad olamayacak sözcükler (kesmesiz birleşir: "Bununla", "Neyle").
_ILE_SAFE_START = frozenset({
    "bunun", "onun", "şunun", "benim", "senin", "bizim", "sizin", "onların", "bunların", "şunların", "kimin",
    "neyin", "ne", "kim",
})
# Son ünlüsü kalın olduğu halde ince ek alan alıntılar ve adlar (saatle, dikkatle, Kemal'le).
_FRONT_LOANS = frozenset({
    "saat", "dikkat", "hakikat", "seyahat", "itaat", "cemaat", "ziraat", "kanaat", "kalp", "harf", "hal", "rol",
    "gol", "alkol", "kontrol", "petrol", "protokol", "hayal", "ihtimal", "istikbal", "istiklal", "misal", "kabul",
    "meal", "emsal", "idrak", "ittifak", "iştirak", "infilak", "usul", "sual", "ahval",
    "kemal", "cemal", "celal", "bilal", "hilal", "nihal",
})
_TR_LETTERS = frozenset("abcçdefgğhıijklmnoöprsştuüvyz")
# Yabancı sözcük izleri: Türkçede olmayan ünlü çiftleri, ünsüz + y / ünsüz + le sonu, 4+ ünsüz, "ck".
_FOREIGN_RE = re.compile(r"oo|ee|ou|ea|ie|ae|au|ei|eu|ui|ck|[^aeıioöuü]y$|[^aeıioöuüy]le$|[^aeıioöuü]{4,}")

# full: -yor ekinde r düşmesi. Ek almış biçimlere (-yordu, -yormuş, -yorsa, -yorken) dokunulmaz.
_YOR_RE = re.compile(r"(?P<stem>.+[ıiuü])yor(?P<tail>um|uz|sun|sunuz|lar)?")
_YOR_TAIL = {None: "", "um": "m", "uz": "z", "sun": "sun", "sunuz": "sunuz", "lar": "lar"}
_BOYLE = {"böyle": "böle", "şöyle": "şöle", "öyle": "öle"}
_DEGIL_RE = re.compile(
    r"değil(?P<tail>im|sin|iz|siniz|ler|dir|di|dim|din|dik|diniz|se|sem|sen|sek|seniz|ken|miş|mişim|mişsin"
    r"|mişiz|mişsiniz)?"
)

# ----------------------------------------------------------------------------------------- belirteçler

_WORD_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")  # harf dizisi; kesmeli ek sözcüğe dahil ("Ahmet'le")
_SPACE_RE = re.compile(r"[ \t  ]+")
_DIGIT_RE = re.compile(r"\d")
_SENT_BREAK = frozenset(".!?…:\n")
_PHRASE_BREAK = frozenset(".!?…:;\n")
_OPENING_QUOTES = frozenset("\"“«‘'„‹")
_FOLD = str.maketrans("âîû", "aiu")


@dataclass
class _Tok:
    """Bir sözcük ve ardından gelen ayraç (boşluk / noktalama)."""

    text: str                 # güncel yazım (büyük harf korunmuş)
    low: str                  # kuralların baktığı biçim: tr_lower + şapkasız
    start: int                # özgün (NFC) metindeki konum — rapor için
    end: int
    sep: str                  # bu sözcükten sonraki, bir sonraki sözcüğe kadarki metin
    cap: bool = False         # ilk harf büyük
    sent_start: bool = False  # cümle başında
    frozen: bool = False      # kesmeli / tamamı büyük / içinde büyük harf → hiç dokunma
    rules: list[str] = field(default_factory=list)


def _fold(s: str) -> str:
    return tr_lower(s).translate(_FOLD)


def _is_frozen(text: str) -> bool:
    if "'" in text or "’" in text:
        return True
    letters = [c for c in text if c.isalpha()]
    if len(letters) >= 2 and all(c.isupper() for c in letters):
        return True
    return any(c.isupper() for c in text[1:])


def _starts_sentence(prev_sep: str) -> bool:
    return any(c in _SENT_BREAK for c in prev_sep) or (prev_sep[-1:] in _OPENING_QUOTES and prev_sep != "")


def _tokenize(src: str) -> tuple[str, list[_Tok]]:
    matches = list(_WORD_RE.finditer(src))
    if not matches:
        return src, []
    toks: list[_Tok] = []
    for k, m in enumerate(matches):
        nxt = matches[k + 1].start() if k + 1 < len(matches) else len(src)
        text = m.group()
        toks.append(_Tok(text=text, low=_fold(text), start=m.start(), end=m.end(), sep=src[m.end():nxt]))
    for k, t in enumerate(toks):
        t.cap = t.text[:1].isupper()
        t.sent_start = k == 0 or _starts_sentence(toks[k - 1].sep)
        t.frozen = _is_frozen(t.text)
    return src[: matches[0].start()], toks


def _editable(t: _Tok) -> bool:
    """Kurala girebilir mi: donmuş değil ve küçük harfli ya da cümle başında."""
    return not t.frozen and (not t.cap or t.sent_start)


def _plain(t: _Tok) -> bool:
    """Kalıbın ikinci/üçüncü sözcüğü olabilir mi: donmuş değil ve küçük harfli."""
    return not t.frozen and not t.cap


def _adj(toks: list[_Tok], i: int) -> bool:
    """i. ile (i+1). sözcük arasında yalnız boşluk var mı (noktalama / satır sonu yok)."""
    return i + 1 < len(toks) and _SPACE_RE.fullmatch(toks[i].sep) is not None


def _prev_low(toks: list[_Tok], i: int) -> str | None:
    """Aynı cümle parçasındaki önceki sözcük."""
    if i == 0 or any(c in _PHRASE_BREAK for c in toks[i - 1].sep):
        return None
    return toks[i - 1].low


def _case_like(t: _Tok, new_low: str) -> str:
    return tr_capitalize(new_low) if t.cap else new_low


def _set(t: _Tok, new_low: str, rule: str) -> None:
    t.low = new_low
    t.text = _case_like(t, new_low)
    t.rules.append(rule)


def _merge(toks: list[_Tok], i: int, j: int, new_text: str, rule: str) -> None:
    """i..j sözcüklerini tek öğeye indirir (araya giren ayraçlar new_text'in içindedir)."""
    head, tail = toks[i], toks[j]
    head.rules = [r for t in toks[i : j + 1] for r in t.rules] + [rule]
    head.text = new_text
    head.low = _fold(new_text)
    head.end = tail.end
    head.sep = tail.sep
    head.frozen = head.frozen or "'" in new_text or "’" in new_text  # "Ahmet'le" artık özel ad biçimi
    del toks[i + 1 : j + 1]


def _number_context(toks: list[_Tok], i: int) -> bool:
    """i. sözcük ("bir") sayı bağlamında mı: "on bir", "bir milyon", "bir iki üç", "bir buçukta", "5 bir"."""
    if i > 0:
        sep = toks[i - 1].sep
        if _DIGIT_RE.search(sep):
            return True
        if not any(c in _PHRASE_BREAK for c in sep) and _is_numeric(toks[i - 1].low):
            return True
    if i + 1 < len(toks):
        if _DIGIT_RE.search(toks[i].sep):
            return True
        if _is_numeric(toks[i + 1].low):
            return True
    return False


# ------------------------------------------------------------------------------- tek sözcük kuralları

def _future_form(low: str) -> tuple[str, bool] | None:
    """Gelecek zaman çekimli sözcüğün konuşma biçimi ve 1. tekil olup olmadığı; değilse None.

    geleceğim → gelicem, yapacaksın → yapıcaksın, bulacağız → bulucaz, olmayacak → olmıycak,
    başlayacağım → başlıycam, okuyacak → okuycak, diyecek → dicek, yapacaktım → yapıcaktım.
    """
    m = _FUTURE_RE.fullmatch(low)
    if not m:
        return None
    pre, v, p = m.group("pre"), m.group("v"), m.group("p")
    if len(pre) < 2:  # gövde en az iki harf: "bacak" (b + acak) gibi isimler elenir
        return None
    end = p[1] if p else "k" + m.group("tail")  # -acağım → -cam, -acağız → -caz, -acak… → -cak…
    if pre[-1] == "y" and pre[-2] in _VOWELS and pre not in _Y_CONSONANT_STEMS:
        stem = pre[:-1]  # ünlüyle biten gövde + kaynaştırma y'si (olma-y-acak, başla-y-acak)
        if stem in ("di", "yi"):  # diyecek → dicek, yiyeceğim → yicem
            core = stem
        else:
            core = stem[:-1] + _RAISE.get(stem[-1], stem[-1]) + "y"
    elif pre[-1] in _VOWELS:
        return None
    else:  # ünsüzle biten gövde: ek ünlüsü daralır ve gövdeye uyar (olacak → olucak, görecek → görücek)
        core = pre + harmony_vowel_4(pre)
    return core + "c" + v + end, p is not None and p[1] == "m"


def _finite_after(toks: list[_Tok], i: int, depth: int = 0) -> bool:
    """i. sözcükten ("-acağım") sonra yan cümle bitiyor mu (fiil mi, sıfat-fiil mi)."""
    if i + 1 >= len(toks) or any(c in _CLAUSE_PUNCT for c in toks[i].sep):
        return True
    nxt = toks[i + 1].low
    # "yapacağım ve yapmayacağım şeyler": bağlacın ardındaki "-acağım"ın bağlamı belirler
    if nxt in _COORD and depth < 4 and i + 2 < len(toks) and not any(c in _CLAUSE_PUNCT for c in toks[i + 1].sep):
        r = _future_form(toks[i + 2].low)
        if r is not None and r[1]:
            return _finite_after(toks, i + 2, depth + 1)
    return nxt in _FINITE_NEXT


def _noun_used_as_verb(toks: list[_Tok], i: int) -> bool:
    """İsim de olabilen yalın biçim ("gelecek", "yiyecek"…) burada kesin fiil mi."""
    low = toks[i].low
    if low not in _NOUN_FUTURE_LEMMAS:
        return False
    if _adj(toks, i) and _QUESTION_RE.fullmatch(toks[i + 1].low):  # "Gelecek misin?"
        return True
    clause_end = i + 1 >= len(toks) or any(c in _CLAUSE_PUNCT for c in toks[i].sep)
    prev = _prev_low(toks, i)
    if low != "gelecek" or not clause_end or prev not in _GELECEK_VERB_PREV:
        return False
    # "hem geçmiş hem de gelecek", "geçmiş ya da gelecek": bağlaç "de/da" → isim
    return not (prev in ("de", "da") and _prev_low(toks, i - 1) in ("hem", "ya", "ve", "veya"))


def _rule_future(toks: list[_Tok]) -> None:
    for i, t in enumerate(toks):
        if not _editable(t):
            continue
        if t.low in FUTURE_EXCEPTIONS and not _noun_used_as_verb(toks, i):
            continue
        r = _future_form(t.low)
        if r is None:
            continue
        new, first_singular = r
        if first_singular and (_prev_low(toks, i) in _POSSESSOR_BEFORE or not _finite_after(toks, i)):
            continue
        _set(t, new, "gelecek-zaman")


def _is_consonant_verb_stem(stem: str) -> bool:
    return stem in _OPT_VERB_STEMS or (len(stem) >= 4 and _OPT_DERIVED_RE.search(stem) is not None)


def _rule_optative(toks: list[_Tok]) -> None:
    """İstek kipi 1. tekil: yapayım → yapıyım, geleyim → geliyim, bulayım → buluyum, göreyim → görüyüm."""
    for i, t in enumerate(toks):
        if not _editable(t):
            continue
        new = _OPT_LEXICAL.get(t.low)
        if new is None:
            m = _OPT_RE.fullmatch(t.low)
            if not m or not _is_consonant_verb_stem(m.group("stem")) or _prev_low(toks, i) in _POSSESSOR_BEFORE:
                continue
            stem = m.group("stem")
            h = harmony_vowel_4(stem)
            new = f"{stem}{h}y{h}m"
        _set(t, new, "istek-kipi")


def _rule_lexical(toks: list[_Tok]) -> None:
    """Sözlük: herhalde → heralde, ağabey → abi, birtakım → bitakım, birkaç → bikaç."""
    for t in toks:
        if not _editable(t):
            continue
        hit = _LEXICAL.get(t.low)
        if hit is not None:
            _set(t, hit[0], hit[1])
            continue
        m = _BIRKAC_RE.fullmatch(t.low)
        if m:
            _set(t, "bikaç" + (m.group("s") or ""), "bi")


def _rule_yor(toks: list[_Tok]) -> None:
    """full: geliyor → geliyo, geliyorum → geliyom, geliyoruz → geliyoz, geliyorsun → geliyosun…"""
    for t in toks:
        if not _editable(t):
            continue
        m = _YOR_RE.fullmatch(t.low)
        if m and len(m.group("stem")) >= 2:
            _set(t, m.group("stem") + "yo" + _YOR_TAIL[m.group("tail")], "yor")


def _rule_boyle(toks: list[_Tok]) -> None:
    """full: böyle → böle, şöyle → şöle, öyle → öle."""
    for t in toks:
        if _editable(t) and t.low in _BOYLE:
            _set(t, _BOYLE[t.low], "böle")


def _rule_diil(toks: list[_Tok]) -> None:
    """full: değil → diil, değilim → diilim… ("değil mi" daha önce "di mi" olmuştur)."""
    for t in toks:
        if not _editable(t):
            continue
        m = _DEGIL_RE.fullmatch(t.low)
        if m:
            _set(t, "diil" + (m.group("tail") or ""), "diil")


# --------------------------------------------------------------------------------- kalıp kuralları

def _is_sey(t: _Tok) -> bool:
    return _plain(t) and _SEY_RE.fullmatch(t.low) is not None


def _rule_sey(toks: list[_Tok]) -> None:
    """hiç bir şey / hiçbir şey → hiçbişey, bir şey(ler) → bişey(ler), her şey → herşey."""
    i = 0
    while i < len(toks):
        t = toks[i]
        if _editable(t) and _adj(toks, i):
            b = toks[i + 1]
            if t.low == "hiç" and _plain(b) and b.low == "bir" and _adj(toks, i + 1) and _is_sey(toks[i + 2]):
                _merge(toks, i, i + 2, _case_like(t, "hiçbi" + toks[i + 2].low), "bişey")
            elif t.low == "hiçbir" and _is_sey(b):
                _merge(toks, i, i + 1, _case_like(t, "hiçbi" + b.low), "bişey")
            elif t.low == "bir" and _is_sey(b) and not _number_context(toks, i):
                _merge(toks, i, i + 1, _case_like(t, "bi" + b.low), "bişey")
            elif t.low == "her" and _is_sey(b):
                _merge(toks, i, i + 1, _case_like(t, "her" + b.low), "herşey")
        i += 1


def _rule_bi_light(toks: list[_Tok]) -> None:
    """Kalıp listesindeki "bir"ler: bi dakka, bi tane, bi de, bi gün, bi bak…; "bir kaç" → "bikaç"."""
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.low == "bir" and _editable(t) and _adj(toks, i) and _plain(toks[i + 1]):
            b = toks[i + 1]
            if b.low == "kaç":
                _merge(toks, i, i + 1, _case_like(t, "bikaç"), "bi")
            elif b.low in _BI_LIGHT and not _number_context(toks, i):
                _merge(toks, i, i + 1, _case_like(t, "bi") + t.sep + (_BI_LIGHT[b.low] or b.text), "bi")
        i += 1


def _rule_ne(toks: list[_Tok]) -> None:
    """ne haber → naber, ne oldu → noldu, ne oluyor → noluyor, ne yapıcaksın → napıcaksın…"""
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.low == "ne" and _editable(t) and _adj(toks, i) and _plain(toks[i + 1]):
            n = toks[i + 1].low
            new = None
            if n == "haber":
                new = "naber"
            elif _NE_OL_RE.fullmatch(n):
                new = "n" + n
            elif _NE_YAP_RE.fullmatch(n):
                new = "n" + n[1:]
            if new is not None:
                _merge(toks, i, i + 1, _case_like(t, new), "ne-kaynaşma")
        i += 1


def _rule_degil_mi(toks: list[_Tok]) -> None:
    """değil mi → di mi (soru eki ayrı sözcük olarak kalır)."""
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.low == "değil" and _editable(t) and _adj(toks, i) and _plain(toks[i + 1]) and toks[i + 1].low == "mi":
            _merge(toks, i, i + 1, _case_like(t, "di") + t.sep + toks[i + 1].text, "di-mi")
        i += 1


def _looks_foreign(word: str) -> bool:
    return any(c not in _TR_LETTERS for c in word) or _FOREIGN_RE.search(word) is not None


def _ile_form(x: _Tok, apostrophe: str) -> str | None:
    """"X ile" → "X(y)la/(y)le"; özel adda kesmeyle ("Ahmet'le"). Uygun değilse None."""
    if x.frozen:
        return None
    last = x.low.rsplit(None, 1)[-1]
    # Cümle başındaki büyük harfli özgün sözcük özel ad mı cins ad mı bilinemez → dokunma
    if x.cap and x.sent_start and not x.rules and last not in _ILE_SAFE_START:
        return None
    if last in _ILE_SKIP or _is_numeric(last) or count_syllables(last) == 0 or _looks_foreign(last):
        return None
    vowel = "e" if last in _FRONT_LOANS else harmony_vowel_2(last)
    suffix = ("y" if ends_with_vowel(last) else "") + "l" + vowel
    return x.text + (apostrophe if x.cap and not x.sent_start else "") + suffix


def _rule_ile(toks: list[_Tok], apostrophe: str = "'") -> None:
    """araba ile → arabayla, kalem ile → kalemle, Ahmet ile → Ahmet'le, Ayşe ile → Ayşe'yle."""
    i = 1
    while i < len(toks):
        t = toks[i]
        if t.low == "ile" and _plain(t) and _adj(toks, i - 1):
            new = _ile_form(toks[i - 1], apostrophe)
            if new is not None:
                _merge(toks, i - 1, i, new, "ile")
                continue  # liste kısaldı; aynı konumdaki yeni sözcüğe bak
        i += 1


def _rule_bi_full(toks: list[_Tok]) -> None:
    """full: bir + sözcük → bi + sözcük (sayı bağlamı, "bir bir", "bir ve iki" hariç)."""
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.low == "bir" and _editable(t) and _adj(toks, i):
            b = toks[i + 1]
            if b.low not in _BI_FULL_BLOCK and not _number_context(toks, i):
                _merge(toks, i, i + 1, _case_like(t, "bi") + t.sep + b.text, "bi")
        i += 1


# ------------------------------------------------------------------------------------------ genel API

def _run(text: str, level: str | bool | None) -> tuple[str, list[dict]]:
    lv = normalize_level(level)
    if lv == "off" or not text:
        return text, []
    src = unicodedata.normalize("NFC", text)  # ayrık "I + ̇" gibi diziler tek harfe insin
    lead, toks = _tokenize(src)
    if not toks:
        return text, []
    # Metin tipografik kesme (’) kullanıyorsa eklenen kesme de öyle olsun.
    apostrophe = "’" if "’" in src and "'" not in src else "'"

    # 1) tek sözcük kuralları
    _rule_future(toks)
    _rule_optative(toks)
    _rule_lexical(toks)
    if lv == "full":
        _rule_yor(toks)
        _rule_boyle(toks)
    # 2) çok sözcüklü kalıplar (sıra önemli: "bir şey" → "bi …" kalıplarından, "değil mi" → "diil"den önce)
    _rule_sey(toks)
    _rule_bi_light(toks)
    _rule_ne(toks)
    _rule_degil_mi(toks)
    _rule_ile(toks, apostrophe)
    if lv == "full":
        _rule_diil(toks)
        _rule_bi_full(toks)

    report: list[dict] = []
    for t in toks:
        original = src[t.start : t.end]
        if t.rules and t.text != original:
            report.append({"from": original, "to": t.text, "rule": "+".join(dict.fromkeys(t.rules))})
    if not report:
        return text, []
    return lead + "".join(t.text + t.sep for t in toks), report


def colloquial_tr(text: str, level: str | bool = "light") -> str:
    """Yazı dilini İstanbul Türkçesi günlük konuşmasına çevirir.

    level: "off" | "light" | "full" (bkz. ``LEVELS``); ``True`` → "light", ``False`` → "off".

    >>> colloquial_tr("Yarın geleceğim, sana bir şey göstereceğim.")
    'Yarın gelicem, sana bişey göstericem.'
    >>> colloquial_tr("Ne yapıyorsun? Böyle olmaz.", "full")
    'Napıyosun? Böle olmaz.'
    """
    return _run(text, level)[0]


def colloquial_report(text: str, level: str | bool = "light") -> list[dict]:
    """Uygulanan dönüşümlerin metin sırasıyla listesi (arayüzde "ne değişti" göstermek için).

    Her öğe: ``{"from": özgün parça, "to": konuşma biçimi, "rule": kural kimliği}``. Birden çok kural aynı
    parçaya uygulandıysa kimlikler "+" ile birleşir ("gelecek-zaman+ne-kaynaşma"); açıklamalar ``RULE_LABELS``.

    >>> colloquial_report("Yarın geleceğim.")
    [{'from': 'geleceğim', 'to': 'gelicem', 'rule': 'gelecek-zaman'}]
    """
    return _run(text, level)[1]
