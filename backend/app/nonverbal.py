"""Gerçek sözsüz tepki kayıtları — gülme, kahkaha, iç çekme, "hmm"… (v4 sözleşmesi, bölüm 2).

Model "[gülme]" etiketini ancak "Hahaha!" diye okuyabiliyor; bu yapay duyuluyor. Bu modül kullanıcının KENDİ gerçek
gülmesini, iç çekmesini, "hmm"ını kullanılabilir hâle getirir:

1. Kayıt (API `POST /api/voices/{id}/nonverbal`): `sample_key(tag)` ile anahtar bulunur, `prepare_nonverbal()`
   kaydı mono/24 kHz'e çevirir, sessizliği kırpar, en fazla 3 sn'lik en enerjik bölümü seçer, seviyeler ve yazar.
   Veritabanında `voice_samples.emotion` sütununa `db_key(anahtar)` ("nv:gülme") ile saklanır.
2. Üretim (motor): metindeki sözsüz etiket için ses kaydı varsa `render_nonverbal()` kaydı her seferinde biraz farklı
   sunar (seviye ±1.5 dB, tempo ±3 %, perde ±0.3 yarım ton; seed ile belirlenimci) → aynı gülme iki kez birebir aynı
   duyulmaz. `level_match()` parçayı komşu konuşmanın 4 dB altına oturtur; motor onu dizinin içine parça olarak koyar.
   Kayıt yoksa `fallback_text()` modelin okuyacağı ünlemi verir (emotion.NONVERBAL'dan). Örnek akış:

       key = sample_key(seg.nonverbal)                     # None → kaydedilebilir karşılığı yok
       yol = ses_ornekleri.get(db_key(key)) if key else None
       if yol: parca = level_match(render_nonverbal(yol, sr, seed=s), sr, active_rms_db(komsu, sr))
       else:   metne fallback_text(seg.nonverbal) eklenir

Tüm küçük harf dönüşümleri `tr_lower` iledir (str.lower() İ/I'yı bozar). `emotion` modülü yalnızca çağrı anında içe
aktarılır; emotion.py ileride bu modülü içe aktarsa bile döngüsel içe aktarma sorunu çıkmaz.
"""
from __future__ import annotations

import functools
import logging
import math
import re
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path

import numpy as np
import soundfile as sf

from . import audio
from .tr import tr_capitalize, tr_lower

log = logging.getLogger("sesklon.nonverbal")

__all__ = [
    "NONVERBAL_KEYS", "NONVERBAL_SCRIPTS", "NONVERBAL_LABELS", "NONVERBAL_ALIASES", "DB_PREFIX",
    "sample_key", "prepare_nonverbal", "render_nonverbal", "db_key", "is_db_key", "key_of_db",
    "nonverbal_catalog", "fallback_text", "level_match", "active_rms_db",
]

# ---------- anahtarlar, yönergeler, eş adlar ----------

# Kaydedilebilir tepkiler (sözleşme sırası). Her anahtar emotion.NONVERBAL'da da vardır (kayıt yoksa okunan ünlem).
NONVERBAL_KEYS: tuple[str, ...] = (
    "gülme", "kahkaha", "kıkırdama", "iç çekme", "hmm", "of", "nefes verir", "öksürür", "boğaz temizler", "esner",
    "ağlar", "şaşırır", "hıh", "mmm", "cık",
)

