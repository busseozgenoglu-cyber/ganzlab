"""Seslendirme stilleri (ön ayarlar): sohbet, anlatıcı, haber, reklam, masal…

Bir stil; varsayılan duyguyu, üretim parametrelerini (exaggeration / cfg_weight / temperature), tempoyu, duraklama
çarpanını, konuşma dili seviyesini, nefesleri ve noktalama/otomatik duygu davranışını birlikte belirler.
İstekte bir alan açıkça verilirse kullanıcının değeri, verilmezse (None) stilin değeri geçerlidir: `apply_style`.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from .emotion import fold_ascii
from .emotion import resolve as resolve_emotion
from .tr import tr_lower

COLLOQUIAL_LEVELS = ("off", "light", "full")
DEFAULT_STYLE = "sohbet"

# apply_style çıktısındaki alanlar (sıra sabit)
STYLE_FIELDS = ("emotion", "exaggeration", "cfg_weight", "temperature", "speed", "pause_scale",
                "colloquial", "breaths", "punctuation_emotion", "auto_emotion")
_FLOAT_FIELDS = ("exaggeration", "cfg_weight", "temperature", "speed", "pause_scale")
_BOOL_FIELDS = ("breaths", "punctuation_emotion", "auto_emotion")


@dataclass
class Style:
    name: str
    label: str
    description: str
    emotion: str | None = None
    exaggeration: float = 0.5
    cfg_weight: float = 0.45
    temperature: float = 0.8
    speed: float = 1.0
    pause_scale: float = 1.0
    colloquial: str = "light"
    breaths: bool = True
    punctuation_emotion: bool = True
    auto_emotion: bool = False
    aliases: list[str] = field(default_factory=list)


STYLES: dict[str, Style] = {s.name: s for s in [
    Style("sohbet", "Sohbet", "Varsayılan: doğal, samimi, konuşur gibi.",
          exaggeration=0.55, cfg_weight=0.45, temperature=0.8, speed=1.0, pause_scale=1.0,
          colloquial="light", breaths=True, punctuation_emotion=True, auto_emotion=False,
          aliases=["conversational", "chat", "casual", "youtube", "sosyal medya", "social", "vlog", "varsayılan",
                   "default", "doğal"]),
    Style("anlatıcı", "Anlatıcı", "Hikâye ve sesli anlatım için ölçülü, akıcı bir anlatıcı sesi.",
          exaggeration=0.45, cfg_weight=0.5, temperature=0.75, speed=0.97, pause_scale=1.2, colloquial="off",
          aliases=["narrator", "narration", "storyteller", "anlatım", "hikâye", "hikaye", "öykü"]),
    Style("haber", "Haber", "Haber spikeri gibi net, tarafsız ve tempolu okuma.",
          exaggeration=0.4, cfg_weight=0.55, temperature=0.7, speed=1.0, pause_scale=0.9, colloquial="off",
          breaths=True, punctuation_emotion=False,
          aliases=["news", "newscaster", "anchor", "spiker", "haber spikeri", "bülten", "bulletin"]),
    Style("reklam", "Reklam", "Enerjik tanıtım ve kampanya seslendirmesi.",
          emotion="heyecanlı", exaggeration=0.8, cfg_weight=0.35, temperature=0.9, speed=1.04, pause_scale=0.8,
          colloquial="light",
          aliases=["ad", "ads", "advert", "advertisement", "commercial", "promo", "tanıtım", "kampanya"]),
    Style("masal", "Masal", "Çocuklara masal okur gibi sıcak, yavaş ve canlı.",
          emotion="samimi", exaggeration=0.65, cfg_weight=0.4, temperature=0.85, speed=0.93, pause_scale=1.35,
          colloquial="off",
          aliases=["fairy tale", "fairytale", "bedtime story", "çocuk masalı", "masal anlatıcısı", "ninni"]),
    Style("podcast", "Podcast", "Rahat, sohbet havasında uzun konuşma.",
          exaggeration=0.5, cfg_weight=0.45, temperature=0.8, speed=0.98, pause_scale=1.1, colloquial="full",
          aliases=["podkast", "radyo", "radio", "talk show", "söyleşi"]),
    Style("belgesel", "Belgesel", "Ciddi, derin ve ağırbaşlı belgesel anlatımı.",
          emotion="ciddi", exaggeration=0.4, cfg_weight=0.55, temperature=0.7, speed=0.95, pause_scale=1.3,
          colloquial="off",
          aliases=["documentary", "docu", "doku", "belgesel anlatımı"]),
    Style("eğitim", "Eğitim", "Ders anlatır gibi açık, sabırlı ve anlaşılır.",
          exaggeration=0.45, cfg_weight=0.5, temperature=0.75, speed=0.96, pause_scale=1.15, colloquial="light",
          punctuation_emotion=True,
          aliases=["education", "educational", "ders", "lesson", "tutorial", "öğretici", "e-learning"]),
    Style("sesli-kitap", "Sesli kitap", "Uzun metinleri yormadan, dengeli ve tutarlı okur.",
          exaggeration=0.4, cfg_weight=0.5, temperature=0.7, speed=0.95, pause_scale=1.25, colloquial="off",
          breaths=True,
          aliases=["audiobook", "audio book", "kitap", "book", "uzun okuma", "roman"]),
    Style("duygusal", "Duygusal", "Dramatik ve duygu yüklü; duyguyu cümle içeriğinden kendisi seçer.",
          exaggeration=0.75, cfg_weight=0.35, temperature=0.9, speed=0.95, pause_scale=1.3, colloquial="light",
          auto_emotion=True,
          aliases=["emotional", "dramatic", "dramatik", "drama", "duygu yüklü"]),
    Style("müşteri-hizmeti", "Müşteri hizmeti", "Nazik ve yardımsever; çağrı merkezi ve karşılama mesajları için.",
          emotion="nazik", exaggeration=0.45, cfg_weight=0.5, speed=0.98, pause_scale=1.05, colloquial="off",
          aliases=["support", "customer support", "customer service", "müşteri hizmetleri", "çağrı merkezi",
                   "call center", "santral", "ivr"]),
    Style("spor-spikeri", "Spor spikeri", "Maç anlatır gibi heyecanlı ve hızlı.",
          emotion="heyecanlı", exaggeration=0.85, cfg_weight=0.3, temperature=0.95, speed=1.08, pause_scale=0.7,
          colloquial="light",
          aliases=["sports", "sport", "sports commentator", "commentator", "spor", "maç", "maç anlatımı",
                   "spor anlatıcısı"]),
]}


def _key(s: str) -> str:
    return re.sub(r"[\s_\-]+", " ", s).strip()


# ad → stil; önce asıl adlar, sonra etiketler, en son eş anlamlılar (biri diğerini ezemez)
_INDEX: dict[str, str] = {}
_FOLD_INDEX: dict[str, str] = {}
for _group in ([(s.name, s.name) for s in STYLES.values()],
               [(s.label, s.name) for s in STYLES.values()],
               [(a, s.name) for s in STYLES.values() for a in s.aliases]):
    for _text, _name in _group:
        _k = _key(tr_lower(_text))
        _INDEX.setdefault(_k, _name)
        _FOLD_INDEX.setdefault(fold_ascii(_k), _name)


def resolve_style(name: str | Style | None) -> Style | None:
    """Stil adı, etiketi ya da eş anlamlısından stil bulur: "ANLATICI", "Sesli Kitap", "sesli_kitap",
    "egitim", "narrator", "audiobook"… Bulamazsa None."""
    if isinstance(name, Style):
        return name
    if name is None or not str(name).strip():
        return None
    key = _key(tr_lower(str(name)).replace("i̇", "i"))
    if key in _INDEX:
        return STYLES[_INDEX[key]]
    n = _FOLD_INDEX.get(fold_ascii(key))       # "AUDIOBOOK" → "audıobook" → "audiobook", "egitim" → "eğitim"
    return STYLES[n] if n else None


def style_catalog() -> list[dict]:
    """Arayüz/health için tüm stiller: name, label, description + tüm parametreler ve eş anlamlılar."""
    return [asdict(s) for s in STYLES.values()]


_TRUE_WORDS = ("1", "true", "on", "yes", "evet", "acik")
_FALSE_WORDS = ("0", "false", "off", "no", "hayir", "kapali", "")


def _plain(value: object) -> str:
    """Karşılaştırma için sade biçim: Türkçe küçük harf + ASCII ("LIGHT" → "light", "AÇIK" → "acik")."""
    return fold_ascii(tr_lower(str(value).strip()))


def _as_colloquial(value: object) -> str:
    if isinstance(value, bool):
        return "light" if value else "off"
    s = _plain(value)
    if s in COLLOQUIAL_LEVELS:
        return s
    if s in _TRUE_WORDS:
        return "light"
    if s in _FALSE_WORDS:
        return "off"
    raise ValueError(f"Geçersiz konuşma dili seviyesi: {value!r} (off | light | full)")


def _as_bool(value: object) -> bool:
    if isinstance(value, str):
        s = _plain(value)
        if s in _TRUE_WORDS:
            return True
        if s in _FALSE_WORDS:
            return False
    return bool(value)


def _as_float(key: str, value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError(f"Geçersiz sayı: {key}={value!r}") from None


def apply_style(style: Style | str | None, overrides: dict | None = None) -> dict:
    """Stilin değerlerini temel alır, `overrides` içindeki None olmayan alanları üstüne yazar ve düz bir sözlük
    döndürür: emotion, exaggeration, cfg_weight, temperature, speed, pause_scale, colloquial, breaths,
    punctuation_emotion, auto_emotion.

    style None ise sözleşmedeki varsayılanlar (Style alan varsayılanları) temel alınır; bilinmeyen stil adı
    ValueError verir. colloquial bool da olabilir (True → "light", False → "off"). emotion profil adına çevrilir
    ("Üzgün" → "üzgün", "normal" → None); tanınmayan duygu adı olduğu gibi bırakılır (doğrulama API katmanında).
    STYLE_FIELDS dışındaki anahtarlar yok sayılır."""
    if style is None or (isinstance(style, str) and not style.strip()):
        base = Style(name="", label="", description="")
    else:
        found = resolve_style(style)
        if found is None:
            raise ValueError(f"Bilinmeyen stil: {style!r}. Seçenekler: {', '.join(STYLES)}")
        base = found
    out: dict = {f: getattr(base, f) for f in STYLE_FIELDS}
    for key, value in (overrides or {}).items():
        if key in out and value is not None:
            out[key] = value
    for key in _FLOAT_FIELDS:
        out[key] = _as_float(key, out[key])
    for key in _BOOL_FIELDS:
        out[key] = _as_bool(out[key])
    out["colloquial"] = _as_colloquial(out["colloquial"])
    emo = out["emotion"]
    if isinstance(emo, str):
        prof = resolve_emotion(emo) if emo.strip() else None
        if prof is not None:
            out["emotion"] = None if prof.name == "normal" else prof.name
        else:
            out["emotion"] = emo.strip() or None
    return out
