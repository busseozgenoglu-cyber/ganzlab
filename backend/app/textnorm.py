"""Metin normalizasyonu — TTS modelinin ağzına, bir Türk spikerin söyleyeceği sözcükleri koyar.

`normalize(metin, dil)` tüm dillerin giriş noktasıdır (imza korunur). Türkçe için ayrıntılı kurallar
(`normalize_tr`), diğer diller için num2words destekliyorsa sayı dönüşümü (`normalize_generic`) uygulanır.

Türkçe işlem sırası (çakışmalar test edilerek kuruldu; gerekçeler ilgili bölümlerde):
   1. Ön temizlik       : NFC, görünmez karakterler, emoji ve emotikonlar, tipografik tırnak/kesme/eksi.
   2. Telefon/IBAN/kart : parantezler duraklamaya çevrilmeden ÖNCE okunur ("0 (532) 123 45 67").
   3. URL / e-posta     : okunuş sözlüğü alan adını değiştirmeden ve "/"-"." sembolleri okunmadan önce.
   4. Yapı              : uzun tire/parantez → duraklama; köşeli/süslü parantez içi ve HTML etiketleri atılır.
   5. Okunuş sözlüğü    : marka ve yabancı sözcükler (tek birleşik regex, tr_lower tabanlı eşleşme).
   6. Para → yüzde → tarih → saat → sıra sayıları (Roma dahil) → birimler.
   7. Noktalı kısaltmalar: birimlerden SONRA ("5 sn." saniyedir), sayılardan ÖNCE ("s. 45", "D. 5" bağlamı).
   8. Aralık/matematik → binlik/ondalık ve kalan sayılar (kesmeli/bitişik ekleriyle birlikte).
   9. Harf harf okunan kısaltmalar (ABD → "a be de", 4K → "dört ka") → harfe yapışık kalan rakamlar →
      semboller → noktalama temizliği.

Ek kuralı: "2024'te", "ABD'de", "%20'lik", "150 TL'ye" gibi kesmeyle yazılmış ekler, okunuşun son sözcüğüne
bitiştirilir ve gerekirse ünlü uyumu/ünsüz benzeşmesi/kaynaştırma harfi düzeltilir (bkz. `attach_suffix`).
Doğru yazılmış ek değişmez: "2024'te" → "iki bin yirmi dörtte"; "150 TL'ye" → "yüz elli liraya".
"""
from __future__ import annotations

import json
import re
import unicodedata

from .tr import (
    TR_HARD_CONSONANTS,
    TR_VOWELS,
    harmony_vowel_2,
    harmony_vowel_4,
    is_turkish_word_like,
    locative_suffix,
    tr_lower,
    tr_upper,
)

try:
    from num2words import num2words
except ImportError:  # pragma: no cover
    num2words = None


# =============================================================================
# 1. GENEL SABİTLER
# =============================================================================

TR_MONTHS = ["ocak", "şubat", "mart", "nisan", "mayıs", "haziran", "temmuz", "ağustos", "eylül", "ekim", "kasım",
             "aralık"]

_LETTER = r"[^\W\d_]"                       # herhangi bir (Unicode) harf
_SUF = rf"(?:'(?P<suf>{_LETTER}+))?"         # kesmeyle yazılmış ek: 2024'te, ABD'de
_NUMV = r"\d+(?:[.,]\d+)*"                   # ayraçlı/ayraçsız sayı (yorumu _split_numeric yapar)

#: Fiyat etiketi istisnası: tam kısmı 9 ile biten ve kuruşu 90/95/99 olan lira tutarları (999,90 ₺ / 49,99 TL)
#: "virgül"le okunur: "dokuz yüz doksan dokuz virgül doksan lira". Diğer tüm tutarlar kuruşla okunur.
#: Eski sözleşme testi (tests/test_text.py) bu okunuşu sabitler; False yapılırsa bunlar da kuruşla okunur.
FIYAT_ETIKETI_VIRGUL = True


def _fold(s: str) -> str:
    """Eşleştirme anahtarı: Türkçe küçük harf + ı/i ayrımı yok sayılır (Instagram = instagram = İnstagram)."""
    return tr_lower(s).replace("ı", "i")


def _with_suffix(words: str, suffix: str | None) -> str:
    """Ek varsa okunuşun son sözcüğüne bitiştirir, yoksa okunuşu aynen döndürür."""
    return attach_suffix(words, suffix) if suffix else words


# =============================================================================
# 2. SÖZLÜKLER
# =============================================================================

#: Noktalı kısaltmalar: anahtar = tr_lower(kısaltma), değer = açılım.
TR_ABBREV = {
    # genel
    "vb": "ve benzeri", "vs": "vesaire", "vd": "ve diğerleri", "bkz": "bakınız", "bknz": "bakınız",
    "örn": "örneğin", "yak": "yaklaşık", "max": "maksimum", "maks": "maksimum", "ort": "ortalama",
    "no": "numara", "sy": "sayfa", "sf": "sayfa", "s": "sayfa", "tel": "telefon", "fax": "faks", "faks": "faks",
    "yy": "yüzyıl", "ms": "milattan sonra", "m.s": "milattan sonra", "mö": "milattan önce", "m.ö": "milattan önce",
    "t.c": "te ce",
    # unvanlar
    "dr": "doktor", "prof": "profesör", "doç": "doçent", "av": "avukat", "sn": "sayın", "yrd": "yardımcı",
    "müh": "mühendis", "hz": "hazreti", "bşk": "başkan", "md": "müdür", "gn": "genel", "uzm": "uzman",
    "dt": "diş tabibi", "ecz": "eczacı", "opr": "operatör", "öğr": "öğretim", "arş": "araştırma", "çev": "çeviren",
    # askerî rütbeler
    "alb": "albay", "yzb": "yüzbaşı", "üstğm": "üsteğmen", "tğm": "teğmen", "gnl": "general", "org": "orgeneral",
    "korg": "korgeneral", "tümg": "tümgeneral", "tuğg": "tuğgeneral", "bnb": "binbaşı", "binb": "binbaşı",
    # şirket
    "şti": "şirketi", "ltd": "limited", "a.ş": "anonim şirketi", "san": "sanayi", "tic": "ticaret",
    # adres
    "mah": "mahallesi", "mh": "mahallesi", "cad": "caddesi", "cd": "caddesi", "sok": "sokak", "sk": "sokak",
    "blv": "bulvarı", "bul": "bulvarı", "apt": "apartmanı", "bl": "blok", "d": "daire", "plz": "plaza",
    "ist": "İstanbul", "ank": "Ankara", "izm": "İzmir",
    # eğitim
    "üniv": "üniversitesi", "ünv": "üniversitesi", "fak": "fakültesi",
    # günler
    "pzt": "pazartesi", "çrş": "çarşamba", "prş": "perşembe", "cmt": "cumartesi",
}

#: Yanlış pozitifleri önleyen koşullar (sözcük aynı zamanda Türkçe bir sözcük olabilir: "bul.", "av.", "sok.").
#:   cap      : yalnız baş harfi büyük olmalı ("Sok.", "Cd."); tamamı büyükse ("CD.") kısaltmadır, dokunulmaz
#:   upper    : tamamı büyük harf ("MS.", "MÖ.")
#:   digit    : ardından rakam gelmeli ("s. 45", "D. 5", "yak. 3 km")
#:   title    : baş harfi büyük ve ardından büyük harfle başlayan bir ad gelmeli ("Av. Mehmet")
#:   capdigit : cap koşulu ya da ardından rakam ("Tel. 0212…", "Bl. 3")
#:   md       : ardından rakam varsa "madde" (TCK md. 5), yoksa "müdür"
#:   yrd      : önünde bir unvan/sözcük varsa "yardımcısı" (Gn. Md. Yrd.), yoksa "yardımcı" (Yrd. Doç.)
_ABBREV_COND = {
    "s": "digit", "d": "digit", "yak": "digit", "sy": "digit", "sf": "digit",
    "av": "title", "çev": "title", "org": "title",
    "sok": "cap", "sk": "cap", "cd": "cap", "mh": "cap", "plz": "cap", "bul": "cap", "apt": "cap", "san": "cap",
    "fak": "cap", "ist": "cap", "ank": "cap", "izm": "cap", "ms": "upper", "mö": "upper",
    "tel": "capdigit", "bl": "capdigit", "md": "md", "yrd": "yrd",
}
#: Cümle sonundaysa noktası korunur ("elma, armut vb." → "elma, armut ve benzeri.").
_ABBREV_KEEP_PERIOD = {"vb", "vs", "vd", "yy", "şti", "a.ş", "ltd"}
_ABBREV_SENTENCE_FINAL = {"vb", "vs", "vd", "yy"}   # ardından büyük harf gelse de cümle biter

#: Birimler: kısaltma → (okunuş, büyük/küçük harf duyarsız mı). Duyarlı olanlar: m (metre) ≠ M (milyon),
#: g (gram) ≠ G (5G), W/V yalnız büyük, "sa"/"ha" yalnız küçük (Türkçe sözcüklerle karışmasın).
_UNITS: dict[str, tuple[str, bool]] = {
    # uzunluk / alan / hacim
    "km": ("kilometre", True), "m": ("metre", False), "cm": ("santimetre", True), "mm": ("milimetre", True),
    "dm": ("desimetre", False), "nm": ("nanometre", False), "µm": ("mikrometre", False), "μm": ("mikrometre", False),
    "km²": ("kilometrekare", True), "km2": ("kilometrekare", True), "m²": ("metrekare", False),
    "m2": ("metrekare", False), "cm²": ("santimetrekare", True), "cm2": ("santimetrekare", True),
    "mm²": ("milimetrekare", True), "mm2": ("milimetrekare", True), "m³": ("metreküp", False),
    "m3": ("metreküp", False), "cm³": ("santimetreküp", True), "cm3": ("santimetreküp", True), "ha": ("hektar", False),
    # ağırlık
    "kg": ("kilogram", True), "g": ("gram", False), "gr": ("gram", True), "mg": ("miligram", True),
    "µg": ("mikrogram", False), "μg": ("mikrogram", False), "mcg": ("mikrogram", True),
    # sıvı
    "lt": ("litre", True), "l": ("litre", False), "L": ("litre", False), "ml": ("mililitre", True),
    "cl": ("santilitre", True), "dl": ("desilitre", True), "cc": ("si si", True),
    # hız
    "km/s": ("kilometre saat", True), "km/sa": ("kilometre saat", True), "km/h": ("kilometre saat", True),
    "m/s": ("metre saniye", False), "m/sn": ("metre saniye", False),
    # veri
    "gb": ("gigabayt", True), "mb": ("megabayt", True), "tb": ("terabayt", True), "kb": ("kilobayt", True),
    "mbps": ("megabit", True), "gbps": ("gigabit", True), "kbps": ("kilobit", True),
    # frekans
    "hz": ("hertz", True), "khz": ("kilohertz", True), "mhz": ("megahertz", True), "ghz": ("gigahertz", True),
    # zaman ("ms" yalnız küçük: "MS 500" milattan sonradır)
    "sn": ("saniye", True), "sa": ("saat", False), "dk": ("dakika", True), "min": ("dakika", True),
    "ms": ("milisaniye", False),
    # enerji / elektrik
    "kcal": ("kilokalori", True), "cal": ("kalori", True), "mAh": ("miliamper saat", False),
    "mah": ("miliamper saat", False), "W": ("vat", False), "kW": ("kilovat", True), "kWh": ("kilovatsaat", True),
    "MW": ("megavat", False), "V": ("volt", False), "mA": ("miliamper", False),
    # ses / görüntü
    "dB": ("desibel", True), "px": ("piksel", True), "fps": ("ef pi es", True), "dpi": ("di pi ay", True),
}
#: Geriye dönük uyumluluk için düz birim tablosu (okunuş).
TR_UNITS = {k: w for k, (w, _) in _UNITS.items()} | {"°c": "derece", "°f": "fahrenhayt derece", "tl": "lira"}