# Kayıt ekranında gösterilen kısa, sıcak yönergeler (en fazla 3 sn kullanılır; daha uzunu kırpılır).
NONVERBAL_SCRIPTS: dict[str, str] = {
    "gülme": "Komik bir şey hatırla ve içten, doğal bir kahkaha at — 1–3 saniye. Zorlama; kısa bir 'hahaha' bile olur.",
    "kahkaha": "Seni gerçekten güldüren bir anı düşün ve kendini bırak: gür, dolu bir kahkaha — 2–3 saniye. "
               "Ses patlamasın diye mikrofondan bir karış uzaklaş.",
    "kıkırdama": "Gülmemeye çalışırken kaçıveren kısa, kısık bir kıkırdama — 'hihi' ya da 'kıkır kıkır', 1–2 saniye. "
                 "Ağzın yarı kapalı olabilir.",
    "iç çekme": "Yorucu bir günün sonunda koltuğa yeni oturmuşsun gibi derin bir nefes al ve 'ahh' diye yavaşça bırak "
                "— 1–2 saniye. Abartma, hafif olsun.",
    "hmm": "Bir soruyu tartıyormuşsun gibi ağzın kapalı, düşünceli bir 'hmm' — 1 saniye kadar. "
           "Sonu nasıl gelirse öyle bırak.",
    "of": "Canını sıkan küçük bir şeye tepki verir gibi 'offf' de — bıkkın ama sevimli, 1 saniye kadar.",
    "nefes verir": "Rahatlamışsın gibi ağzından sesli bir nefes ver — 'hoff', yarım ile 1,5 saniye arası.",
    "öksürür": "Boğazına bir şey kaçmış gibi bir iki kez doğal öksür — 1 saniye kadar. "
               "Mikrofona doğrudan değil, hafif yana dönerek.",
    "boğaz temizler": "Söze girmeden önceki gibi kısa bir 'ehem' ile boğazını temizle — yarım ile 1 saniye arası.",
    "esner": "Uykun gelmiş gibi doğal bir esneme — 'aaah', 1–2 saniye. Rahat bırak, sonu kendiliğinden sönsün.",
    "ağlar": "Duygulandığın bir anı düşün: kısa, burnunu çeken hafif bir ağlama ya da birkaç kesik hıçkırık — "
             "1–3 saniye. Kendini zorlama.",
    "şaşırır": "Hiç beklemediğin bir haber almışsın gibi içten şaşır: kısa bir 'Aa!' ya da 'Vay!' — 1 saniye kadar.",
    "hıh": "Karşındakini dinlerken onaylar gibi ağzın kapalı, kısa bir 'hı hı' — yarım ile 1 saniye arası.",
    "mmm": "Çok sevdiğin bir tadı alıyormuşsun gibi ağzın kapalı, keyifli bir 'mmm' — 1 saniye kadar.",
    "cık": "'Olmaz' der gibi dilini damağına vurarak iki kez 'cık cık' yap — yarım saniye kadar.",
}

# Arayüz etiketleri (Türkçe, baş harf büyük; fiil anahtarlar ad biçiminde gösterilir).
NONVERBAL_LABELS: dict[str, str] = {
    "gülme": "Gülme", "kahkaha": "Kahkaha", "kıkırdama": "Kıkırdama", "iç çekme": "İç çekme", "hmm": "Hmm",
    "of": "Of", "nefes verir": "Nefes verme", "öksürür": "Öksürük", "boğaz temizler": "Boğaz temizleme",
    "esner": "Esneme", "ağlar": "Ağlama", "şaşırır": "Şaşırma", "hıh": "Hı hı", "mmm": "Mmm", "cık": "Cık cık",
}

# Etiket/eş ad → anahtar. emotion.NONVERBAL'daki, okunuşu bir anahtarınkiyle aynı olan her eş ad burada (testle
# denetlenir); yakın anlamlı olanlar emotion.py'deki kanonik gruplarla aynı kararla eşlenir: "chuckles"/"kıs kıs
# güler" → kıkırdama, "pff"/"pöf" → of, "sobs" → ağlar, "gasps"/"vay"/"wow" → şaşırır, "hı hı"/"hıhı"/"onay" → hıh
# (onay sesi). Kaydedilebilir karşılığı olmayanlar ("tüh", "aman", "şey", dolgu "ııı", "mırıldanır", "inler",
# "hıçkırır", "ıslık", "sniffs"…) eşlenmez: model onları emotion.NONVERBAL'daki ünlemle okur.
NONVERBAL_ALIASES: dict[str, tuple[str, ...]] = {
    "gülme": ("gülme", "güler", "gülüyor", "gülüş", "gülmek", "laughs", "laugh", "laughing", "starts laughing",
              "haha", "hahaha"),
    "kahkaha": ("kahkaha", "kahkaha atar", "kahkaha atma", "kahkahalar", "kahkahayı basar", "laughs hard",
                "laughs harder", "laughing hard", "laughs out loud"),
    "kıkırdama": ("kıkırdama", "kıkırdar", "kıkır kıkır", "kıs kıs güler", "kıs kıs gülme", "giggles", "giggle",
                  "giggling", "hihi", "hihihi", "chuckles", "chuckle", "chuckling", "heh heh", "hehe"),
    "iç çekme": ("iç çekme", "iç çeker", "iç geçirir", "iç geçirme", "sighs", "sigh", "sighing"),
    "hmm": ("hmm", "hm", "düşünür", "düşünme", "thinks", "thinking"),
    "of": ("of", "off", "pff", "pf", "pöf", "puflar", "ugh"),
    "nefes verir": ("nefes verir", "nefes verme", "nefes vermek", "exhales", "exhale", "exhaling"),
    "öksürür": ("öksürür", "öksürük", "öksürme", "coughs", "cough", "coughing"),
    "boğaz temizler": ("boğaz temizler", "boğazını temizler", "boğaz temizleme", "clears throat", "clear throat",
                       "clearing throat", "ehem", "ahem"),
    "esner": ("esner", "esneme", "esniyor", "yawns", "yawn", "yawning"),
    "ağlar": ("ağlar", "ağlıyor", "ağlama", "cries", "cry", "crying", "sobs", "sob", "sobbing"),
    "şaşırır": ("şaşırır", "şaşırma", "vay canına", "vay", "wow", "gasps", "gasp", "gasping", "hah",
                "nefesi kesilir"),
    "hıh": ("hıh", "hı hı", "hıhı", "ıhı", "onay", "uh huh", "mhm", "mm hmm"),
    "mmm": ("mmm", "mm", "lezzet", "yum"),
    "cık": ("cık", "cık cık", "cıkcık", "tsk", "tsk tsk", "tut tut"),
}

DB_PREFIX = "nv:"           # voice_samples.emotion sütununda sözsüz kayıtların öneki ("nv:gülme")

# ---------- ses ayarları ----------

MAX_SECONDS = 3.0           # hazırlanan kaydın en uzun hâli
MIN_SECONDS = 0.15          # bundan kısası "Kayıt çok kısa"
MAX_INPUT_SECONDS = 60.0    # yüklemenin en fazla ilk 60 sn'si incelenir
TRIM_DB = -40.0             # kırpma eşiği (dBFS, 20 ms kare RMS)
TRIM_PAD_MS = 30
PREP_FADE_MS = 15
TARGET_RMS_DB = -22.0
PEAK_DB = -1.0
RENDER_FADE_MS = 10
LEVEL_JITTER_DB = 1.5       # seviye mikro varyasyonu (±dB)
TEMPO_JITTER = 0.03         # tempo mikro varyasyonu (±oran)
PITCH_JITTER_ST = 0.3       # perde mikro varyasyonu (±yarım ton)
NEIGHBOR_OFFSET_DB = -4.0   # gülme konuşmadan biraz kısık durur
MAX_MATCH_GAIN_DB = 20.0    # level_match'in uygulayabileceği en büyük kazanç değişimi
ACTIVE_GATE_DB = 30.0       # etkin RMS: en gür kareden bu kadar kısık kareler sayılmaz
ACTIVE_FLOOR_DB = -70.0     # etkin RMS: bunun altındaki kareler sessizlik
FFMPEG_TIMEOUT_S = 60

_FRAME_MS = 20
_CUT_REL_DB = 25.0          # en gür karenin bu kadar altındaki kare de kesim noktası sayılır
_CUT_NOISE_DB = 3.0         # gürültü tabanının bu kadar üstüne kadar olan kare de kesim noktası sayılır
_MIN_KEEP_RATIO = 0.7       # sessizlikte kesilen bölüm en enerjik pencerenin enerjisinin en az bu kadarını tutmalı
_ALIGN_MS = 300             # yedek yolda sınırı en kısık kareye çekerken aranacak en uzak mesafe
_MIN_FILTER_S = 0.1         # bundan kısa parçalara perde/tempo uygulanmaz (ffmpeg boş çıktı verebiliyor)


# ---------- etiket → anahtar ----------

_WRAP_CHARS = "[](){}*<>«»\"'“”‘’ \t\r\n"
_EDGE_PUNCT = " .!?…,;:"
_SEP_RE = re.compile(r"[_\-]+")
_WS_RE = re.compile(r"\s+")
_LEVEL_SUFFIX_RE = re.compile(r"\s*:\s*[+-]?\d+(?:[.,]\d+)?$")    # "[gülme:2]" → "gülme"
_REPEAT3_RE = re.compile(r"(.)\1{2,}")      # "hmmmm" → "hmm", "offff" → "off"
_REPEAT2_RE = re.compile(r"(.)\1+")         # "cıkk" → "cık"
_LAUGH_RE = re.compile(r"^(?:ha){2,}h?$")   # "hahahaha" → gülme
_GIGGLE_RE = re.compile(r"^(?:hi|he){2,}h?$")   # "hihihi", "hehehe" → kıkırdama
# Anlamı değiştirmeyen niteleyiciler: "[derin bir iç çekme]", "[hafif gülme]", "[laughs softly]", "[öksürük sesi]"
_MOD_PREFIX = frozenset({
    "biraz", "hafif", "hafifçe", "çok", "aşırı", "kısa", "kısaca", "uzun", "derin", "bir", "sessiz", "sessizce",
    "içten", "gür", "kısık", "küçük", "büyük", "a", "soft", "quiet", "loud", "nervous", "deep", "heavy", "light",
    "short", "long", "little", "small", "big", "slight",
})
_MOD_SUFFIX = frozenset({
    "sesi", "sesleri", "softly", "quietly", "loudly", "nervously", "deeply", "heavily", "lightly", "awkwardly",
    "briefly", "slightly", "again",
})