#: Sayıya bağlı olmayan, kalan semboller.
TR_SYMBOLS = {"&": " ve ", "+": " artı ", "%": " yüzde ", "‰": " binde ", "₺": " lira ", "$": " dolar ",
              "€": " euro ", "£": " sterlin ", "@": " et ", "°": " derece ", "§": " madde ", "№": " numara ",
              "÷": " bölü ", "±": " artı eksi ", "²": " kare ", "³": " küp "}

#: Para birimleri: ad → (birim, alt birim).
_CURRENCIES = {"lira": ("lira", "kuruş"), "dolar": ("dolar", "sent"), "euro": ("euro", "sent"),
               "avro": ("avro", "sent"), "sterlin": ("sterlin", "peni")}
_CURRENCY_ALIASES = {
    "₺": "lira", "tl": "lira", "try": "lira", "lira": "lira", "trl": "lira",
    "$": "dolar", "usd": "dolar", "dolar": "dolar",
    "€": "euro", "eur": "euro", "euro": "euro", "avro": "avro",
    "£": "sterlin", "gbp": "sterlin", "sterlin": "sterlin",
}

#: Türkçe harf adları (K için günlük konuşmadaki "ka").
TR_LETTER_NAMES = {
    "A": "a", "B": "be", "C": "ce", "Ç": "çe", "D": "de", "E": "e", "F": "fe", "G": "ge", "Ğ": "yumuşak ge",
    "H": "he", "I": "ı", "İ": "i", "J": "je", "K": "ka", "L": "le", "M": "me", "N": "ne", "O": "o", "Ö": "ö",
    "P": "pe", "R": "re", "S": "se", "Ş": "şe", "T": "te", "U": "u", "Ü": "ü", "V": "ve", "Y": "ye", "Z": "ze",
    "Q": "kü", "W": "çift ve", "X": "iks",
}

#: Türk kurum/kavram kısaltmaları — Türkçe harf adlarıyla okunur (okunuş otomatik üretilir).
_TR_SPELL_LIST = [
    "AB", "BM", "TC", "TL", "TV", "BT", "ABD", "BAE", "KKTC", "KDV", "ÖTV", "TBMM", "CHP", "AKP", "MHP", "HDP",
    "PTT", "THY", "TRT", "ÖSYM", "YKS", "TYT", "AYT", "KPSS", "LGS", "DGS", "YDS", "AÖF", "SGK", "SSK", "AVM",
    "GSM", "ATM", "PDF", "İBB", "İETT", "EYT", "AYM", "YSK", "TSK", "MSB", "TCMB", "BDDK", "SPK", "TMSF", "TFF",
    "TSE", "TCDD", "TMO", "TPAO", "TTK", "TCK", "HMK", "CMK", "TBK", "TMK", "EKG", "HPV", "PCR", "KTÜ", "DSİ",
    "GS", "FB", "TS", "BJK", "AŞ", "İK", "EFT",
]

#: Bilinen doğrudan okunuşlar: İngilizce harf adlarıyla okunanlar ve sözcük gibi okunan kısaltmalar.
EN_SPELL_WORDS = {
    # İngilizce harf adlarıyla (Türkçede yerleşik söyleyiş)
    "SMS": "es em es", "CD": "si di", "DVD": "di vi di", "USB": "yu es bi", "PC": "pi si", "CV": "si vi",
    "DJ": "di cey", "AI": "yapay zeka", "IT": "ay ti", "HR": "eyç ar", "CEO": "si i o", "CFO": "si ef o",
    "CTO": "si ti o", "URL": "yu ar el", "HTML": "eyç ti em el", "CSS": "si es es", "CPU": "si pi yu",
    "GPU": "ci pi yu", "SSD": "es es di", "HDD": "eyç di di", "HDMI": "eyç di em ay", "HDR": "eyç di ar",
    "HBO": "eyç bi o", "KFC": "ka ef si", "SUV": "es yu vi", "GIF": "cif", "DM": "di em", "PM": "pi em",
    "CS": "si es", "PUBG": "pabci", "GPS": "ce pe es", "API": "ey pi ay", "LCD": "el si di", "BBC": "bi bi si",
    "CNN": "si en en", "NBA": "en bi ey", "FBI": "ef bi ay", "CIA": "si ay ey", "IMF": "ay em ef",
    "AIDS": "eyds", "HIV": "eyç ay vi", "USA": "yu es ey", "UK": "yu key", "NFT": "en ef ti", "VR": "vi ar",
    "VPN": "vi pi en", "QR": "kü ar", "IP": "ay pi", "UI": "yu ay", "UX": "yu eks", "CRM": "si ar em",
    "ERP": "i ar pi", "MR": "em ar", "B2B": "bi tu bi", "B2C": "bi tu si", "MP3": "em pe üç", "MP4": "em pe dört",
    "LTE": "el ti i", "4K": "dört ka", "8K": "sekiz ka", "5G": "beş ce", "3D": "üç de", "2D": "iki de",
    "F1": "formula bir", "BMW": "be me ve", "DNA": "de en a", "WWW": "ve ve ve", "WHO": "dablyu eyç o",
    "NASDAQ": "nasdak", "IBB": "i be be", "IETT": "i e te te",
    # sözcük gibi okunanlar (küçük harfe çevrilir)
    "NATO": "nato", "NASA": "nasa", "UNICEF": "unisef", "UNESCO": "unesko", "FIFA": "fifa", "UEFA": "uefa",
    "TÜBİTAK": "tübitak", "TUBITAK": "tübitak", "ASELSAN": "aselsan", "TOKİ": "toki", "MEB": "meb",
    "TÜİK": "tüik", "TEOG": "teog", "TOEFL": "tofıl", "IELTS": "aylts", "LASER": "lazer", "RADAR": "radar",
    "VIP": "vip", "RAM": "ram", "LED": "led", "OLED": "oled", "OPEC": "opek", "COVID": "kovid", "SEO": "seo",
    "YÖK": "yök", "ODTÜ": "odtü", "İTÜ": "itü", "AFAD": "afad", "HES": "hes", "BES": "bes", "TOGG": "tog",
    "IBAN": "iban", "İBAN": "iban",
    # sayıdan bağımsız para kodları ("USD/TRY paritesi")
    "USD": "dolar", "EUR": "euro", "GBP": "sterlin", "TRY": "lira",
    # veri birimleri (sayısız kullanım: "kaç GB?")
    "GB": "gigabayt", "MB": "megabayt", "TB": "terabayt", "KB": "kilobayt",
}

#: Küçük harfle yazıldığında da (sms, pdf, usb…) kısaltma sayılanlar — Türkçe sözcüklerle çakışmayanlar.
#: Bilinçli olarak YOK: "it" (köpek), "ok" (ok-yay), "ab", "ip" (urgan), "bm".
_ACRONYM_LOWER_OK = [
    "SMS", "PDF", "USB", "DVD", "CD", "ATM", "GPS", "URL", "HTML", "CSS", "CPU", "GPU", "SSD", "HDD", "HDMI",
    "DNA", "AVM", "GSM", "KDV", "TV", "PC", "CV", "DJ", "GIF", "CEO", "API", "MP3", "MP4", "VPN", "NFT", "LCD",
    "ABD", "TBMM", "SGK", "PTT", "THY", "TRT", "KPSS", "YKS", "LGS", "ÖSYM", "DM", "PM", "QR", "UI", "UX",
    "CRM", "ERP", "SUV", "KFC", "BMW", "HBO", "UNICEF", "UNESCO", "TOEFL", "IELTS", "LASER", "OPEC", "COVID",
    "GB", "MB", "TB", "KB", "TC", "TL", "AI",
]

#: Türkçe metinde geçen yabancı marka/terimlerin Türkçe okunuşu. data/pronunciations.json ile genişletilebilir.
#: Büyük/küçük harf duyarsız eşleşir (tr_lower). Yazılışı değişmeyenler (link, trend, viral, spa…) bilinçli
#: olarak yoktur. Türkçe sözcükle çakışanlar da yoktur: "meme" (meme kanseri), "ok" (yalnız "OK"/"Ok").
DEFAULT_PRONUNCIATIONS = {
    # --- mevcut okunuşlar ---
    "ElevenLabs": "İlevın Labs", "YouTube": "Yutub", "Instagram": "İnstagram", "TikTok": "Tiktok",
    "Shopify": "Şopifay", "Google": "Gugıl", "Gmail": "Cimeyl", "iPhone": "Ayfon", "iPad": "Aypet",
    "WhatsApp": "Vatsap", "Chrome": "Krom", "ChatGPT": "Çet Cipiti", "OpenAI": "Open Ey Ay",
    "Claude": "Klod", "Anthropic": "Antropik", "GitHub": "Githab", "LinkedIn": "Linktin",
    "Facebook": "Feysbuk", "Netflix": "Netfliks", "Spotify": "Spotifay",
    "Microsoft": "Maykrosoft", "Windows": "Vindovs", "macOS": "Mek O Es", "Android": "Endroid",
    "Wi-Fi": "Vay Fay", "wifi": "vay fay", "Bluetooth": "Blutut", "e-mail": "i meyl", "email": "i meyl",
    "online": "onlayn", "offline": "oflayn", "download": "davnlod", "upload": "aplod", "update": "apdeyt",
    "like": "layk", "story": "stori", "reels": "rils", "shorts": "şorts", "podcast": "podkest",
    "influencer": "influensır", "freelance": "frilens", "start-up": "startap", "startup": "startap",
    "SaaS": "Sas", "Railway": "Reylvey", "Vercel": "Vörsel", "Notion": "Noşın", "Canva": "Kanva",
    "CapCut": "Kepkat", "Premiere": "Primiyer", "Photoshop": "Fotoşop", "Excel": "Eksel", "Word": "Vörd",
    "Nike": "Nayk", "Apple": "Epıl",
    # --- sosyal medya / iletişim ---
    "Twitter": "Tivitır", "Discord": "Diskord", "Twitch": "Tiviç", "Snapchat": "Snepçet",
    "Pinterest": "Pintırest", "Reddit": "Redit", "Zoom": "Zum", "Teams": "Tims", "Slack": "Slek",
    "Jira": "Cira",
    # --- e-ticaret / ödeme / eğlence ---
    "eBay": "İbey", "Etsy": "Etsi", "PayPal": "Peypal", "Stripe": "Strayp", "iyzico": "iyziko",
    "Disney": "Dizni", "Prime": "Praym", "Apple Music": "Epıl Müzik",
    # --- otomotiv / perakende / yiyecek ---
    "Mercedes": "Mersedes", "Volkswagen": "Folksvagen", "Hyundai": "Hyunday", "Renault": "Reno",
    "Peugeot": "Pejo", "Citroën": "Sitroen", "Citroen": "Sitroen", "H&M": "Haşem", "LC Waikiki": "Le Ce Vaykiki",
    "Starbucks": "Starbaks", "McDonald's": "Mekdonalds", "McDonalds": "Mekdonalds", "Burger King": "Börger King",
    "Coca-Cola": "Koka Kola", "Red Bull": "Red Bul",
    # --- teknoloji markaları / yazılım ---
    "Xiaomi": "Şaomi", "Huawei": "Huavey", "OnePlus": "Vanplas", "MacBook": "Mekbuk", "AirPods": "Eyrpods",
    "iOS": "ay o es", "Office": "Ofis", "PowerPoint": "Pavırpoynt", "Outlook": "Autluk", "OneDrive": "Vandrayv",
    "Dropbox": "Dropboks", "iCloud": "Ayklaud", "GitLab": "Gitlab", "Docker": "Dokır", "Kubernetes": "Kubernetis",
    "Python": "Paytın", "JavaScript": "Cavaskript", "TypeScript": "Taypskript", "React": "Riakt", "Node": "Nod",
    "Node.js": "Nod Cey Es", "Java": "Cava", "Linux": "Linuks", "Gemini": "Cemini", "Copilot": "Kopaylot",
    "Midjourney": "Midcörni", "DeepL": "Dip El", "Lightroom": "Laytrum", "After Effects": "Aftır Efekts",
    "DaVinci": "Davinçi", "Blender": "Blendır", "Unity": "Yuniti", "Unreal": "Anriıl",
    # --- oyun ---
    "Steam": "Stim", "PlayStation": "Pleysteyşın", "Xbox": "Eksboks", "Fortnite": "Fortnayt",
    "Minecraft": "Maynkraft", "Roblox": "Robloks", "League of Legends": "Lig of Lecınds",
    # --- donanım / görüntü ---
    "full HD": "ful eyç di", "4.5G": "dört buçuk ge", "COVID-19": "kovid on dokuz", "USB-C": "yu es bi si",
    "Type-C": "tayp si",
    # --- sosyal medya dili ---
    "follow": "folov", "share": "şeır", "live": "layv", "stream": "strim", "e-commerce": "i komers",
    "dropshipping": "dropşiping", "branding": "brending", "content": "kontent", "creator": "kriyeytır",
    "feedback": "fidbek", "deadline": "dedlayn", "meeting": "miting", "brief": "brif", "check": "çek",
    "OK": "okey", "Ok": "okey", "cool": "kul", "chill": "çil", "vibe": "vayb", "mood": "mud",
    "hashtag": "haştag", "tag": "teg", "mention": "menşın", "spoiler": "spoylır", "teaser": "tizır",
    "trailer": "treylır", "premium": "premiyum", "budget": "bacıt", "cashback": "keşbek",
    "black friday": "blek fraydey", "sale": "seyl", "outlet": "autlet", "showroom": "şovrum",
    # --- spor / yeme-içme ---
    "fitness": "fitnes", "gym": "cim", "cardio": "kardiyo", "detox": "detoks", "smoothie": "smuti",
    "snack": "snek", "brunch": "branç", "cheesecake": "çizkeyk", "cupcake": "kapkeyk", "cookie": "kuki",
    "americano": "amerikano", "mocha": "moka", "frappe": "frape", "iced": "ayst", "fast food": "fest fud",
    "delivery": "dilivıri", "takeaway": "teykevey",
    # --- seyahat ---
    "booking": "buking", "check-in": "çekin", "check-out": "çekaut", "resort": "rizort", "wellness": "velnes",
    "jacuzzi": "jakuzi", "suite": "suit", "lounge": "launc", "business class": "biznıs klas",
    "economy": "ekonomi", "boarding": "bording", "rent a car": "rent e kar",
    # --- otomobil ---
    "drive": "drayv", "test drive": "test drayv", "crossover": "krosovır", "hatchback": "heçbek",
    "coupe": "kupe", "hybrid": "haybrid", "charging": "çarcing", "range": "reync",
    # --- yazılım / arayüz ---
    "feature": "fiçır", "upgrade": "apgreyd", "install": "instol", "setup": "setap", "logout": "logaut",
    "password": "pasvörd", "username": "yuzırneym", "account": "akaunt", "profile": "profayl",
    "dashboard": "deşbord", "default": "difolt", "preview": "privyu", "render": "rendır", "export": "eksport",
    "template": "templeyt", "plugin": "plagin", "widget": "vicıt", "cloud": "klaud", "server": "sörvır",
    "domain": "domeyn", "backup": "bekap", "cache": "keş", "browser": "bravzır", "search": "sörç",
    "filter": "filtır", "scroll": "skrol", "swipe": "svayp", "click": "klik", "tap": "tep", "touch": "taç",
    "screenshot": "skrinşat", "screen": "skrin", "display": "displey", "refresh": "rifreş",
    "wireless": "vayrlıs",
    # --- oyun dili ---
    "gaming": "geyming", "gamer": "geymır", "tournament": "turnament", "ranked": "renkt", "level": "levıl",
    "quest": "kuest", "loot": "lut",
}
#: Yalnız tam bu yazılışla eşleşen anahtarlar (küçük hali Türkçe sözcük ya da başka bir şey olabilir).
PRONUNCIATION_CASE_SENSITIVE = {"OK", "Ok", "4.5G"}


# =============================================================================
# 3. SAYI OKUMA
# =============================================================================

_ONES = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
_TENS = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]
_SCALES = [(10**12, "trilyon"), (10**9, "milyar"), (10**6, "milyon"), (1000, "bin")]
_DIGIT_WORDS = ["sıfır"] + _ONES[1:]


def _n2w(n: float | int, lang: str, to: str = "cardinal") -> str:
    """num2words sarmalayıcı; dil desteklenmiyorsa rakamı aynen döndürür."""
    if num2words is None:
        return str(n)
    try:
        return num2words(n, lang=lang, to=to)
    except Exception:  # noqa: BLE001 — dil desteklenmiyorsa rakam kalsın
        return str(n)


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
    """Sıra sayısı: 4 → 'dördüncü', 21 → 'yirmi birinci'."""
    w = tr_int_to_words(n)
    last = w.split()[-1]
    vowels = [c for c in last if c in TR_VOWELS]
    v = vowels[-1] if vowels else "i"
    suffix = {"a": "ıncı", "ı": "ıncı", "e": "inci", "i": "inci", "o": "uncu", "u": "uncu", "ö": "üncü", "ü": "üncü"}[v]
    if last == "dört":
        last = "dörd"
    if last[-1] in TR_VOWELS:
        suffix = suffix[1:]
    return " ".join(w.split()[:-1] + [last + suffix])


def read_number_tr(digits: str) -> str:
    """Rakam dizisini okur; baştaki sıfırlar tek tek söylenir: '05' → 'sıfır beş', '00' → 'sıfır sıfır'."""
    digits = digits.strip()
    stripped = digits.lstrip("0")
    zeros = len(digits) - len(stripped)
    if not stripped:
        return " ".join(["sıfır"] * max(zeros, 1))
    return " ".join(["sıfır"] * zeros + [tr_int_to_words(int(stripped))])


def _int_tr(s: str) -> str:
    return tr_int_to_words(int(s))


def _n2w_tr(n: int, to: str = "cardinal") -> str:
    return tr_ordinal(n) if to == "ordinal" else tr_int_to_words(n)


def _read_fraction_digits(d: str) -> str:
    """Ondalık kısmı okur: en çok üç hane sayı olarak ('05' → 'sıfır beş'), daha uzunu hane hane."""
    if len(d) > 3:
        return " ".join(_DIGIT_WORDS[int(c)] for c in d)
    return read_number_tr(d)


def _decimal_words(ip: str, fp: str | None, sep: str | None) -> str:
    """Tam + ondalık kısım: ',5' → 'buçuk' (sıfırla değil), diğerleri 'virgül' / İngilizce stilde 'nokta'."""
    iw = read_number_tr(ip) if ip else "sıfır"
    if not fp:
        return iw
    if fp == "5" and ip and int(ip) != 0:
        return f"{iw} buçuk"
    return f"{iw} {'virgül' if sep == ',' else 'nokta'} {_read_fraction_digits(fp)}"


_RE_TR_THOUSANDS = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?")
_RE_EN_THOUSANDS = re.compile(r"\d{1,3}(?:,\d{3}){2,}(?:\.\d+)?|\d{1,3}(?:,\d{3})+\.\d+")


def _split_numeric(s: str) -> tuple[str, str | None, str | None] | None:
    """Sayıyı (tam, ondalık, ayraç) olarak ayrıştırır; sürüm/IP gibi çok parçalıysa None.

    Türkçe öncelikli: '1.250' binlik, '2,5' ondalık; tek noktalı ve 3 hane olmayan '2.5'/'3.14' İngilizce ondalık.
    """
    if s.isdecimal():
        return s, None, None
    if _RE_TR_THOUSANDS.fullmatch(s):
        ip, _, fp = s.partition(",")
        return ip.replace(".", ""), fp or None, ","
    if _RE_EN_THOUSANDS.fullmatch(s):
        ip, _, fp = s.partition(".")
        return ip.replace(",", ""), fp or None, "."
    if s.count(",") == 1 and "." not in s:
        ip, fp = s.split(",")
        return ip, fp, ","
    if s.count(".") == 1 and "," not in s:
        ip, fp = s.split(".")
        return ip, fp, "."
    return None


def _read_numeric(s: str) -> str:
    """Ayraçlı sayıyı okur: '1.250' → 'bin iki yüz elli', '2,5' → 'iki buçuk', '1.2.3' → 'bir nokta iki nokta üç'."""
    parts = _split_numeric(s)
    if parts is None:
        return " ".join(read_number_tr(p) if p.isdecimal() else ("nokta" if p == "." else "virgül")
                        for p in re.split(r"([.,])", s) if p)
    return _decimal_words(*parts)


def _numeric_value(s: str) -> float:
    """Aralık karşılaştırması için sayısal değer (ayrıştırılamazsa ValueError)."""
    parts = _split_numeric(s)
    if parts is None:
        raise ValueError(s)
    ip, fp, _ = parts
    return float(f"{ip}.{fp}") if fp else float(ip)


def _range_sep(a: str, b: str) -> str:
    """Aralık ayıracı: yakın ve küçük sayılarda boşluk ('üç dört kişi'), diğerlerinde virgül duraklaması."""
    try:
        x, y = _numeric_value(a), _numeric_value(b)
    except ValueError:
        return ", "
    return " " if abs(y - x) <= 10 and max(x, y) < 100 else ", "


# =============================================================================
# 4. EK UYUMU — "2024'te", "TL'ye", "ABD'de"
# =============================================================================

#: Son sözcüğü bunlarla bitenler kural dışı ince/yuvarlak ünlü uyumu alır ("saate", "kontrolü").
_HARMONY_EXCEPTIONS = {
    "saat": "e", "kalp": "e", "harf": "e", "dikkat": "e",
    "gol": "ö", "rol": "ö", "mol": "ö", "alkol": "ö", "kontrol": "ö", "petrol": "ö", "sembol": "ö", "protokol": "ö",
}
_SOFTENING = {"dört": "dörd", "kalp": "kalb"}     # ünlüyle başlayan ekten önce yumuşama: dört+ü → dördü
_RE_BUF_Y = re.compile(r"y[aeıioöuü]")           # kaynaştırma y: -ye, -yı, -yle
_RE_BUF_N = re.compile(r"n[ıiuü]n")               # ilgi eki -nin
_RE_BUF_S = re.compile(r"s[ıiuü](?!z)")           # iyelik -si (ama -siz değil)
_RE_GENITIVE_BARE = re.compile(r"[ıiuü]n")


def attach_suffix(phrase: str, suffix: str) -> str:
    """Kesmeyle yazılmış eki okunuşun son sözcüğüne uyumlu biçimde bitiştirir.

    'iki bin yirmi dört' + 'te' → '… dörtte'; 'lira' + 'ye' → 'liraya'; 'kuruş' + 'ye' → 'kuruşa';
    'yirmi dört' + 'ü' → '… dördü'; 'yapay zeka' + 'ın' → '… zekanın'. Doğru yazılmış ek değişmez.
    """
    suffix = tr_lower(suffix or "").strip("' ")
    if not suffix or not phrase:
        return phrase
    if suffix == "s":                       # İngilizce çoğul: 1990's → doksanlar
        suffix = "ler"
    head, sp, stem = phrase.rpartition(" ")
    low = tr_lower(stem)
    if not low or not low[-1].isalpha():
        return phrase + suffix
    base = low                              # uyumu belirleyen (sanal) gövde
    for word, vowel in _HARMONY_EXCEPTIONS.items():
        if low.endswith(word):
            base = low + vowel
            break

    s = suffix
    if low[-1] in TR_VOWELS:
        if s[0] in TR_VOWELS:               # ünlü + ünlü → kaynaştırma ünsüzü
            s = ("n" if _RE_GENITIVE_BARE.fullmatch(s) else "y") + s
    else:
        if _RE_BUF_Y.match(s) or _RE_BUF_N.match(s) or _RE_BUF_S.match(s):
            s = s[1:]                       # ünsüzden sonra kaynaştırma ünsüzü düşer: kuruş+ye → kuruşa
        if s and s[0] in TR_VOWELS and low in _SOFTENING:
            stem = _SOFTENING[low]

    out: list[str] = []
    prev = tr_lower(stem)[-1]
    i = 0
    while i < len(s):
        c = s[i]
        # "-ki" (bulunma eki ardından) uyuma girmez: 2024'teki → dörtteki
        if c == "k" and s.startswith("ki", i) and "".join(out[-2:]) in ("de", "da", "te", "ta"):
            out.append("ki")
            base += "ki"
            prev = "i"
            i += 2
            continue
        if c in "ea":
            c = harmony_vowel_2(base)
        elif c in "ıiuü":
            c = harmony_vowel_4(base)
        elif c in "dt":
            c = "t" if prev in TR_HARD_CONSONANTS else "d"
        elif c in "cç":
            c = "ç" if prev in TR_HARD_CONSONANTS else "c"
        out.append(c)
        base += c
        prev = c
        i += 1
    return f"{head}{sp}{stem}{''.join(out)}"