def _em():
    """emotion modülü — çağrı anında içe aktarılır: emotion.py bu modülü (hangi biçimde olursa olsun) içe aktarsa da
    döngü oluşmaz."""
    from . import emotion
    return emotion


def _clean(tag: str) -> str:
    """NFC, sarmalayıcılar ([], (), *) atılır, Türkçe küçük harf, tire/alt çizgi → boşluk, tek boşluk."""
    s = unicodedata.normalize("NFC", tag).strip(_WRAP_CHARS)
    s = tr_lower(s).replace("i\u0307", "i")         # str.lower() ile bozulmuş "İ" (i + birleşik nokta)
    s = _SEP_RE.sub(" ", s)
    return _WS_RE.sub(" ", s).strip()


def _strip_modifiers(s: str) -> str:
    words = s.split(" ")
    while len(words) > 1 and words[0] in _MOD_PREFIX:
        words.pop(0)
    while len(words) > 1 and words[-1] in _MOD_SUFFIX:
        words.pop()
    return " ".join(words)


def _candidates(tag: str) -> list[str]:
    """Sırayla denenecek biçimler: ham, uç noktalaması atılmış, düzey soneki atılmış, niteleyicisiz."""
    raw = _clean(tag)
    base = raw.strip(_EDGE_PUNCT)
    no_level = _LEVEL_SUFFIX_RE.sub("", base).strip(_EDGE_PUNCT)
    out: list[str] = []
    for s in (raw, base, no_level, _strip_modifiers(no_level)):
        if s and s not in out:
            out.append(s)
    return out


@functools.lru_cache(maxsize=1)
def _tables() -> tuple[dict[str, str], dict[str, str], frozenset[str]]:
    """(birebir eş ad → anahtar, ASCII'ye katlanmış eş ad → anahtar, katlanmış duraklama etiketleri). İlk çağrıda
    kurulur (emotion modülü o anda tamamen yüklüdür)."""
    exact: dict[str, str] = {}
    for key in NONVERBAL_KEYS:
        for alias in (key, *NONVERBAL_ALIASES[key]):
            exact.setdefault(_clean(alias), key)
    fold = _em().fold_ascii
    folded: dict[str, str] = {}
    for alias, key in exact.items():
        folded.setdefault(fold(alias), key)
    pauses = {fold(_clean(k)) for k in _em().PAUSE_TAGS}
    pauses |= {fold(_clean(k)) for k, v in _em().NONVERBAL.items() if not v}
    return exact, folded, frozenset(pauses)


def _is_pause(s: str, pause_fold: frozenset[str]) -> bool:
    if s in _em().PAUSE_TAGS or _em().fold_ascii(s) in pause_fold:
        return True
    return _em().timed_pause_ms(s) is not None


def sample_key(tag: str) -> str | None:
    """Etiket ya da eş addan kaydedilebilir tepki anahtarı: "laughs" → "gülme", "Kahkaha Atar" → "kahkaha",
    "kıkırdar" → "kıkırdama", "SIGHS" → "iç çekme", "hmmm" → "hmm", "hıhı" → "hıh", "[derin bir iç çekme]" →
    "iç çekme". Eşleşme yoksa ya da etiket bir duraklamaysa ([nefes], [1.5 sn]…) None.

    Sıra: birebir (Türkçe küçük harf) → harf tekrarı sadeleştirilmiş ("offff") → "hahaha"/"hihihi" kalıpları →
    ASCII karşılığı ("gulme", "ic cekme")."""
    if not isinstance(tag, str) or not tag.strip():
        return None
    cands = _candidates(tag)
    if not cands:
        return None
    exact, folded, pause_fold = _tables()
    if any(_is_pause(c, pause_fold) for c in cands):
        return None
    variants: list[str] = []
    for c in cands:
        for v in (c, _REPEAT3_RE.sub(r"\1\1", c), _REPEAT2_RE.sub(r"\1", c)):
            if v and v not in variants:
                variants.append(v)
    for v in variants:
        if v in exact:
            return exact[v]
    fold = _em().fold_ascii
    for v in variants:
        for compact in (v.replace(" ", ""), fold(v).replace(" ", "")):
            if _LAUGH_RE.match(compact):
                return "gülme"
            if _GIGGLE_RE.match(compact):
                return "kıkırdama"
    for v in variants:
        hit = folded.get(fold(v))
        if hit:
            return hit
    return None