# =============================================================================
# 5. HARF HARF OKUMA
# =============================================================================

def _spell_letters(word: str) -> str:
    """Harfleri Türkçe adlarıyla, rakam öbeklerini sayı olarak okur: 'TBMM' → 'te be me me', 'A4' → 'a dört'."""
    parts = []
    for run in re.findall(r"\d+|[^\W\d_]", word):
        if run.isdecimal():
            parts.append(read_number_tr(run))
        else:
            name = TR_LETTER_NAMES.get(tr_upper(run))
            if name:
                parts.append(name)
    return " ".join(parts)


TR_SPELL = {k: _spell_letters(k) for k in _TR_SPELL_LIST}
_ACRONYM_EXACT = {**TR_SPELL, **EN_SPELL_WORDS}
_ACRONYM_LOWER = {tr_lower(k): k for k in _ACRONYM_LOWER_OK if k in _ACRONYM_EXACT}


def spell_acronym(word: str) -> str:
    """Kısaltmanın okunuşu: bilinen özel okunuşlar önce ('SMS' → 'es em es'), yoksa Türkçe harf adları.

    'ABD' → 'a be de', 'KDV' → 'ka de ve', 'ÖSYM' → 'ö se ye me', 'A4' → 'a dört'.
    """
    w = word.strip().strip(".")
    hit = _ACRONYM_EXACT.get(w) or _ACRONYM_EXACT.get(tr_upper(w))
    return hit if hit is not None else _spell_letters(w)


_ONSETS = {"bl", "br", "dr", "fl", "fr", "gl", "gr", "kl", "kr", "pl", "pr", "sk", "sl", "sm", "sn", "sp", "st",
           "sv", "şp", "şt", "tr", "ps", "ks"}
_FINALS = {"nk", "rt", "st", "lt", "ns", "rs", "ks", "lk", "rk", "nç", "rç", "lç", "rp", "lp", "mp", "lm", "rm",
           "rf", "rz", "ft", "kt", "sk", "şk", "şt", "nt", "nd", "rd", "ng", "lf", "ls", "zm"}
_RE_ROMAN = re.compile(r"M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})")
_RE_LOAN_ONSET3 = re.compile(r"(?:str|spr|skr|spl)[aeıioöuü]")     # STRES, SPREY


def _looks_like_acronym(word: str) -> bool:
    """Büyük harfli 3–5 harflik sözcük Türkçe hece yapısına uymuyorsa kısaltmadır.

    AKP, İBB, DSİ → kısaltma; STOK, PLAN, STRES, ARTIK → sözcük (bağırma yazımı, dokunulmaz).
    """
    w = _fold(word)
    if not any(c in TR_VOWELS for c in w):
        return True
    if not is_turkish_word_like(word) and not _RE_LOAN_ONSET3.match(w):
        return True
    if w[0] not in TR_VOWELS and w[1] not in TR_VOWELS and w[:2] not in _ONSETS:
        return True
    if w[-1] not in TR_VOWELS and w[-2] not in TR_VOWELS and w[-2:] not in _FINALS:
        return True
    return False


def _acronym_reading(w: str) -> str | None:
    """Sözcük kısaltma olarak okunacaksa okunuşu, değilse None."""
    letters = [c for c in w if c.isalpha()]
    if not letters:
        return None
    if all(c == tr_upper(c) for c in letters):                # tamamı büyük harf
        hit = _ACRONYM_EXACT.get(w)
        if hit is not None:
            return hit
        if any(c.isdecimal() for c in w):                    # A4, H2O, PS5, G20
            return " ".join(_ACRONYM_EXACT.get(run) or (read_number_tr(run) if run.isdecimal() else _spell_letters(run))
                            for run in re.findall(r"\d+|[^\W\d_]+", w))
        if not 3 <= len(w) <= 5 or _RE_ROMAN.fullmatch(w):
            return None                                        # 2 harfli (AL, ON, EV) ve Roma rakamı: dokunma
        return _spell_letters(w) if _looks_like_acronym(w) else None
    key = _ACRONYM_LOWER.get(tr_lower(w))
    return _ACRONYM_EXACT[key] if key else None


# =============================================================================
# 6. PARA VE SAAT (sözleşmedeki açık yardımcılar)
# =============================================================================

def _currency_info(currency: str) -> tuple[str, str | None]:
    name = _CURRENCY_ALIASES.get(_fold(currency.strip()), _fold(currency.strip()))
    return _CURRENCIES.get(name, (currency.strip(), None))


def _split_amount(s: str) -> tuple[str, str | None]:
    """Para tutarını (tam, ondalık) ayırır. '1.250,75' / '1,250.75' / '12.50' / '1.250' (binlik) / '12,5'."""
    s = s.replace(" ", "")
    has_dot, has_comma = "." in s, "," in s
    if has_dot and has_comma:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        ip, fp = s.rsplit(dec, 1)
        return ip.replace("." if dec == "," else ",", ""), fp
    sep = "." if has_dot else ("," if has_comma else None)
    if sep is None:
        return s, None
    parts = s.split(sep)
    if len(parts) > 2 or len(parts[1]) == 3:                  # 1.250.000 / 1.250 → binlik
        return "".join(parts), None
    return parts[0], parts[1]


def read_money_tr(amount: str, currency: str = "lira") -> str:
    """Para tutarını okur: ('12,50', 'lira') → 'on iki lira elli kuruş'; ('12.50', '$') → 'on iki dolar elli sent'.

    Sıfır kuruş söylenmez ('12,00 TL' → 'on iki lira'); yalnız kuruşsa birim söylenmez ('0,50' → 'elli kuruş').
    """
    unit, sub = _currency_info(currency)
    ip, fp = _split_amount(amount)
    ip = ip or "0"
    iw = read_number_tr(ip) if len(ip) > 1 and ip.startswith("0") and int(ip) else tr_int_to_words(int(ip))
    if fp is None or not fp.strip("0"):
        return f"{iw} {unit}"
    if len(fp) == 1:
        fp += "0"                                              # 12,5 TL → 12 lira 50 kuruş
    if len(fp) > 2 or sub is None:
        return f"{_decimal_words(ip, fp, ',')} {unit}"
    if FIYAT_ETIKETI_VIRGUL and unit == "lira" and ip.endswith("9") and fp in ("90", "95", "99"):
        return f"{iw} virgül {tr_int_to_words(int(fp))} {unit}"
    sw = tr_int_to_words(int(fp))
    return f"{sw} {sub}" if int(ip) == 0 else f"{iw} {unit} {sw} {sub}"


def read_time_tr(h: int, m: int) -> str:
    """Saati okur: (14, 30) → 'on dört otuz', (14, 5) → 'on dört sıfır beş', (14, 0) → 'on dört'."""
    hw = tr_int_to_words(h)
    if m == 0:
        return "sıfır sıfır" if h == 0 else hw
    return f"{hw} {tr_int_to_words(m) if m >= 10 else 'sıfır ' + tr_int_to_words(m)}"


# =============================================================================
# 7. OKUNUŞ SÖZLÜĞÜ — tek birleşik regex, pronunciations.json değişince yeniden derlenir
# =============================================================================

_PRON_STATE: dict = {"key": None, "regex": None, "table": None}


def _pron_file():
    try:
        from .config import DATA_DIR

        return DATA_DIR / "pronunciations.json"
    except Exception:  # noqa: BLE001
        return None


def _load_pronunciations() -> dict:
    """Varsayılan sözlük + data/pronunciations.json (varsa) birleşimi."""
    d = dict(DEFAULT_PRONUNCIATIONS)
    p = _pron_file()
    try:
        if p is not None and p.exists():
            d.update(json.loads(p.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        pass
    return d


def _pron_matcher():
    """(regex, katlanmış tablo) döndürür; tablo: _fold(anahtar) → [okunuş, izinli tam yazılışlar | None]."""
    p = _pron_file()
    try:
        stamp = p.stat().st_mtime_ns if p is not None and p.exists() else None
    except OSError:
        stamp = None
    key = (str(p), stamp)
    if _PRON_STATE["key"] == key and _PRON_STATE["regex"] is not None:
        return _PRON_STATE["regex"], _PRON_STATE["table"]
    table: dict[str, list] = {}
    for k, v in _load_pronunciations().items():
        if not isinstance(k, str) or not isinstance(v, str) or not k.strip():
            continue
        fk = _fold(k.strip())
        exact = k if k in PRONUNCIATION_CASE_SENSITIVE else None
        entry = table.get(fk)
        if entry is None:
            table[fk] = [v, {exact} if exact else None]
        elif exact is None:
            entry[0], entry[1] = v, None
        elif entry[1] is not None:
            entry[1].add(exact)
    alts = "|".join(re.escape(k) for k in sorted(table, key=len, reverse=True))
    regex = re.compile(rf"(?<![\w])(?P<k>{alts})(?![\w]){_SUF}")
    _PRON_STATE.update(key=key, regex=regex, table=table)
    return regex, table


def apply_pronunciations(text: str, lang: str) -> str:
    """Sözlükteki terimleri okunuşlarıyla değiştirir (yalnızca Türkçe için); kesmeli ek bitiştirilir."""
    if lang != "tr" or not text:
        return text
    regex, table = _pron_matcher()
    shadow = _fold(text)
    if len(shadow) != len(text):                              # güvenlik: katlama uzunluğu değiştirdiyse
        shadow = "".join(f if len(f := _fold(ch)) == 1 else ch for ch in text)
    out, last = [], 0
    for m in regex.finditer(shadow):
        entry = table.get(m.group("k"))
        if entry is None:
            continue
        value, exact = entry
        if exact is not None and text[m.start("k"):m.end("k")] not in exact:
            continue
        suf = text[m.start("suf"):m.end("suf")] if m.group("suf") is not None else ""
        out.append(text[last:m.start()])
        out.append(_with_suffix(value, suf))
        last = m.end()
    out.append(text[last:])
    return "".join(out)


# =============================================================================
# 8. AŞAMA: ÖN TEMİZLİK (emoji, emotikon, görünmez karakter, tipografi)
# =============================================================================

_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF\U00002300-\U000023FF"
    "\U000025A0-\U000025FF\u3030\u303d\u3297\u3299\u00a9\u00ae\u2122]+"
)
_RE_INVISIBLE = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u00ad\ufe0e\ufe0f\u20e3\U000E0020-\U000E007F]")
_RE_EMOTICON = re.compile(
    r"(?<!\S)(?:"
    r"[:;=][-'^o]?[)(\]\[DPpOo/\\|*]+"         # :) :( :D ;) :P :/ :* =)
    r"|[xX][dD]+"                              # xD XD
    r"|\((?:[:;]|-:)"                          # (: (;
    r"|</?3+"                                  # <3 </3
    r"|:'[()]"                                 # :'(
    r"|\^[_.]?\^|-_-|[oO]_[oO]|[tT]_[tT]"      # ^^ ^_^ -_- o_O T_T
    r")(?=\s|$|[.,!?])"
)
_TYPO = str.maketrans({
    "“": '"', "”": '"', "„": '"', "«": '"', "»": '"', "‟": '"',
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "ʼ": "'", "´": "'", "`": "'",
    "−": "-", "‐": "-", "‑": "-", "‒": "–",
    "\u00a0": " ", "\u202f": " ", "\u2009": " ", "\u2007": " ", "\u2002": " ", "\u2003": " ",
    "‼": "!", "⁉": "?",
})
_RE_DIGIT_DASH = re.compile(r"(?<=\d)[ \t]?–[ \t]?(?=\d)")   # 2010–2015 → 2010-2015 (aralık)
_RE_DIGIT_HALF = re.compile(r"(?<=\d)½")
_VULGAR_FRACTIONS = {"½": " yarım ", "¼": " çeyrek ", "¾": " dörtte üç ", "⅓": " üçte bir ", "⅔": " üçte iki "}


_RE_NEXT_SENTENCE = re.compile(r"[ \t]*[A-ZÇĞİÖŞÜ]")


def _drop_symbolic(m: re.Match) -> str:
    """Emoji/emotikonu siler; cümle sonu yerine kullanılmışsa ("selam :) Bugün…") nokta bırakır."""
    before = m.string[max(0, m.start() - 4):m.start()].rstrip()
    if before and before[-1].isalnum() and _RE_NEXT_SENTENCE.match(m.string, m.end()):
        return ". "
    return " "


def _emoticon_sub(m: re.Match) -> str:
    tok = m.group(0)
    if tok.startswith("<"):
        before = m.string[max(0, m.start() - 4):m.start()].rstrip()
        if before and before[-1].isdecimal():                 # "5 <3" karşılaştırmadır, kalp değil
            return tok
    return _drop_symbolic(m)


def _stage_preclean(t: str) -> str:
    """NFC, görünmez karakterler, emoji/emotikonlar ve tipografik işaretler."""
    t = unicodedata.normalize("NFC", t)
    t = t.translate(_TYPO)
    t = _RE_INVISIBLE.sub("", t)
    t = _EMOJI.sub(_drop_symbolic, t)
    t = _RE_EMOTICON.sub(_emoticon_sub, t)
    t = t.replace("…", "...")
    t = _RE_DIGIT_HALF.sub(",5", t)                          # 1½ kg → 1,5 kg → "bir buçuk"
    for sym, word in _VULGAR_FRACTIONS.items():
        t = t.replace(sym, word)
    return _RE_DIGIT_DASH.sub("-", t)


# =============================================================================
# 9. AŞAMA: TELEFON / IBAN / KART (parantezler kaybolmadan önce)
# =============================================================================

_RE_IBAN = re.compile(r"(?<![\w])TR\s?(\d{2})\s?(\d{4})\s?(\d{4})\s?(\d{4})\s?(\d{4})\s?(\d{4})\s?(\d{2})(?![\w])")
_RE_CARD = re.compile(r"(?<![\w])(\d{4})[ \-](\d{4})[ \-](\d{4})[ \-](\d{4})(?![\w])")
_RE_444 = re.compile(rf"(?<![\w])444[ \-]?(?P<x>\d)[ \-]?(?P<y>\d{{3}})(?![\w]){_SUF}")
_RE_PHONE = re.compile(
    r"(?<![\w+])(?:"
    r"(?P<cc>\+\s?90|0090)[ \-]?(?:\(\s?0?\s?(?P<a1>\d{3})\s?\)|0?(?P<a2>\d{3}))"
    r"|(?P<zero>0)[ \-]?(?:\(\s?(?P<a3>\d{3})\s?\)|(?P<a4>\d{3}))"
    r"|\(\s?(?P<pz>0)?\s?(?P<a5>\d{3})\s?\)"
    r"|(?P<a6>[2-5]\d{2})"
    rf")[ .\-]?(?P<a>\d{{3}})[ .\-]?(?P<b>\d{{2}})[ .\-]?(?P<c>\d{{2}})(?![\w]){_SUF}"
)
_RE_LONG_DIGITS = re.compile(
    r"(?<![\w.,+])(?P<d>\d{10,})(?![\w]|[.,]\d)"
    rf"(?!\s?(?:[₺$€£]|(?i:tl|try|usd|eur|gbp|lira|dolar|euro)(?![\w]))){_SUF}"
)


def _phone_sub(m: re.Match) -> str:
    area = next(m.group(g) for g in ("a1", "a2", "a3", "a4", "a5", "a6") if m.group(g))
    parts = []
    if m.group("cc"):
        parts.append("artı doksan")
    lead = "sıfır " if (m.group("zero") or m.group("pz")) else ""
    parts.append(lead + read_number_tr(area))
    parts += [read_number_tr(m.group(g)) for g in ("a", "b", "c")]
    return _with_suffix(", ".join(parts), m.group("suf"))


def _group_digits(d: str) -> list[str]:
    """Uzun rakam dizisini okunur gruplara böler: 10 hane 3-3-2-2, 0'la başlayan 11 hane 4-3-2-2, 16 hane 4×4."""
    n = len(d)
    if n == 16:
        return [d[i:i + 4] for i in range(0, 16, 4)]
    if n == 11 and d[0] == "0":
        return [d[:4], d[4:7], d[7:9], d[9:]]
    if n == 10:
        return [d[:3], d[3:6], d[6:8], d[8:]]
    if n == 12 and d.startswith("90"):
        return [d[:2], d[2:5], d[5:8], d[8:10], d[10:]]
    head = d[:-4]
    groups = [head[i:i + 3] for i in range(0, len(head), 3)]
    if len(groups) > 1 and len(groups[-1]) == 1:
        groups[-2:] = [groups[-2][:2], groups[-2][2:] + groups[-1]]
    return groups + [d[-4:-2], d[-2:]]


def _stage_phones(t: str) -> str:
    """Telefon, IBAN, kart numarası ve 10+ haneli dizileri gruplar halinde okur."""
    t = _RE_IBAN.sub(lambda m: "te re " + ", ".join(read_number_tr(g) for g in m.groups()), t)
    t = _RE_CARD.sub(lambda m: ", ".join(read_number_tr(g) for g in m.groups()), t)
    t = _RE_444.sub(lambda m: _with_suffix(
        f"dört yüz kırk dört, {read_number_tr(m.group('x'))}, {read_number_tr(m.group('y'))}", m.group("suf")), t)
    t = _RE_PHONE.sub(_phone_sub, t)
    return _RE_LONG_DIGITS.sub(lambda m: _with_suffix(
        ", ".join(read_number_tr(g) for g in _group_digits(m.group("d"))), m.group("suf")), t)


# =============================================================================
# 10. AŞAMA: YAPI (tire, parantez, köşeli parantez, HTML)
# =============================================================================

_RE_BULLET = re.compile(r"(?m)^[ \t]*[-–—•·*▪►▶➤]+[ \t]+")
_RE_HTML = re.compile(r"</?[A-Za-z][^<>\n]{0,200}>")
_RE_SPACED_HYPHEN = re.compile(r"(?<!\d)[ \t]+-[ \t]+|[ \t]+-[ \t]+(?!\d)")


def _stage_structure(t: str) -> str:
    """Uzun tire ve parantezler kısa duraklamaya döner; köşeli/süslü parantez içi ve HTML etiketleri atılır."""
    t = _RE_HTML.sub(" ", t)
    t = _RE_BULLET.sub("", t)
    t = re.sub(r"[–—]", ", ", t)                      # tire → kısa duraklama
    t = _RE_SPACED_HYPHEN.sub(", ", t)                # "Merhaba - nasılsın" (sayı arası değil)
    t = re.sub(r"\s*\(\s*", ", ", t)                  # parantez → duraklama
    t = re.sub(r"\s*\)\s*", ", ", t)
    t = re.sub(r"\s*\[[^\]]*\]\s*", " ", t)           # köşeli parantez içini at (etiketler önceden ayrıştırıldı)
    return re.sub(r"\s*\{[^}]*\}\s*", " ", t)


# =============================================================================
# 11. AŞAMA: URL / E-POSTA
# =============================================================================

_TLD_READ = {
    "com": "com", "net": "net", "org": "org", "tr": "te re", "io": "ay o", "ai": "ey ay", "co": "ko", "dev": "dev",
    "app": "ep", "me": "mi", "info": "info", "biz": "biz", "xyz": "iks vay zi", "tech": "tek", "store": "stor",
    "shop": "şop", "online": "onlayn", "site": "sayt", "beauty": "byuti", "fit": "fit", "edu": "edu", "gov": "gov",
    "de": "de", "uk": "yu key", "eu": "e u", "fm": "ef em", "tv": "ti vi", "gg": "ci ci", "k12": "ka on iki",
    "bel": "bel", "av": "av", "gen": "gen", "web": "veb", "cloud": "klaud", "blog": "blog", "design": "dizayn",
    "studio": "stüdyo", "art": "art", "media": "medya", "news": "nyuz", "club": "klab", "life": "layf",
    "world": "vörld", "live": "layv", "pro": "pro", "today": "tudey", "academy": "akademi", "games": "geyms",
    "global": "global", "website": "vebsayt", "space": "speys", "digital": "dicital", "agency": "eycınsi",
}
_MULTI_TLDS = ["com.tr", "gov.tr", "edu.tr", "org.tr", "net.tr", "k12.tr", "bel.tr", "av.tr", "gen.tr", "web.tr",
               "biz.tr", "info.tr", "co.uk"]
_SAFE_TLDS = {"com", "net", "org", "edu", "gov", "tr", *_MULTI_TLDS}
_TLD_ALT = "|".join(re.escape(k) for k in sorted([*_TLD_READ, *_MULTI_TLDS], key=len, reverse=True))
_RE_EMAIL = re.compile(
    rf"(?<![\w.+\-])(?P<local>\w[\w.+\-]*)@(?P<host>[\w\-]+(?:\.[\w\-]+)*?\.(?i:{_TLD_ALT}))(?![\w\-]){_SUF}"
)
_RE_URL = re.compile(
    rf"(?<![\w@.\-])(?P<scheme>(?i:https?://))?(?P<www>(?i:www\.))?"
    rf"(?P<host>[\w\-]+(?:\.[\w\-]+)*?\.(?P<tld>(?i:{_TLD_ALT})))(?![\w\-])"
    rf"(?P<path>/[^\s,;!?)\]\"'<>#]*)?(?P<query>[?#][^\s\"'<>]+)?{_SUF}"
)


def _read_host(host: str) -> str:
    labels = host.split(".")
    out = [labels[0].replace("-", " tire ")]
    for lab in labels[1:]:
        out.append(_TLD_READ.get(_fold(lab), lab.replace("-", " tire ")))
    return " nokta ".join(out)


def _email_sub(m: re.Match) -> str:
    local = m.group("local")
    for ch, word in ((".", " nokta "), ("_", " alt çizgi "), ("-", " tire "), ("+", " artı ")):
        local = local.replace(ch, word)
    return _with_suffix(f"{local} et {_read_host(m.group('host'))}", m.group("suf"))


def _url_sub(m: re.Match) -> str:
    host, tld = m.group("host"), _fold(m.group("tld"))
    path = m.group("path") or ""                             # sorgu dizesi (?ref=…) ve #parça okunmaz
    trail = ""
    while path and path[-1] in ".:":
        trail, path = path[-1] + trail, path[:-1]
    explicit = m.group("scheme") or m.group("www") or path or m.group("query")
    if not explicit and tld not in _SAFE_TLDS and host != tr_lower(host):
        return m.group(0)                                    # "Geldim.De" gibi yazım hatası URL değildir
    words = _read_host(host)
    segs = [s for s in path.split("/") if s]
    if segs:
        words += " bölü " + " bölü ".join(re.sub(r"[-_]+", " ", s).replace("@", "et ") for s in segs)
    if trail:                                                # "…/tr." → cümle noktası URL'ye dahil değildir
        return words + trail + (f"'{m.group('suf')}" if m.group("suf") else "")
    return _with_suffix(words, m.group("suf"))


def _stage_urls(t: str) -> str:
    """E-posta ve URL: 'info@firma.com.tr' → 'info et firma nokta com nokta te re'; '/' → 'bölü'."""
    t = _RE_EMAIL.sub(_email_sub, t)
    return _RE_URL.sub(_url_sub, t)