def fallback_text(key: str) -> str:
    """Kayıt yoksa modelin okuyacağı ünlem (emotion.NONVERBAL'dan): "gülme" → "Hahaha!". Eş ad verilirse önce kendi
    okunuşu ("chuckles" → "Heh heh.", "hıhı" → "Hı hı."), yoksa anahtarınki. Tanınmayan etiket → ""."""
    if not isinstance(key, str):
        return ""
    nv = _em().NONVERBAL
    for c in _candidates(key):
        if nv.get(c):
            return nv[c]
    k = sample_key(key)
    return nv.get(k, "") if k else ""


def nonverbal_catalog() -> list[dict]:
    """Arayüz / health için: [{key, label, script, aliases}] (NONVERBAL_KEYS sırasıyla)."""
    return [
        {"key": k, "label": NONVERBAL_LABELS.get(k) or tr_capitalize(k), "script": NONVERBAL_SCRIPTS[k],
         "aliases": list(NONVERBAL_ALIASES[k])}
        for k in NONVERBAL_KEYS
    ]


# ---------- veritabanı anahtarı ----------

def db_key(key: str) -> str:
    """"gülme" → "nv:gülme" (voice_samples.emotion sütunu için). Eş ad da kabul edilir ("laughs" → "nv:gülme"),
    zaten önekliyse aynen döner. Tanınmayan etikette ValueError."""
    raw = key_of_db(key) if is_db_key(key) else key
    k = sample_key(raw) if isinstance(raw, str) else None
    if k is None:
        raise ValueError(f"Bilinmeyen sözsüz tepki: {key!r}. Seçenekler: {', '.join(NONVERBAL_KEYS)}")
    return DB_PREFIX + k


def is_db_key(s: str) -> bool:
    """Sütun değeri sözsüz kayıt mı ("nv:" önekli)? Duygu örnekleri ("mutlu") ve None → False."""
    return isinstance(s, str) and s.startswith(DB_PREFIX) and len(s) > len(DB_PREFIX)


def key_of_db(s: str) -> str:
    """"nv:gülme" → "gülme". Öneksiz değer olduğu gibi döner (duygu örnekleri için güvenli)."""
    return s[len(DB_PREFIX):] if is_db_key(s) else s


# ---------- yardımcı sinyal işlemleri ----------

def _mono(wav: np.ndarray) -> np.ndarray:
    x = np.asarray(wav, dtype=np.float32)
    if x.ndim > 1:
        x = x.mean(axis=1)
    return np.nan_to_num(x.reshape(-1), nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32, copy=False)


def _frame_power(wav: np.ndarray, frame: int) -> np.ndarray:
    """Kare başına ortalama güç (float64); yarım kalan son kare atılır."""
    n = len(wav) // frame
    if n <= 0:
        return np.zeros(0)
    f = np.asarray(wav[: n * frame], dtype=np.float64).reshape(n, frame)
    return np.mean(f * f, axis=1)


def _db_to_power(db: float) -> float:
    return 10.0 ** (db / 10.0)


def _rms(wav: np.ndarray) -> float:
    x = np.asarray(wav, dtype=np.float64)
    return float(np.sqrt(np.mean(x * x))) if x.size else 0.0


def _limit_peak(wav: np.ndarray, peak_db: float = PEAK_DB) -> np.ndarray:
    peak = float(np.max(np.abs(wav))) if wav.size else 0.0
    limit = audio.db_to_amp(peak_db)
    return wav * (limit / peak) if peak > limit else wav


def active_rms_db(wav: np.ndarray, sr: int) -> float:
    """Etkin (sessizlik kapılı) RMS, dBFS: 20 ms karelerden en gür kareye göre 30 dB'den kısık olanlar ve -70 dBFS
    altı atılır, kalanların ortalama gücü alınır. Gülme darbeleri arasındaki boşluklar ya da konuşmadaki duraklamalar
    seviyeyi aşağı çekmez. Boş/sessiz girdi → -inf. Motor komşu konuşmayı da bununla ölçmeli (level_match)."""
    x = _mono(wav)
    if x.size == 0:
        return float("-inf")
    p = _frame_power(x, max(1, int(int(sr) * _FRAME_MS / 1000)))
    if p.size == 0:                                  # tek kareden kısa parça
        p = np.array([np.mean(np.asarray(x, dtype=np.float64) ** 2)])
    floor = max(_db_to_power(ACTIVE_FLOOR_DB), float(p.max()) * _db_to_power(-ACTIVE_GATE_DB))
    act = p[p > floor]
    if act.size == 0:
        return float("-inf")
    return 10.0 * math.log10(float(np.mean(act)))