# =============================================================================
# 12. AŞAMA: PARA
# =============================================================================

_AMT = r"\d+(?:[.,]\d{3})*(?:[.,]\d{1,2})?"
#: Önekli kodlar yalnız büyük harf ("USD 100"); sonekte "TL/tl" serbest, "TRY" büyük harf (İngilizce "try" değil).
_RE_MONEY_PRE = re.compile(
    rf"(?<![\w])(?P<cur>[₺$€£]|(?:USD|EUR|GBP|TRY)(?=\s?\d))\s?(?P<amt>{_AMT})(?![\d]|[.,]\d){_SUF}"
)
_RE_MONEY_POST = re.compile(
    rf"(?<![\w.,])(?:(?P<amt1>{_AMT})\s?[-–]\s?)?(?P<amt>{_AMT})\s?"
    r"(?:(?P<sym>[₺$€£])|(?P<code>(?i:tl|usd|eur|gbp)|TRY)(?![\w])"
    r"|(?P<noun>(?i:lira|dolar|euro|avro|sterlin))(?P<glued>[a-zçğıöşü]*)(?![\w]))"
    rf"{_SUF}"
)
_CUR_CODE_ALT = r"(?P<cur>[₺$€£]|(?:(?i:tl|usd|eur|gbp)|TRY)(?![\w]))"
#: Ölçekli tutar: "1 milyon TL", "2,5 milyar $", "500 bin TL'ye", "5K TL" → kuruşsuz okunur.
_SCALE_ALT = r"(?P<scale>(?i:bin|milyon|milyar|trilyon)|[kK]|M|mn|mlr|mly|bn)"
_RE_MONEY_SCALE = re.compile(rf"(?<![\w.,])(?P<amt>{_NUMV})\s?{_SCALE_ALT}\s?{_CUR_CODE_ALT}{_SUF}")
_RE_MONEY_SCALE_PRE = re.compile(rf"(?<![\w])(?P<cur>[₺$€£])\s?(?P<amt>{_NUMV})\s?{_SCALE_ALT}(?![\w]){_SUF}")
#: Yazıyla yazılmış sayıdan sonra kod/sembol: "beş yüz TL" → "beş yüz lira".
_RE_MONEY_WORDS = re.compile(
    r"(?<![\w])(?P<w>bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz|on|yirmi|otuz|kırk|elli|altmış|yetmiş|seksen"
    rf"|doksan|yüz|bin|milyon|milyar|trilyon|buçuk)\s?{_CUR_CODE_ALT}{_SUF}"
)
_SCALE_WORDS = {"k": "bin", "K": "bin", "M": "milyon", "mn": "milyon", "mlr": "milyar", "mly": "milyar", "bn": "milyar"}


def _money_scale_sub(m: re.Match) -> str:
    scale = _SCALE_WORDS.get(m.group("scale")) or tr_lower(m.group("scale"))
    unit, _ = _currency_info(m.group("cur"))
    return _with_suffix(f"{_read_numeric(m.group('amt'))} {scale} {unit}", m.group("suf"))


def _money_words_sub(m: re.Match) -> str:
    unit, _ = _currency_info(m.group("cur"))
    return _with_suffix(f"{m.group('w')} {unit}", m.group("suf"))


def _amount_plain(a: str) -> str:
    ip, fp = _split_amount(a)
    return _decimal_words(ip, fp, ",")


def _money_post_sub(m: re.Match) -> str:
    cur = m.group("sym") or m.group("code") or m.group("noun")
    words = read_money_tr(m.group("amt"), cur)
    if m.group("amt1"):
        words = _amount_plain(m.group("amt1")) + _range_sep(m.group("amt1"), m.group("amt")) + words
    return _with_suffix(words, (m.group("glued") or "") + (m.group("suf") or ""))


def _stage_money(t: str) -> str:
    """₺150, 150 TL, 12,50 TL, $100, 12.50$, 100 USD, €20, £5 → okunuş (kuruş/sent/peni dahil)."""
    t = _RE_MONEY_SCALE.sub(_money_scale_sub, t)
    t = _RE_MONEY_SCALE_PRE.sub(_money_scale_sub, t)
    t = _RE_MONEY_PRE.sub(lambda m: _with_suffix(read_money_tr(m.group("amt"), m.group("cur")), m.group("suf")), t)
    t = _RE_MONEY_POST.sub(_money_post_sub, t)
    return _RE_MONEY_WORDS.sub(_money_words_sub, t)


# =============================================================================
# 13. AŞAMA: YÜZDE / BİNDE
# =============================================================================

_RE_PCT_PRE = re.compile(
    rf"(?<![\w%‰])(?P<sym>[%‰])\s?(?P<a>{_NUMV})(?:\s?[-–]\s?[%‰]?\s?(?P<b>{_NUMV}))?(?![\w]|[.,]\d){_SUF}"
)
_RE_PCT_POST = re.compile(
    rf"(?<![\w.,])(?P<a>{_NUMV})(?:\s?[%‰]?\s?[-–]\s?(?P<b>{_NUMV}))?\s?(?P<sym>[%‰])(?![\w%‰]){_SUF}"
)


def _pct_sub(m: re.Match) -> str:
    words = ("yüzde " if m.group("sym") == "%" else "binde ") + _read_numeric(m.group("a"))
    if m.group("b"):
        words += _range_sep(m.group("a"), m.group("b")) + _read_numeric(m.group("b"))
    return _with_suffix(words, m.group("suf"))


def _stage_percent(t: str) -> str:
    """%20 / 20% → 'yüzde yirmi', %12,5 → 'yüzde on iki buçuk', %20'lik → 'yüzde yirmilik', ‰5 → 'binde beş'."""
    t = _RE_PCT_PRE.sub(_pct_sub, t)
    return _RE_PCT_POST.sub(_pct_sub, t)


# =============================================================================
# 14. AŞAMA: TARİH
# =============================================================================

_RE_DATE_FULL = re.compile(
    rf"(?<![\w.,/\-])(?P<d>\d{{1,2}})(?P<sep>[./\-])(?P<m>\d{{1,2}})(?P=sep)(?P<y>\d{{4}})(?![\d]){_SUF}"
)
_RE_DATE_ISO = re.compile(rf"(?<![\w.,/\-])(?P<y>\d{{4}})-(?P<m>\d{{2}})-(?P<d>\d{{2}})(?![\d]){_SUF}")
_RE_DATE_DM = re.compile(rf"(?<![\w.,/\-])(?P<d>\d{{1,2}})\.(?P<m>\d{{2}})(?![\d]|[.,]\d){_SUF}")
_RE_DATE_MY = re.compile(rf"(?<![\w.,/\-])(?P<m>\d{{1,2}})/(?P<y>(?:19|20)\d{{2}})(?![\d/]){_SUF}")   # 12/2024
_RE_SAAT_BEFORE = re.compile(r"(?i:saat)\s*:?\s*$")
_RE_VERSION_BEFORE = re.compile(r"(?i:sürüm|versiyon|version)\s*$")


def _date_words(d: int, mo: int, y: int | None = None) -> str | None:
    if not (1 <= d <= 31 and 1 <= mo <= 12):
        return None
    w = f"{tr_int_to_words(d)} {TR_MONTHS[mo - 1]}"
    return f"{w} {tr_int_to_words(y)}" if y is not None else w


def _date_full_sub(m: re.Match) -> str:
    w = _date_words(int(m.group("d")), int(m.group("m")), int(m.group("y")))
    return m.group(0) if w is None else _with_suffix(w, m.group("suf"))


def _date_dm_sub(m: re.Match) -> str:
    before = m.string[max(0, m.start() - 12):m.start()]
    if _RE_SAAT_BEFORE.search(before) or _RE_VERSION_BEFORE.search(before):
        return m.group(0)                                     # "saat 10.05" saattir, "sürüm 1.10" sürümdür
    if not m.group("suf") and _unit_follows(m.string, m.end()):
        return m.group(0)                                     # "1.05 kg" sayıdır
    w = _date_words(int(m.group("d")), int(m.group("m")))
    return m.group(0) if w is None else _with_suffix(w, m.group("suf"))


def _stage_dates(t: str) -> str:
    """12.10.2026 / 12/10/2026 / 12-10-2026 / 2026-10-12 / 12.10 → 'on iki ekim (iki bin yirmi altı)'."""
    t = _RE_DATE_FULL.sub(_date_full_sub, t)
    t = _RE_DATE_ISO.sub(_date_full_sub, t)
    t = _RE_DATE_MY.sub(lambda m: m.group(0) if not 1 <= int(m.group("m")) <= 12 else _with_suffix(
        f"{TR_MONTHS[int(m.group('m')) - 1]} {tr_int_to_words(int(m.group('y')))}", m.group("suf")), t)
    return _RE_DATE_DM.sub(_date_dm_sub, t)


# =============================================================================
# 15. AŞAMA: SAAT
# =============================================================================

_RE_TIME_COLON = re.compile(
    r"(?<![\d:.,])(?P<h>\d{1,2}):(?P<m>\d{2})(?::(?P<s>\d{2}))?"
    rf"(?:\s?[-–]\s?(?P<h2>\d{{1,2}}):(?P<m2>\d{{2}}))?(?![\d:]|[.,]\d){_SUF}"
)
_RE_TIME_SAAT_DOT = re.compile(
    r"(?P<pre>(?<![\w])(?i:saat)\s*:?\s*)(?P<h>\d{1,2})\.(?P<m>\d{2})"
    rf"(?:\s?[-–]\s?(?P<h2>\d{{1,2}})[.:](?P<m2>\d{{2}}))?(?![\d]|[.,]\d){_SUF}"
)
_RE_TIME_DOT = re.compile(
    r"(?<![\w.,:])(?P<h>\d{1,2})\.(?P<m>\d{2})"
    rf"(?:\s?[-–]\s?(?P<h2>\d{{1,2}})\.(?P<m2>\d{{2}}))?(?![\d]|[.,]\d){_SUF}"
)


def _time_words(h: str, m: str, s: str | None = None) -> str | None:
    hi, mi = int(h), int(m)
    if not (0 <= hi <= 24 and 0 <= mi <= 59) or (hi == 24 and mi):
        return None
    w = read_time_tr(hi, mi)
    if s is not None:
        si = int(s)
        if si > 59:
            return None
        if si:
            w += " " + (tr_int_to_words(si) if si >= 10 else "sıfır " + tr_int_to_words(si))
    return w


def _time_core(m: re.Match, with_seconds: bool = False) -> str | None:
    w = _time_words(m.group("h"), m.group("m"), m.group("s") if with_seconds else None)
    if w is not None and m.group("h2"):
        w2 = _time_words(m.group("h2"), m.group("m2"))
        w = None if w2 is None else f"{w}, {w2}"
    return w


def _time_colon_sub(m: re.Match) -> str:
    w = _time_core(m, with_seconds=True)
    return m.group(0) if w is None else _with_suffix(w, m.group("suf"))


def _time_saat_dot_sub(m: re.Match) -> str:
    w = _time_core(m)
    return m.group(0) if w is None else m.group("pre") + _with_suffix(w, m.group("suf"))


def _time_dot_sub(m: re.Match) -> str:
    # bağlamsız nokta biçimi: 2 haneli saat ("14.30") ya da ekli ("9.45'te") ya da aralık; ardından birim yoksa
    if not (len(m.group("h")) == 2 or m.group("suf") or m.group("h2")):
        return m.group(0)                                     # "3.14" ondalıktır
    if not m.group("suf") and _unit_follows(m.string, m.end()):
        return m.group(0)                                     # "12.50 kg" sayıdır
    w = _time_core(m)
    return m.group(0) if w is None else _with_suffix(w, m.group("suf"))


def _stage_times(t: str) -> str:
    """14:30 / saat 14.30 / 14.30 → 'on dört otuz'; 9:05 → 'dokuz sıfır beş'; 14:30'da → 'on dört otuzda'."""
    t = _RE_TIME_SAAT_DOT.sub(_time_saat_dot_sub, t)
    t = _RE_TIME_COLON.sub(_time_colon_sub, t)
    return _RE_TIME_DOT.sub(_time_dot_sub, t)


# =============================================================================
# 16. AŞAMA: SIRA SAYILARI (Roma rakamları dahil)
# =============================================================================

_RE_ORD_SUFFIX = re.compile(
    r"(?<![\w.,])(?P<n>\d+)'?(?:inci|ıncı|uncu|üncü|nci|ncı|ncu|ncü)(?P<rest>[a-zçğıöşü]*)(?![\w])"
)
#: "3. sınıf" (küçük harf) ya da adres sözcüğü ("5. Sok.", "2. Kat") öncesi nokta sıra sayısıdır;
#: "Saat 5. Ahmet geldi" (büyük harf) belirsizdir ve cümle sonu sayılır.
_RE_ORD_DOT = re.compile(
    r"(?<![\w.,])(?P<n>\d+)\.(?=[ \t]+(?:[a-zçğıöşü]"
    r"|(?:Sok|Sk|Cad|Cd|Mah|Mh|Blv|Bul|Apt|Bl|Kat|Daire|Sokak|Cadde|Mahalle|Bulvar)(?![\w])))"
)
_RE_ROMAN_ORD = re.compile(r"(?<![\w.'])(?P<r>[IVX]{1,7})\.(?=[ \t]+[^\W\d_])")
_RE_ROMAN_SMALL = re.compile(r"X{0,3}(?:IX|IV|V?I{0,3})")
#: Noktasız Roma rakamı yalnız bu sözcüklerden sonra asıl sayı okunur: "Bölüm II" → "Bölüm iki".
_RE_ROMAN_CARDINAL = re.compile(
    r"(?P<pre>(?<![\w])(?i:bölüm|kısım|cilt|sezon|sayı|ünite|kitap|perde|aşama|seviye|faz|madde)[ \t]+)"
    r"(?P<r>[IVX]{1,7})(?![\w.])"
)
_ROMAN_VAL = {"I": 1, "V": 5, "X": 10}


def _roman_value(r: str) -> int:
    total = 0
    for i, c in enumerate(r):
        v = _ROMAN_VAL[c]
        total += -v if i + 1 < len(r) and _ROMAN_VAL[r[i + 1]] > v else v
    return total


def _roman_ord_sub(m: re.Match) -> str:
    r = m.group("r")
    if not _RE_ROMAN_SMALL.fullmatch(r):
        return m.group(0)
    return tr_ordinal(_roman_value(r))


def _stage_ordinals(t: str) -> str:
    """3. sınıf → 'üçüncü sınıf', 1'inci → 'birinci', II. Dünya Savaşı → 'ikinci Dünya Savaşı' (I–XXXIX)."""
    t = _RE_ORD_SUFFIX.sub(lambda m: tr_ordinal(int(m.group("n"))) + m.group("rest"), t)
    t = _RE_ORD_DOT.sub(lambda m: tr_ordinal(int(m.group("n"))), t)
    t = _RE_ROMAN_CARDINAL.sub(
        lambda m: m.group("pre") + tr_int_to_words(_roman_value(m.group("r")))
        if _RE_ROMAN_SMALL.fullmatch(m.group("r")) else m.group(0), t)
    return _RE_ROMAN_ORD.sub(_roman_ord_sub, t)


# =============================================================================
# 17. AŞAMA: BİRİMLER (derece, çarpanlar, MS/MÖ dahil)
# =============================================================================

def _unit_alternation() -> str:
    alts = []
    for key in sorted(_UNITS, key=len, reverse=True):
        alts.append(f"(?i:{re.escape(key)})" if _UNITS[key][1] else re.escape(key))
    return "|".join(alts)


_UNIT_ALT = _unit_alternation()
_UNIT_EXACT = {k: w for k, (w, ci) in _UNITS.items() if not ci}
_UNIT_FOLDED = {_fold(k): w for k, (w, ci) in _UNITS.items() if ci}
_NUM_START = r"(?:(?<=[xX×])|(?<![\w.,]))"          # "120x60cm" boyutlarında da başlar
_RE_UNIT = re.compile(rf"{_NUM_START}(?P<num>{_NUMV})\s?(?P<unit>{_UNIT_ALT})(?![\w²³]){_SUF}")
_RE_UNIT_AHEAD = re.compile(rf"\s?(?:{_UNIT_ALT}|°|%)(?![\w²³])")
_RE_DEGREE = re.compile(rf"{_NUM_START}(?P<num>{_NUMV})\s?°\s?(?P<cf>[CcFf](?![\w]))?{_SUF}")
_RE_MULTIPLIER = re.compile(
    rf"(?<![\w.,])(?P<num>\d+(?:[.,]\d+)?)(?:(?P<k>[kK])|(?P<mil>M)|\s?(?P<w>mn|mlr|mly|bn))(?![\w]){_SUF}"
)
_RE_ERA = re.compile(r"(?<![\w.])(?P<era>MS|MÖ|M\.S\.|M\.Ö\.)\s?(?=\d)")


def _unit_follows(s: str, pos: int) -> bool:
    """pos konumundan sonra bir birim/yüzde/derece geliyor mu (sayı-tarih-saat ayrımı için)."""
    return _RE_UNIT_AHEAD.match(s, pos) is not None


def _unit_sub(m: re.Match) -> str:
    u = m.group("unit")
    word = _UNIT_EXACT.get(u) or _UNIT_FOLDED.get(_fold(u))
    if word is None:
        return m.group(0)
    return f"{m.group('num')} {_with_suffix(word, m.group('suf'))}"


def _degree_sub(m: re.Match) -> str:
    word = "fahrenhayt derece" if m.group("cf") in ("F", "f") else "derece"
    return f"{m.group('num')} {_with_suffix(word, m.group('suf'))}"


def _multiplier_sub(m: re.Match) -> str:
    if m.group("k") == "K" and m.group("num") in ("4", "8"):
        return m.group(0)                                     # 4K / 8K çözünürlüktür (kısaltma sözlüğü okur)
    if m.group("k"):
        word = "bin"
    elif m.group("mil") or m.group("w") == "mn":
        word = "milyon"
    else:
        word = "milyar"
    return f"{m.group('num')} {_with_suffix(word, m.group('suf'))}"


def _stage_units(t: str) -> str:
    """5 km → '5 kilometre' (sayı sonra okunur), 25°C → '25 derece', 10K → '10 bin', MS 500 → 'milattan sonra 500'."""
    t = _RE_ERA.sub(lambda m: "milattan sonra " if "S" in m.group("era") else "milattan önce ", t)
    t = _RE_DEGREE.sub(_degree_sub, t)
    t = _RE_MULTIPLIER.sub(_multiplier_sub, t)
    return _RE_UNIT.sub(_unit_sub, t)


# =============================================================================
# 18. AŞAMA: NOKTALI KISALTMALAR
# =============================================================================

_ABBR_COMBOS = [
    (re.compile(r"(?<![\w.])Arş\.\s*Gör\."), "araştırma görevlisi"),
    (re.compile(r"(?<![\w.])Öğr\.\s*Gör\."), "öğretim görevlisi"),
    (re.compile(r"(?<![\w.])Öğr\.\s*Üyesi"), "öğretim üyesi"),
    (re.compile(r"(?<![\w.])Yrd\.\s*Doç\."), "yardımcı doçent"),
]
_RE_LABEL_COLON = re.compile(r"(?<![\w.])(?P<w>No|NO|no|Tel|TEL|tel|Fax|FAX|Faks|FAKS|faks)[ \t]*:[ \t]*")
_LABELS = {"no": "numara ", "tel": "telefon ", "fax": "faks ", "faks": "faks "}
_RE_ABBR = re.compile(r"(?<![\w.])(?P<w>[^\W\d_]+(?:\.[^\W\d_]+)*)\.(?=[\s,;:!?\"'\-]|$|[^\W_])")
_RE_NEXT_DIGIT = re.compile(r"[ \t]*\d")
_RE_NEXT_NAME = re.compile(r"[ \t]*[A-ZÇĞİÖŞÜ]")
_RE_NEXT_UPPER = re.compile(r"\s+[A-ZÇĞİÖŞÜ]")
_RE_PREV_WORD = re.compile(r"[^\W\d_]\.?[ \t]+$")       # aynı satırda önünde bir sözcük/kısaltma var mı


_TITLE_ABBREVS = {"dr", "prof", "doç", "av", "sn", "uzm", "dt", "ecz", "müh", "yrd", "hz", "opr"}


def _abbr_compound(w: str) -> str | None:
    """Boşluksuz yazılmış bileşikler: 'Ltd.Şti' → 'limited şirketi', 'Prof.Dr' → 'profesör doktor',
    'Dr.Ayşe' → 'doktor Ayşe.' (son nokta adın cümle noktasıdır)."""
    parts = w.split(".")
    keys = [tr_lower(p) for p in parts]
    if all(k in TR_ABBREV for k in keys):
        return " ".join(TR_ABBREV[k] for k in keys)
    if keys[0] in _TITLE_ABBREVS and parts[1][:1].isupper():
        return f"{TR_ABBREV[keys[0]]} {'.'.join(parts[1:])}."
    return None


def _abbr_sub(m: re.Match) -> str:
    w = m.group("w")
    key = tr_lower(w)
    exp = TR_ABBREV.get(key)
    s, end = m.string, m.end()
    glue = " " if end < len(s) and s[end].isalnum() else ""     # "Dr.Ayşe" → "doktor Ayşe"
    if exp is None:
        if "." in w and (comp := _abbr_compound(w)) is not None:
            return comp + glue
        return m.group(0)
    cond = _ABBREV_COND.get(key)
    digit_next = _RE_NEXT_DIGIT.match(s, end) is not None
    capitalized = w[0].isupper() and (len(w) == 1 or w[1:] != tr_upper(w[1:]))    # "Cd" evet, "CD" hayır
    if cond == "digit" and not digit_next:
        return m.group(0)
    if cond == "cap" and not capitalized:
        return m.group(0)
    if cond == "upper" and w != tr_upper(w):
        return m.group(0)
    if cond == "capdigit" and not (capitalized or digit_next):
        return m.group(0)
    if cond == "title" and not (w[0].isupper() and _RE_NEXT_NAME.match(s, end)):
        return m.group(0)
    if cond == "md":
        exp = "madde" if digit_next else "müdür"
    if cond == "yrd" and _RE_PREV_WORD.search(s, 0, m.start()):
        exp = "yardımcısı"                                    # "Gn. Md. Yrd." → "genel müdür yardımcısı"
    keep = False
    if key in _ABBREV_KEEP_PERIOD:
        rest = s[end:]
        if not rest.strip() or rest.lstrip(" \t").startswith("\n"):
            keep = True
        elif key in _ABBREV_SENTENCE_FINAL and _RE_NEXT_UPPER.match(rest):
            keep = True
    return exp + ("." if keep else "") + glue


def _stage_abbreviations(t: str) -> str:
    """Dr. → 'doktor', vb. → 've benzeri', A.Ş. → 'anonim şirketi', No: 5 → 'numara 5', D. 5 → 'daire 5'."""
    for rx, rep in _ABBR_COMBOS:
        t = rx.sub(rep, t)
    t = _RE_LABEL_COLON.sub(lambda m: _LABELS[tr_lower(m.group("w"))], t)
    return _RE_ABBR.sub(_abbr_sub, t)


# =============================================================================
# 19. AŞAMA: ARALIK VE MATEMATİK
# =============================================================================

_RE_HASHNUM = re.compile(r"#\s?(?=\d)")
_RE_EQUATION = re.compile(
    rf"(?<![\w.,])-?{_NUMV}(?:\s?[-+xX×*/÷:]\s?-?{_NUMV})*\s?=\s?-?{_NUMV}(?:\s?[-+xX×*/÷]\s?-?{_NUMV})*(?![\w])"
)
_RE_EQ_TOKEN = re.compile(rf"{_NUMV}|[-+xX×*/÷:=]")
_EQ_OPS = {"-": "eksi", "+": "artı", "x": "çarpı", "X": "çarpı", "×": "çarpı", "*": "çarpı", "/": "bölü",
           "÷": "bölü", ":": "bölü", "=": "eşittir"}