def _has_sound(wav: np.ndarray, sr: int, threshold_db: float = TRIM_DB) -> bool:
    p = _frame_power(wav, max(1, int(sr * _FRAME_MS / 1000)))
    return bool(p.size) and bool(np.any(p > _db_to_power(threshold_db)))


def _loudest_window(wav: np.ndarray, sr: int, seconds: float) -> np.ndarray:
    """En yüksek RMS enerjili, en fazla `seconds` uzunluğunda ve sınırları sessizliğe denk gelen bölüm.

    1. Kesim adayları: sessiz kareler ile kaydın baş ve sonu. Sessiz = -40 dBFS, en gür karenin 25 dB altı ya da
       gürültü tabanının (karelerin 10. yüzdeliği) 3 dB üstü — hangisi yüksekse; ancak hiçbir zaman en gür karenin
       15 dB altından yukarıda değil (gürültülü kayıtta da boşluklar bulunur). İki aday arasında kalan, uzunluğu sınırı
       aşmayan bölümlerden enerjisi en yüksek olanı seçilir; böylece gülme bir darbenin ortasından kesilmez ve en
       enerjik kısım bölümde kalır.
    2. Bu bölüm, sınırsız en enerjik pencerenin enerjisinin %70'ini tutamıyorsa (ör. hiç boşluk yok, sürekli ses):
       en enerjik pencere alınır, iki sınırı da içeri doğru en çok 300 ms içindeki en kısık kareye çekilir."""
    max_len = int(seconds * sr)
    if len(wav) <= max_len:
        return wav
    frame = max(1, int(sr * _FRAME_MS / 1000))
    e = _frame_power(wav, frame)
    n = e.size
    win = max(1, min(n, max_len // frame))
    c = np.concatenate(([0.0], np.cumsum(e)))
    scores = c[win:] - c[:-win]
    best_plain = float(scores.max())
    peak = float(e.max())
    noise = float(np.percentile(e, 10)) * _db_to_power(_CUT_NOISE_DB)
    cut_thr = max(_db_to_power(TRIM_DB), peak * _db_to_power(-_CUT_REL_DB), min(noise, peak * _db_to_power(-15.0)))
    quiet = np.nonzero(e <= cut_thr)[0]
    starts = np.union1d(quiet, [0])
    ends = np.union1d(quiet, [n - 1])
    j = np.searchsorted(ends, starts + win - 1, side="right") - 1    # her başlangıca sığan en geç bitiş
    ok = j >= 0
    if np.any(ok):
        s_ok, e_ok = starts[ok], ends[j[ok]]
        keep = e_ok >= s_ok
        s_ok, e_ok = s_ok[keep], e_ok[keep]
        if s_ok.size:
            energy = c[e_ok + 1] - c[s_ok]
            b = int(np.argmax(energy))
            if energy[b] >= _MIN_KEEP_RATIO * best_plain:
                return wav[int(s_ok[b]) * frame:(int(e_ok[b]) + 1) * frame]
    # Yedek (boşluksuz, sürekli ses): en enerjik pencere, sınırlar içeride en kısık kareye
    s0 = int(np.argmax(scores))
    e0 = s0 + win
    k = max(1, min(round(_ALIGN_MS / _FRAME_MS), win // 3))
    start_f = s0 + int(np.argmin(e[s0:s0 + k]))
    last = e0 - 1 - int(np.argmin(e[e0 - k:e0][::-1]))
    if last <= start_f:
        start_f, last = s0, e0 - 1
    return wav[start_f * frame:(last + 1) * frame]


# ---------- kayıt hazırlama ----------

def prepare_nonverbal(src: Path, dst: Path, sr: int = audio.TARGET_SR) -> float:
    """Yüklenen tepki kaydını hazırlar ve dst'ye WAV yazar; süreyi (sn) döndürür.

    audio.to_wav ile mono sr'ye çevirir (ffmpeg yoksa librosa), DC'yi çıkarır, -40 dB eşikle baş/son sessizliği
    kırpar (30 ms pay), 3.0 sn'den uzunsa en yüksek RMS enerjili 3 sn'lik pencereyi seçer (sınırlar sessizliğe denk
    gelir), 15 ms fade uygular, RMS'i -22 dBFS'e çeker (tepe ≤ -1 dBFS). 0.15 sn'den kısaysa ValueError("Kayıt çok
    kısa"); duyulur ses yoksa da ValueError. Hata durumunda dst'ye hiçbir şey yazılmaz."""
    src, dst, sr = Path(src), Path(dst), int(sr)
    with tempfile.TemporaryDirectory(prefix="sesklon-nv-") as td:
        raw = Path(td) / "ham.wav"
        audio.to_wav(src, raw, sr, MAX_INPUT_SECONDS)
        wav, file_sr = sf.read(str(raw), dtype="float32", always_2d=False)
    wav = _mono(wav)
    if file_sr != sr:
        wav = audio.resample(wav, file_sr, sr)
    if len(wav) < MIN_SECONDS * sr:
        raise ValueError("Kayıt çok kısa")
    wav = (wav - np.float32(np.mean(wav))).astype(np.float32)     # DC kayması kırpmayı ve fade'i bozmasın
    if not _has_sound(wav, sr):
        raise ValueError("Kayıt çok sessiz: duyulur bir ses bulunamadı")
    wav = audio.trim_silence(wav, sr, threshold_db=TRIM_DB, pad_ms=TRIM_PAD_MS)
    if len(wav) > int(MAX_SECONDS * sr):
        wav = _loudest_window(wav, sr, MAX_SECONDS)
        wav = audio.trim_silence(wav, sr, threshold_db=TRIM_DB, pad_ms=TRIM_PAD_MS)
    duration = len(wav) / sr
    if duration < MIN_SECONDS:
        raise ValueError("Kayıt çok kısa")
    wav = audio.fade(wav, sr, PREP_FADE_MS)
    wav = audio.rms_normalize(wav, target_dbfs=TARGET_RMS_DB, peak_dbfs=PEAK_DB)
    dst.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(dst), wav, sr)
    return duration


# ---------- üretimde sunum (mikro varyasyon) ----------

@functools.lru_cache(maxsize=8)
def _ffmpeg_has_filter(ffmpeg: str, name: str) -> bool:
    """Bu ffmpeg derlemesinde `name` filtresi var mı (ffmpeg yolu başına bir kez sorulur)?"""
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=15).stdout
    except Exception:  # noqa: BLE001
        return False
    return re.search(rf"^\s*\S+\s+{re.escape(name)}\s", out or "", flags=re.M) is not None


def _has_rubberband() -> bool:
    """ffmpeg var ve rubberband filtresiyle derlenmiş mi (sonuç ffmpeg yolu başına önbelleklenir)?"""
    ff = shutil.which("ffmpeg")
    return bool(ff) and _ffmpeg_has_filter(ff, "rubberband")


def _pitch_tempo(wav: np.ndarray, sr: int, semitones: float, tempo: float) -> np.ndarray | None:
    """Perde (yarım ton) ve tempoyu ffmpeg ile değiştirir: rubberband varsa onunla, yoksa asetrate+aresample+atempo.
    ffmpeg yoksa, değişim yok denecek kadar küçükse, parça çok kısaysa ya da çıktı tutarsızsa None (yalnızca seviye
    değişir; üretim hiçbir zaman bu yüzden düşmez)."""
    ff = shutil.which("ffmpeg")
    if not ff or (abs(semitones) < 0.005 and abs(tempo - 1.0) < 0.0005) or len(wav) < int(_MIN_FILTER_S * sr):
        return None
    ratio = 2.0 ** (semitones / 12.0)
    if _has_rubberband():
        af = f"rubberband=tempo={tempo:.6f}:pitch={ratio:.6f}"
    else:
        # asetrate perdeyi ve hızı birlikte `ratio` kadar değiştirir; atempo hızı istenen tempoya geri getirir
        asr = max(1, int(round(sr * ratio)))
        af = f"asetrate={asr},aresample={sr},atempo={tempo * sr / asr:.6f}"
    try:
        with tempfile.TemporaryDirectory(prefix="sesklon-nv-") as td:
            src, dst = Path(td) / "giris.wav", Path(td) / "cikis.wav"
            sf.write(str(src), np.asarray(wav, dtype=np.float32), sr, subtype="FLOAT")
            subprocess.run(
                [ff, "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(src), "-af", af,
                 "-ar", str(sr), "-ac", "1", "-c:a", "pcm_f32le", str(dst)],
                check=True, capture_output=True, timeout=FFMPEG_TIMEOUT_S,
            )
            out, out_sr = sf.read(str(dst), dtype="float32", always_2d=False)
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or b"").decode("utf-8", "replace").strip()[:300] or f"çıkış kodu {e.returncode}"
        log.warning("Sözsüz tepki varyasyonu uygulanamadı (%s): %s — yalnızca seviye değişecek", af, detail)
        return None
    except Exception as e:  # noqa: BLE001 — zaman aşımı, dosya/soundfile hataları
        log.warning("Sözsüz tepki varyasyonu uygulanamadı (%s): %s — yalnızca seviye değişecek", af, e)
        return None
    out = _mono(out)
    expected = len(wav) / tempo
    if out_sr != sr or out.size == 0 or abs(out.size - expected) > 0.1 * expected + 0.01 * sr:
        log.warning("Sözsüz tepki varyasyonu tutarsız çıktı verdi (%d örnek, beklenen ~%d) — yalnızca seviye "
                    "değişecek", out.size, int(expected))
        return None
    return out


def render_nonverbal(path: Path, sr: int, target_rms_db: float = TARGET_RMS_DB, seed: int | None = None) -> np.ndarray:
    """Hazırlanmış tepki kaydını üretim için sunar: yükler (mono), sr farklıysa audio.resample ile eşler; seed'li
    RNG ile seviye ±1.5 dB, tempo ±3 %, perde ±0.3 yarım ton mikro varyasyon uygular (ffmpeg varsa; yoksa yalnızca
    seviye), 10 ms fade, RMS = target_rms_db + seviye sapması, tepe ≤ -1 dBFS; float32 döner.

    Aynı seed → birebir aynı çıktı; seed=None → her çağrıda farklı. Rastgele sayılar ffmpeg olsun olmasın aynı sırayla
    çekilir: seviye sapması yoldan bağımsızdır. Dosya okunamazsa soundfile hatası yükselir (motor fallback_text'e
    düşebilir)."""
    wav, file_sr = sf.read(str(path), dtype="float32", always_2d=False)
    sr = int(sr)
    wav = _mono(wav)
    if file_sr != sr:
        wav = audio.resample(wav, file_sr, sr)
    rng = np.random.default_rng(None if seed is None else int(seed) % (1 << 64))
    level_db = float(rng.uniform(-LEVEL_JITTER_DB, LEVEL_JITTER_DB))
    tempo = float(1.0 + rng.uniform(-TEMPO_JITTER, TEMPO_JITTER))
    semitones = float(rng.uniform(-PITCH_JITTER_ST, PITCH_JITTER_ST))
    if wav.size == 0:
        return wav.astype(np.float32)
    varied = _pitch_tempo(wav, sr, semitones, tempo)
    if varied is not None:
        wav = varied
    wav = audio.fade(wav, sr, RENDER_FADE_MS)
    rms = _rms(wav)
    if rms > 1e-9:
        wav = wav * (audio.db_to_amp(float(target_rms_db) + level_db) / rms)
    return np.asarray(_limit_peak(wav), dtype=np.float32)


def level_match(piece: np.ndarray, sr: int, neighbor_rms_db: float | None, *,
                offset_db: float = NEIGHBOR_OFFSET_DB) -> np.ndarray:
    """Tepki parçasını komşu konuşma parçasının seviyesine göre ayarlar: parçanın etkin RMS'i (active_rms_db)
    neighbor_rms_db + offset_db'ye (varsayılan -4 dB: gülme konuşmadan biraz kısık durur) çekilir, tepe ≤ -1 dBFS.
    neighbor_rms_db'yi motor `active_rms_db(komsu, sr)` ile ölçmeli. Komşu seviyesi yok/sonsuz/sessiz ya da parça
    sessizse parça olduğu gibi (kopya) döner; kazanç değişimi ±20 dB ile sınırlıdır. Uzunluk korunur; float32."""
    x = _mono(piece).copy()
    if x.size == 0 or neighbor_rms_db is None:
        return x
    try:
        neighbor = float(neighbor_rms_db)
    except (TypeError, ValueError):
        return x
    if not math.isfinite(neighbor) or neighbor <= ACTIVE_FLOOR_DB:
        return x
    current = active_rms_db(x, sr)
    if not math.isfinite(current):
        return x
    gain_db = min(MAX_MATCH_GAIN_DB, max(-MAX_MATCH_GAIN_DB, neighbor + float(offset_db) - current))
    return np.asarray(_limit_peak(x * audio.db_to_amp(gain_db)), dtype=np.float32)