_RE_COMPARE = re.compile(r"(?<![-=<>!])\s*(<=|>=|!=|≤|≥|≠|<|>)\s*(?=-?\d)")      # "->" ok değildir
_CMP_WORDS = {"<": "küçüktür", ">": "büyüktür", "<=": "küçük eşittir", "≤": "küçük eşittir",
              ">=": "büyük eşittir", "≥": "büyük eşittir", "!=": "eşit değildir", "≠": "eşit değildir"}
_RE_MULT = re.compile(rf"(?<![\w.,]){_NUMV}(?:\s?[xX×*]\s?{_NUMV})+(?![\w]|[.,]\d)")
_RE_TIMES = re.compile(r"(?<![\w.,])(?P<n>\d+)[xX×](?![\w])")
_RE_FRACTION = re.compile(rf"(?<![\w./,])(?P<a>\d+)/(?P<b>\d+)(?![\w/]|[.,]\d){_SUF}")
_RE_PLUS = re.compile(rf"(?<![\w.,]){_NUMV}(?:\s?\+\s?{_NUMV})+(?![\w]|[.,]\d)")
_RE_RANGE = re.compile(rf"(?<![\w.,\-])(?P<a>{_NUMV})\s?[-–]\s?(?P<b>{_NUMV})(?![\w]|[.,]\d){_SUF}")
_RE_RATIO = re.compile(r"(?<![\w:.,])(?P<a>\d+):(?P<b>\d+)(?![\w:]|[.,]\d)")
_RE_NEGATIVE = re.compile(r"(?<![^\s(\[{,;:\"'/=])-(?=\d)")
_FRACTION_SPECIAL = {(1, 2): "yarım", (1, 4): "çeyrek", (7, 24): "yedi yirmi dört", (24, 7): "yirmi dört yedi"}


def _equation_sub(m: re.Match) -> str:
    out, expect_num = [], True
    for tok in _RE_EQ_TOKEN.findall(m.group(0)):
        if tok[0].isdecimal():
            out.append(_read_numeric(tok))
            expect_num = False
        elif tok == "-" and expect_num:
            out.append("eksi")                                # işaret: = -3
        else:
            out.append(_EQ_OPS[tok])
            expect_num = True
    return " ".join(out)


def _fraction_sub(m: re.Match) -> str:
    a, b = int(m.group("a")), int(m.group("b"))
    suf = m.group("suf")
    if (a, b) == (1, 2) and suf:
        return attach_suffix("yarı", suf)                     # 1/2'si → yarısı
    if (a, b) in _FRACTION_SPECIAL:
        words = _FRACTION_SPECIAL[(a, b)]
    elif b and a < b:
        den = tr_int_to_words(b)
        words = f"{den}{locative_suffix(den)} {tr_int_to_words(a)}"     # 3/4 → dörtte üç
    else:
        words = f"{tr_int_to_words(a)} bölü {tr_int_to_words(b)}"      # 10/2 → on bölü iki
    return _with_suffix(words, suf)


def _range_sub(m: re.Match) -> str:
    a, b = m.group("a"), m.group("b")
    words = _read_numeric(a) + _range_sep(a, b) + _read_numeric(b)
    return _with_suffix(words, m.group("suf"))


def _stage_math(t: str) -> str:
    """5x3 → 'beş çarpı üç', 5-3=2 → '… eksi … eşittir …', 3/4 → 'dörtte üç',
    3-4 kişi → 'üç dört kişi', -5 → 'eksi beş'."""
    t = _RE_HASHNUM.sub("numara ", t)
    t = _RE_EQUATION.sub(_equation_sub, t)
    t = _RE_COMPARE.sub(lambda m: f" {_CMP_WORDS[m.group(1)]} ", t)
    t = _RE_MULT.sub(lambda m: " çarpı ".join(_read_numeric(n) for n in re.split(r"\s?[xX×*]\s?", m.group(0))), t)
    t = _RE_TIMES.sub(lambda m: f"{m.group('n')} kat", t)
    t = _RE_FRACTION.sub(_fraction_sub, t)
    t = _RE_PLUS.sub(lambda m: " artı ".join(_read_numeric(n) for n in re.split(r"\s?\+\s?", m.group(0))), t)
    t = _RE_RANGE.sub(_range_sub, t)
    t = _RE_RATIO.sub(lambda m: f"{attach_suffix(tr_int_to_words(int(m.group('a'))), 'e')} "
                                f"{tr_int_to_words(int(m.group('b')))}", t)
    return _RE_NEGATIVE.sub("eksi ", t)


# =============================================================================
# 20. AŞAMA: BİNLİK / ONDALIK / KALAN SAYILAR (+ kesmeli ve bitişik ekler)
# =============================================================================

_RE_VERSION = re.compile(r"(?<![\w.])[vV](?P<v>\d+(?:\.\d+)*)(?![\w])")
_RE_NUMBER = re.compile(
    rf"(?<![\w.,])(?P<num>{_NUMV})"
    r"(?:'(?P<suf>[^\W\d_]+)|(?P<glued>[a-zçğıöşü]*[aeıioöuü][a-zçğıöşü]*))?(?![\w])"
)
_RE_ANY_DIGITS = re.compile(r"\d+")


def _number_sub(m: re.Match) -> str:
    return _with_suffix(_read_numeric(m.group("num")), m.group("suf") or m.group("glued"))


def _stage_numbers(t: str) -> str:
    """1.250.000 → 'bir milyon iki yüz elli bin', 2,5 → 'iki buçuk', 2024'te → 'iki bin yirmi dörtte'."""
    t = _RE_VERSION.sub(lambda m: "versiyon " + _read_numeric(m.group("v")), t)
    return _RE_NUMBER.sub(_number_sub, t)


def _stage_leftover_digits(t: str) -> str:
    """Güvenlik ağı: harfe yapışık kalan rakamlar (iPhone15) da okunur; modele hiç rakam gitmez.

    Kısaltma aşamasından SONRA çalışır ki 4K, 5G, MP3, A4 gibi biçimler bütün olarak okunabilsin.
    """
    return _RE_ANY_DIGITS.sub(lambda m: f" {read_number_tr(m.group(0))} ", t)


# =============================================================================
# 21. AŞAMA: HARF HARF KISALTMALAR
# =============================================================================

_RE_WORD_TOKEN = re.compile(r"(?<![\w'.])(?P<w>[^\W_]+)(?:'(?P<suf>[^\W\d_]+))?(?![\w])")


def _acronym_sub(m: re.Match) -> str:
    rep = _acronym_reading(m.group("w"))
    return m.group(0) if rep is None else _with_suffix(rep, m.group("suf"))


def _stage_acronyms(t: str) -> str:
    """ABD → 'a be de', KDV'si → 'ka de vesi', SMS → 'es em es', NATO → 'nato'; ARTIK/STOK gibi sözcüklere dokunmaz."""
    return _RE_WORD_TOKEN.sub(_acronym_sub, t)


# =============================================================================
# 22. AŞAMA: SEMBOLLER
# =============================================================================

_RE_SLASH_WORDS = re.compile(r"(?<=[^\W\d_])[ \t]?/[ \t]?(?=[^\W\d_])")
_RE_ARROWS = re.compile(r"[ \t]*(?:<?-+>|<-+|=>|<=>|[→⇒➔➜←↑↓↔|])[ \t]*")      # ok ve ayraçlar → duraklama


def _stage_symbols(t: str) -> str:
    """& → 've', @ → 'et', #etiket → 'etiket', ~ → 'yaklaşık', = → 'eşittir', kadın/erkek → 'kadın, erkek'."""
    t = re.sub(r"\s*&\s*", " ve ", t)
    t = re.sub(r"(?i)(?<![\w])ve\s*/\s*veya(?![\w])", "ve veya", t)
    t = _RE_SLASH_WORDS.sub(", ", t)
    t = t.replace("/", " ")
    t = re.sub(r"#(?=[^\W\d_])", "", t)
    t = re.sub(r"~\s*", " yaklaşık ", t)
    t = _RE_ARROWS.sub(", ", t)                      # "A -> B" ("=>" eşittir sayılmasın diye "="den önce)
    t = re.sub(r"\s*=\s*", " eşittir ", t)
    for sym, word in TR_SYMBOLS.items():
        if sym in t:
            t = t.replace(sym, word)
    return re.sub(r"[#*_\\^<>×]", " ", t)


# =============================================================================
# 23. AŞAMA: NOKTALAMA TEMİZLİĞİ
# =============================================================================

_RE_MISSING_SPACE = re.compile(r"(?<=[a-zçğıöşü]{2})([.!?,])(?=[A-ZÇĞİÖŞÜ][a-zçğıöşü])")


def _stage_cleanup(t: str) -> str:
    """Fazla noktalama, boşluk ve satır başı/sonu duraklama işaretlerini toplar."""
    t = re.sub(r"[!?]{2,}", lambda m: "?" if "?" in m.group(0) else "!", t)   # "!!!" → "!", "!?!" → "?"
    t = re.sub(r"\.{4,}", "...", t)
    t = re.sub(r"\s*,\s*,+", ",", t)                 # ardışık virgül
    t = re.sub(r"([.!?])\s*,", r"\1", t)             # "?," → "?"
    t = re.sub(r",\s*([.!?])", r"\1", t)             # ",." → "."
    t = re.sub(r"\s+([,.!?;:])", r"\1", t)
    t = _RE_MISSING_SPACE.sub(r"\1 ", t)             # "Geldim.Sonra" → "Geldim. Sonra"
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"(?m)^[ \t]*[,;:][ \t]*", "", t)     # satır başında kalan duraklama
    t = re.sub(r"(?m)[ \t]*,[ \t]*$", "", t)         # satır sonunda kalan virgül
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


# =============================================================================
# 24. GİRİŞ NOKTALARI
# =============================================================================

def normalize_tr(text: str) -> str:
    """Türkçe kurallarını sırayla uygular (ön temizlik ve okunuş sözlüğü `normalize` içindedir)."""
    t = _stage_phones(text)
    t = _stage_urls(t)
    t = _stage_money(t)
    t = _stage_percent(t)
    t = _stage_dates(t)
    t = _stage_times(t)
    t = _stage_ordinals(t)
    t = _stage_units(t)
    t = _stage_abbreviations(t)
    t = _stage_math(t)
    t = _stage_numbers(t)
    t = _stage_acronyms(t)
    t = _stage_leftover_digits(t)
    return _stage_symbols(t)


def normalize_generic(text: str, lang: str) -> str:
    """Türkçe dışı diller: num2words destekliyorsa sayıları yazıya çevirir."""
    t = text
    t = re.sub(r"%\s*(\d+)", lambda m: m.group(1) + " percent" if lang == "en" else m.group(0), t)
    t = re.sub(r"\b(\d+)[.,](\d+)\b",
               lambda m: f"{_n2w(int(m.group(1)), lang)} point {_n2w(int(m.group(2)), lang)}" if lang == "en" else m.group(0), t)
    t = re.sub(r"\b\d+\b", lambda m: _n2w(int(m.group(0)), lang), t)
    return t


def normalize(text: str, lang: str = "tr") -> str:
    """Dile göre normalize eder, fazla noktalama ve emojileri temizler."""
    if not text:
        return ""
    t = _stage_preclean(text)
    if lang == "tr":
        t = _stage_phones(t)            # "0 (532) …" parantezler duraklamaya dönmeden önce
        t = _stage_urls(t)              # okunuş sözlüğü alan adını değiştirmeden önce ("claude.ai")
    t = _stage_structure(t)
    t = apply_pronunciations(t, lang)
    t = normalize_tr(t) if lang == "tr" else normalize_generic(t, lang)
    return _stage_cleanup(t)
