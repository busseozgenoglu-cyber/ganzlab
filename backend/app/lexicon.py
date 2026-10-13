"""Telaffuz sözlüğü, satır içi okunuş, sohbet kısaltmaları ve konuşma dolguları (sözleşme bölüm 8).

Türkçe metin zincirindeki yeri:

    apply_inline_readings → expand_chat_speak → apply_lexicon → textnorm.normalize → colloquial_tr

``add_fillers`` isteğe bağlıdır (``fillers: true``) ve en sonda, konuşma dili katmanından sonra çalışmak üzere
tasarlandı.

Kullanıcı sözlüğü
-----------------
* Genel sözlük ``LEXICON_PATH`` (``data/lexicon.json``), ses sözlüğü ``voices/<voice_id>.lexicon.json``. İkisi de düz
  JSON nesnesidir: ``{"Claude": "Klod", "Red Bull": "Red Bul"}``. Aynı sözcük için ses sözlüğü geneli ezer.
* ``textnorm.DEFAULT_PRONUNCIATIONS`` bu modülden bağımsızdır; normalize içinde ayrıca çalışır. Kullanıcı sözlüğü
  ondan önce uygulandığı için aynı sözcükte kullanıcının okunuşu kazanır.
* Yazma atomiktir (aynı klasörde geçici dosya + fsync + ``os.replace``): eşzamanlı okuyan hiçbir zaman yarım dosya
  görmez. Aynı süreçteki oku-değiştir-yaz işlemleri kilitle sıraya girer. Okumalar (mtime, boyut, inode) damgasıyla
  önbelleğe alınır; dosya dışarıdan değişirse bir sonraki çağrı yenisini görür. Bozuk dosya boş sayılır ve ilk
  yazmada ``.bozuk`` uzantılı yedeğe taşınır (veri kaybolmaz).

Eşleşme kuralları (sözlük ve sohbet kısaltmaları)
-------------------------------------------------
* Sözcük sınırı ve Türkçe büyük/küçük harf (``tr_lower``: İ↔i, I↔ı). Büyük ASCII "I" hem ı hem i olabileceği için
  (INSTAGRAM / ILIK) iki türlü de eşleşir; küçük "ı" ile "i" ise ayrı harflerdir (kır ≠ kir). Şapkalı harfler de
  ayrıdır (kâr ≠ kar, hâlâ ≠ hala).
* Çok sözcüklü anahtarlar ("Red Bull") aradaki boşluk sayısından bağımsız eşleşir; en uzun anahtar önce denenir.
* Kesmeyle yazılmış ek korunur: "Claude'un" → "Klod'un".
* Baş harf büyüklüğü korunur: "claude" → "klod", "Claude" / "CLAUDE" → "Klod".
* Dokunulmayan yerler: köşeli parantez etiketleri ([gülerek], [ses:Ayşe]; "[vurgu: metin]" gibi kapsamlı etiketin
  yalnız metin kısmı işlenir), süslü parantezli satır içi okunuşlar, URL ve e-posta adresleri.
"""
from __future__ import annotations

import bisect
import contextlib
import json
import math
import os
import random
import re
import tempfile
import threading
import unicodedata
from pathlib import Path

from . import config
from .textnorm import EN_SPELL_WORDS, TR_ABBREV, TR_SPELL
from .tr import tr_capitalize, tr_lower, tr_upper

__all__ = [
    "CHAT_ABBREV",
    "FILLERS_COMMA",
    "FILLERS_END",
    "FILLERS_START",
    "FILLER_MIN_GAP",
    "LEXICON_PATH",
    "MAX_READING_CHARS",
    "MAX_WORD_CHARS",
    "NO_FILLER_STYLES",
    "add_fillers",
    "apply_inline_readings",
    "apply_lexicon",
    "delete_entry",
    "expand_chat_speak",
    "lexicon_report",
    "list_entries",
    "set_entry",
    "voice_lexicon_path",
]

# =============================================================================================================
# 1. DOSYALAR VE DOĞRULAMA
# =============================================================================================================

LEXICON_PATH: Path = config.DATA_DIR / "lexicon.json"

MAX_WORD_CHARS = 80
MAX_READING_CHARS = 200

_VOICE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-]{0,63}")
_WS_RE = re.compile(r"\s+")
# Etiket ([…]) ve satır içi okunuş ({…|…}) sözdizimiyle çakışan karakterler; arayüz de aynı kuralı uygular.
_FORBIDDEN_WORD = frozenset("[]{}|")
_FORBIDDEN_READING = _FORBIDDEN_WORD


def voice_lexicon_path(voice_id: str) -> Path:
    """Sesin sözlük dosyası: ``config.VOICES_DIR / f"{voice_id}.lexicon.json"``.

    Kimlik dosya adına girdiği için yalnız harf, rakam, "_" ve "-" kabul edilir; "../x" gibi yol kaçışları
    ``ValueError`` verir.
    """
    vid = voice_id.strip() if isinstance(voice_id, str) else ""
    if not _VOICE_ID_RE.fullmatch(vid):
        raise ValueError(f"Geçersiz ses kimliği: {voice_id!r}")
    return Path(config.VOICES_DIR) / f"{vid}.lexicon.json"


def _vid(voice_id: str | None) -> str | None:
    """None / "" / yalnız boşluk → None (genel sözlük)."""
    if voice_id is None:
        return None
    s = str(voice_id).strip()
    return s or None


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


_IDENT_FOLD = str.maketrans({"’": "'", "‐": "-", "‑": "-"})


def _ident(s: str) -> str:
    """Anahtar kimliği: NFC, tek boşluk, Türkçe küçük harf, ı/i birleşik, tipografik kesme ve tire düz.

    Kayıtta aynı sözcüğün büyük/küçük harf türevleri tek girdi sayılır ("Instagram" = "INSTAGRAM" = "instagram").
    """
    return tr_lower(_WS_RE.sub(" ", _nfc(s)).strip()).replace("ı", "i").translate(_IDENT_FOLD)


def _clean_text(value: object, *, what: str, limit: int, forbidden: frozenset) -> str:
    """Doğrular ve sadeleştirir (NFC, tek boşluk). Tüm doğrulama hataları ValueError'dır (API 400'e çevirir)."""
    if not isinstance(value, str):
        raise ValueError(f"{what} metin olmalı.")  # noqa: TRY004 — çağıran tek tür hata yakalar
    s = _WS_RE.sub(" ", _nfc(value)).strip()
    if not s:
        raise ValueError(f"{what} boş olamaz.")
    if len(s) > limit:
        raise ValueError(f"{what} en fazla {limit} karakter olabilir.")
    bad = sorted({c for c in s if c in forbidden})
    if bad:
        raise ValueError(f"{what} şu karakterleri içeremez: {' '.join(bad)}")
    if not any(c.isalnum() for c in s):
        raise ValueError(f"{what} en az bir harf ya da rakam içermeli.")
    return s


def _clean_word(word: object) -> str:
    return _clean_text(word, what="Sözcük", limit=MAX_WORD_CHARS, forbidden=_FORBIDDEN_WORD)


def _clean_reading(reading: object) -> str:
    return _clean_text(reading, what="Okunuş", limit=MAX_READING_CHARS, forbidden=_FORBIDDEN_READING)


# Türk alfabesi + yabancı sözcüklerdeki q, w, x (Latin sırasındaki yerlerinde)
_TR_ALPHABET = "abcçdefgğhıijklmnoöpqrsştuüvwxyz"
_TR_RANK = {c: i for i, c in enumerate(_TR_ALPHABET)}


def _sort_char(c: str) -> tuple[int, int, int]:
    if c in _TR_RANK:
        return 1, _TR_RANK[c], 0
    if c.isalpha():                               # şapkalı / aksanlı harf: temel harfin hemen ardından
        base = unicodedata.normalize("NFD", c)[0]
        return (1, _TR_RANK[base], 1) if base in _TR_RANK else (2, ord(c), 0)
    return 0, ord(c), 0                           # rakam ve noktalama harflerden önce


def _sort_key(word: str) -> tuple:
    """Türk alfabesi sırası: ç c'den sonra, ı i'den önce; â a'nın, é e'nin ardından; harf dışı karakterler önce."""
    return tuple(_sort_char(c) for c in tr_lower(word)), word


# ------------------------------------------------------------------------------------------- okuma / yazma

_WRITE_LOCK = threading.RLock()
# yol → ((mtime_ns, boyut, inode), tablo, bozuk_mu). Tablolar paylaşılır: değiştirilmeden önce kopyalanır.
_FILE_CACHE: dict[str, tuple[tuple[int, int, int], dict[str, str], bool]] = {}


def _stamp(path: Path | None) -> tuple[int, int, int] | None:
    if path is None:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size, st.st_ino


def _clean_table(raw: object) -> dict[str, str]:
    """Dosyadan okunan nesneyi doğrular: geçersiz çiftler atlanır, aynı kimlikli anahtarlarda sonuncu kazanır."""
    table: dict[str, str] = {}
    if not isinstance(raw, dict):
        return table
    by_ident: dict[str, str] = {}
    for k, v in raw.items():
        try:
            word, reading = _clean_word(k), _clean_reading(v)
        except ValueError:
            continue
        old = by_ident.get(_ident(word))
        if old is not None:
            table.pop(old, None)
        table[word] = reading
        by_ident[_ident(word)] = word
    return table


def _read_file(path: Path) -> tuple[dict[str, str], bool]:
    """(tablo, bozuk_mu). Dosya yoksa boş tablo. Dönen tablo önbellekle paylaşılır: değiştirilmemeli."""
    stamp = _stamp(path)
    if stamp is None:
        return {}, False
    key = os.fspath(path)
    hit = _FILE_CACHE.get(key)
    if hit is not None and hit[0] == stamp:
        return hit[1], hit[2]
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        corrupt = not isinstance(raw, dict)
    except FileNotFoundError:            # stat ile açma arasında silindi
        return {}, False
    except (OSError, ValueError):        # okunamayan / geçersiz JSON (UnicodeDecodeError da ValueError'dır)
        raw, corrupt = None, True
    table = _clean_table(raw)
    _FILE_CACHE[key] = (stamp, table, corrupt)
    return table, corrupt


def _fsync_dir(directory: Path) -> None:
    """Yeniden adlandırmanın diske işlenmesi için klasörü de eşitler (POSIX; olmazsa sessizce geçer)."""
    if os.name != "posix":
        return
    with contextlib.suppress(OSError):
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _write_file(path: Path, table: dict[str, str]) -> None:
    """Tabloyu atomik yazar (geçici dosya → fsync → os.replace). Boş tablo dosyayı siler."""
    key = os.fspath(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not table:
            with contextlib.suppress(FileNotFoundError):
                os.remove(path)
            return
        ordered = {k: table[k] for k in sorted(table, key=_sort_key)}
        data = (json.dumps(ordered, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=os.fspath(path.parent))
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            with contextlib.suppress(OSError):
                os.chmod(tmp, 0o644)       # mkstemp 0600 açar; diğer veri dosyalarıyla aynı izin
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.remove(tmp)
            raise
        _fsync_dir(path.parent)
    finally:
        _FILE_CACHE.pop(key, None)


def _load_for_update(path: Path) -> dict[str, str]:
    """Yazmadan önce okur (kopya döner). Bozuk dosya ``<ad>.bozuk`` olarak yedeklenir, boş tabloyla başlanır."""
    table, corrupt = _read_file(path)
    if corrupt:
        with contextlib.suppress(OSError):
            os.replace(path, path.with_name(path.name + ".bozuk"))
        _FILE_CACHE.pop(os.fspath(path), None)
        return {}
    return dict(table)


def _scope_path(voice_id: str | None) -> tuple[Path, str]:
    vid = _vid(voice_id)
    if vid is not None:
        return voice_lexicon_path(vid), "voice"
    return Path(LEXICON_PATH), "global"


# =============================================================================================================
# 2. SÖZLÜK İŞLEMLERİ (CRUD)
# =============================================================================================================

def list_entries(voice_id: str | None = None) -> list[dict]:
    """Birleşik sözlük: ``[{"word", "reading", "scope": "global"|"voice"}]``, Türk alfabesine göre sıralı.

    ``voice_id`` verilirse ses sözlüğü de eklenir; ses sözlüğündeki sözcük genel sözlükteki aynı sözcüğü gizler
    (geçerli olan okunuş gösterilir).
    """
    merged: dict[str, dict] = {}
    for word, reading in _read_file(Path(LEXICON_PATH))[0].items():
        merged[_ident(word)] = {"word": word, "reading": reading, "scope": "global"}
    vid = _vid(voice_id)
    if vid is not None:
        for word, reading in _read_file(voice_lexicon_path(vid))[0].items():
            merged[_ident(word)] = {"word": word, "reading": reading, "scope": "voice"}
    return sorted(merged.values(), key=lambda e: _sort_key(e["word"]))


def set_entry(word: str, reading: str, voice_id: str | None = None) -> dict:
    """Sözcüğü ekler ya da günceller; ``{"word", "reading", "scope"}`` döner.

    Aynı sözcüğün büyük/küçük harf türevi varsa onun yerine geçer (tek girdi kalır). Boş / çok uzun / etiket
    karakteri ([ ] { } |) içeren değerler ``ValueError`` verir.
    """
    w, r = _clean_word(word), _clean_reading(reading)
    path, scope = _scope_path(voice_id)
    ident = _ident(w)
    with _WRITE_LOCK:
        table = _load_for_update(path)
        for k in [k for k in table if _ident(k) == ident]:
            del table[k]
        table[w] = r
        _write_file(path, table)
    return {"word": w, "reading": r, "scope": scope}


def delete_entry(word: str, voice_id: str | None = None) -> bool:
    """Sözcüğü siler (büyük/küçük harf duyarsız). Bulunduysa True. Sözlük boşalırsa dosyası da silinir."""
    if not isinstance(word, str) or not word.strip():
        return False
    path, _ = _scope_path(voice_id)
    ident = _ident(word)
    with _WRITE_LOCK:
        table, corrupt = _read_file(path)
        hits = [k for k in table if _ident(k) == ident]
        if corrupt or not hits:
            return False
        table = {k: v for k, v in table.items() if k not in hits}
        _write_file(path, table)
    return True


# =============================================================================================================
# 3. EŞLEŞTİRME ALTYAPISI (sözlük ve sohbet kısaltmaları ortak)
# =============================================================================================================

def _char_re(c: str) -> str:
    """Anahtardaki bir karakterin metinde eşleşeceği karakter sınıfı (Türkçe büyük/küçük harf duyarsız)."""
    if c == "I":                       # anahtarda büyük ASCII I: ı da i de olabilir (Instagram / Isparta)
        return "[iıIİ]"
    if c in "iİ":                      # metindeki büyük I (INSTAGRAM) yabancı sözcükte i'dir
        return "[iİI]"
    if c == "ı":
        return "[ıI]"
    if c == " ":
        return r"[ \t\u00a0]+"
    if c in "'’":
        return "['’]"
    if c in "-‐‑":
        return "[-‐‑]"
    variants = {c}
    for v in (tr_lower(c), tr_upper(c)):
        if len(v) == 1:
            variants.add(v)
    if len(variants) == 1:
        return re.escape(c)
    return "[" + "".join(re.escape(v) for v in sorted(variants)) + "]"


def _phrase_re(word: str) -> str:
    return "".join(_char_re(c) for c in _WS_RE.sub(" ", _nfc(word).strip()))


# Sol sınır: önünde harf/rakam yok ve kesme ekinin içinde değil ("Ahmet'in" içindeki "in" eşleşmez).
_LEFT = r"(?<![\w])(?<![\w]['’])"
_SUFFIX = r"(?:(?P<apo>['’])(?P<suf>[^\W\d_]+))?"
_RIGHT = r"(?![\w])"


def _compile(words: list[str]) -> re.Pattern | None:
    """Tek birleşik desen; en uzun anahtar önce (aynı konumda "Red Bull", "Red"den önce denenir)."""
    words = [w for w in words if w and w.strip()]
    if not words:
        return None
    ordered = sorted(set(words), key=lambda w: (-len(_ident(w)), _ident(w), w))
    alts = "|".join(_phrase_re(w) for w in ordered)
    return re.compile(rf"{_LEFT}(?P<k>{alts}){_SUFFIX}{_RIGHT}")


# ---- dokunulmayan bölgeler: etiketler, satır içi okunuşlar, URL / e-posta ----

_TAG_SPAN_RE = re.compile(r"\[(?P<inner>[^\[\]\n]*)\]")
_SCOPED_TAG_RE = re.compile(r"(?P<label>[^:\[\]\n]{1,30}):(?P<body>.*\S.*)")
_SPEAKER_LABELS = frozenset({"ses", "konuşmacı", "konusmaci", "speaker", "voice", "karakter"})
_BRACE_SPAN_RE = re.compile(r"\{[^{}\n]*\}")
_TLDS = (
    "com|net|org|edu|gov|mil|tr|io|ai|co|dev|app|info|biz|xyz|tech|store|shop|online|site|fit|de|uk|eu|tv|gg|fm|ly|"
    "pro|blog|cloud|design|studio|media|news|club|life|world|live|today|academy|games|global|website|space|"
    "digital|agency|art|beauty"
)
_URL_TAIL = r"[^\s<>\"\[\]{}]*[^\s<>\"\[\]{}.,;:!?)'’]"
_URLISH_RE = re.compile(
    rf"(?:https?://|www\.){_URL_TAIL}"
    r"|[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+"
    rf"|(?<![\w@.\-])[\w\-]+(?:\.[\w\-]+)*\.(?:{_TLDS})(?![\w\-])(?:/(?:{_URL_TAIL})?)?",
    re.IGNORECASE,
)


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def _protected_spans(text: str) -> list[tuple[int, int]]:
    """Değiştirilmeyecek bölgeler (sıralı, birleşik). Kapsamlı etiketin ("[vurgu: metin]") metin kısmı serbesttir;
    konuşmacı etiketi ("[ses:Ayşe]") bütünüyle korunur."""
    spans: list[tuple[int, int]] = []
    for m in _TAG_SPAN_RE.finditer(text):
        sm = _SCOPED_TAG_RE.fullmatch(m.group("inner"))
        label = sm.group("label").strip() if sm else ""
        if sm and any(c.isalpha() for c in label) and tr_lower(label) not in _SPEAKER_LABELS:
            spans.append((m.start(), m.start("inner") + sm.start("body")))
            spans.append((m.end() - 1, m.end()))
        else:
            spans.append(m.span())
    spans.extend(m.span() for m in _BRACE_SPAN_RE.finditer(text))
    spans.extend(m.span() for m in _URLISH_RE.finditer(text))
    return _merge_spans(spans)


def _overlaps(a: int, b: int, spans: list[tuple[int, int]], starts: list[int]) -> bool:
    """[a, b) aralığı korunan bir bölgeyle kesişiyor mu (spans sıralı ve çakışmasız)."""
    i = bisect.bisect_right(starts, a) - 1
    if i >= 0 and spans[i][1] > a:
        return True
    return i + 1 < len(spans) and spans[i + 1][0] < b


# =============================================================================================================
# 4. SÖZLÜĞÜ UYGULAMA
# =============================================================================================================

# (genel yol, damga, ses yolu, damga) → (desen, kimlik → (yazılış, okunuş, kapsam))
_MATCHER_CACHE: dict[tuple, tuple[re.Pattern | None, dict[str, tuple[str, str, str]]]] = {}


def _matcher(voice_id: str | None) -> tuple[re.Pattern | None, dict[str, tuple[str, str, str]]]:
    gpath = Path(LEXICON_PATH)
    vpath: Path | None = None
    if voice_id is not None:
        with contextlib.suppress(ValueError):     # geçersiz kimlik: yalnız genel sözlük (seslendirme durmasın)
            vpath = voice_lexicon_path(voice_id)
    key = (os.fspath(gpath), _stamp(gpath), os.fspath(vpath) if vpath else None, _stamp(vpath))
    hit = _MATCHER_CACHE.get(key)
    if hit is not None:
        return hit
    table: dict[str, tuple[str, str, str]] = {}
    for w, r in _read_file(gpath)[0].items():
        table[_ident(w)] = (w, r, "global")
    if vpath is not None:
        for w, r in _read_file(vpath)[0].items():
            table[_ident(w)] = (w, r, "voice")         # ses sözlüğü geneli ezer
    result = (_compile([e[0] for e in table.values()]), table)
    if len(_MATCHER_CACHE) > 64:
        _MATCHER_CACHE.clear()
    _MATCHER_CACHE[key] = result
    return result


def _is_tr(lang: object) -> bool:
    if lang is None:
        return True
    s = tr_lower(str(lang)).strip().replace("_", "-").split("-")[0]
    return s in ("", "tr", "tur", "turkish", "türkçe", "turkce")


def _match_case(src: str, reading: str) -> str:
    """Okunuşun ilk harfini kaynağın ilk harfinin büyüklüğüne uydurur (gerisi okunuştaki gibi kalır)."""
    first = next((c for c in src if c.isalpha()), "")
    idx = next((i for i, c in enumerate(reading) if c.isalpha()), None)
    if not first or idx is None:
        return reading
    ch = reading[idx]
    new = tr_upper(ch) if first.isupper() else tr_lower(ch)
    return reading[:idx] + new + reading[idx + 1:]


def _apply(text: str, lang: object, voice_id: str | None) -> tuple[str, list[dict]]:
    if not isinstance(text, str) or not text or not _is_tr(lang):
        return text, []
    regex, table = _matcher(_vid(voice_id))
    if regex is None:
        return text, []
    src = _nfc(text)
    protected = _protected_spans(src)
    starts = [a for a, _ in protected]
    out: list[str] = []
    changes: list[dict] = []
    last = 0
    for m in regex.finditer(src):
        a, b = m.span()
        if protected and _overlaps(a, b, protected, starts):
            continue
        entry = table.get(_ident(m.group("k")))
        if entry is None:
            continue
        rep = _match_case(m.group("k"), entry[1])
        if m.group("suf"):
            rep += m.group("apo") + m.group("suf")      # kesmeli ek olduğu gibi korunur: Claude'un → Klod'un
        if rep == m.group(0):
            continue
        out.append(src[last:a])
        out.append(rep)
        last = b
        changes.append({"from": m.group(0), "to": rep})
    if not changes:
        return text, []
    out.append(src[last:])
    return "".join(out), changes


def apply_lexicon(text: str, lang: str = "tr", voice_id: str | None = None) -> str:
    """Kullanıcı sözlüğünü uygular (textnorm'dan ÖNCE çalışır).

    Genel sözlük + (verildiyse) ses sözlüğü; ses sözlüğü aynı sözcükte geneli ezer. Kurallar modül belgesinde:
    sözcük sınırı, Türkçe büyük/küçük harf, en uzun anahtar önce, baş harf büyüklüğü korunur, kesmeli ek korunur,
    çok sözcüklü anahtar desteklenir; etiket / satır içi okunuş / URL / e-postaya dokunulmaz. Türkçe dışı dillerde
    metin değişmeden döner (textnorm okunuş sözlüğüyle aynı ilke). Değişiklik yoksa girdinin kendisi döner.

    Örnek (sözlükte {"Claude": "Klod", "Red Bull": "Red Bul"} varken): "CLAUDE'un Red  Bull'u" → "Klod'un Red Bul'u".
    """
    return _apply(text, lang, voice_id)[0]


def lexicon_report(text: str, voice_id: str | None = None, lang: str = "tr") -> list[dict]:
    """``apply_lexicon``'un yaptığı değişiklikler, metin sırasıyla: ``[{"from": "Claude'un", "to": "Klod'un"}]``."""
    return _apply(text, lang, voice_id)[1]


# =============================================================================================================
# 5. SATIR İÇİ OKUNUŞ — {yazılış|okunuş}
# =============================================================================================================

_INLINE_RE = re.compile(r"\{(?P<body>[^{}\[\]\n]*)\}")


def apply_inline_readings(text: str) -> str:
    """Satır içi okunuşları çözer: "{Claude|Klod}" → "Klod"; "{Klod}" → "Klod" (``|`` yoksa içerik aynen).

    İç içe kullanım yoktur; okunuş boşsa yazılış kullanılır ("{Claude|}" → "Claude"); köşeli parantez
    etiketlerine (ve içlerindeki süslü parantezlere) dokunulmaz. Dilden bağımsızdır.
    """
    if not isinstance(text, str) or "{" not in text:
        return text
    tags = [m.span() for m in _TAG_SPAN_RE.finditer(text)]
    starts = [a for a, _ in tags]

    def repl(m: re.Match) -> str:
        if tags and _overlaps(m.start(), m.end(), tags, starts):
            return m.group(0)
        body = m.group("body")
        if "|" not in body:
            return body
        written, _, reading = body.partition("|")
        return reading.strip() or written.strip()

    return _INLINE_RE.sub(repl, text)


# =============================================================================================================
# 6. SOHBET KISALTMALARI
# =============================================================================================================

CHAT_ABBREV: dict[str, str] = {
    # --- sözleşmedeki liste ---
    "tmm": "tamam", "nbr": "naber", "slm": "selam", "mrb": "merhaba",
    "tşk": "teşekkürler", "tşkr": "teşekkürler", "tsk": "teşekkürler",
    "kib": "kendine iyi bak", "bb": "bay bay", "msj": "mesaj", "tlf": "telefon", "grs": "görüşürüz",
    "iyi gcl": "iyi geceler", "nsl": "nasıl", "nslsn": "nasılsın", "bgn": "bugün", "yrn": "yarın",
    "şmd": "şimdi", "hyr": "hayır", "evt": "evet", "ok": "okey", "cnm": "canım", "knk": "kanka",
    "abi": "abi", "abe": "abi", "inş": "inşallah", "mşl": "maşallah", "aeo": "allaha emanet ol",
    "sa": "selamün aleyküm", "as": "aleyküm selam",
    # --- ek kısaltmalar (Türkçe sözcük, birim ya da kurum kısaltmasıyla çakışmayanlar seçildi; bilinçli olarak
    #     YOK: "sn" (saniye/sayın), "kb" (kilobayt), "bn" (milyar), "gs" (Galatasaray), "yk", "vs", "ii") ---
    "mrhb": "merhaba", "slmlr": "selamlar", "gnydn": "günaydın", "iyi gclr": "iyi geceler",
    "iyi akşmlr": "iyi akşamlar", "iyi gnlr": "iyi günler",
    "tşk ederim": "teşekkür ederim", "tşkr ederim": "teşekkür ederim", "tsk ederim": "teşekkür ederim",
    "tşkler": "teşekkürler", "eyw": "eyvallah", "eyv": "eyvallah", "kbs": "kusura bakma", "glb": "galiba",
    "hcm": "hocam", "krdşm": "kardeşim", "bşy": "bişey", "nrdsn": "nerdesin", "nrde": "nerede", "zmn": "zaman",
    "msl": "mesela", "ztn": "zaten", "dimi": "di mi", "tmmdır": "tamamdır", "hg": "hoş geldin",
    "pls": "lütfen", "plz": "lütfen", "sğl": "sağ ol", "dk": "dakika", "bnm": "benim", "snn": "senin",
    "çk": "çok", "gzl": "güzel", "nslsnz": "nasılsınız",
}

# Satır başındaki "as" ardından bu sözcükler gelirse selam değil, "as" (asmak / as oyuncu) demektir.
_AS_NOT_GREETING = frozenset({
    "oyuncu", "oyuncular", "oyuncusu", "oyuncuları", "kadro", "kadroda", "kadrosu", "kadroya", "futbolcu",
    "futbolcular", "forvet", "golcü", "isim", "takım", "takımı", "bayrak", "bayrağı", "bayrakları", "bayrağını",
    "bayraklarını", "şunu", "bunu", "onu", "şunları", "bunları", "onları", "şuraya", "buraya", "oraya", "duvara",
    "askıya", "tabloyu", "resmi", "çamaşırları", "perdeyi", "perdeleri",
})
# Tamamı büyük harfle yazılmış kurum kısaltmaları açılmaz: "TSK" Türk Silahlı Kuvvetleri'dir, "teşekkürler" değil.
_CHAT_ACRONYM_GUARD = frozenset(TR_SPELL) | frozenset(EN_SPELL_WORDS)

_CHAT_CACHE: dict = {"key": None, "regex": None, "table": None}


def _chat_matcher() -> tuple[re.Pattern | None, dict[str, str]]:
    """CHAT_ABBREV'den derlenmiş desen; sözlük çalışma anında genişletilirse yeniden derlenir."""
    key = tuple(CHAT_ABBREV.items())
    if _CHAT_CACHE["key"] != key:
        table: dict[str, str] = {}
        words: list[str] = []
        for k, v in CHAT_ABBREV.items():
            if isinstance(k, str) and isinstance(v, str) and k.strip():
                table[_ident(k)] = v
                words.append(k)
        _CHAT_CACHE.update(key=key, regex=_compile(words), table=table)
    return _CHAT_CACHE["regex"], _CHAT_CACHE["table"]


# ---- bağlam yardımcıları (cümle başı, satır başı, ardından gelen) ----

_LEAD_RE = re.compile(r"(?:[ \t\u00a0\"'“‘«„>*•·]|[-–—](?=[ \t])|\[[^\[\]\n]*\])*")
# Dolgu yerleştirirken tırnaklar atlanmaz: dolgu açılış tırnağının ÖNÜNE gelir, içine değil.
_FILLER_LEAD_RE = re.compile(r"(?:[ \t\u00a0>*•·]|[-–—](?=[ \t])|\[[^\[\]\n]*\])*")
_SPEAKER_RE = re.compile(
    r"(?P<name>[A-ZÇĞİÖŞÜ][^\W\d_]*(?:[ .'’\-][^\W\d_]+){0,2})[ \t]*(?:\([^()\n]{0,40}\)[ \t]*)?"
    r"(?P<sep>:|[-–—])(?=[ \t]|$)"
)


def _strip_line_prefix(text: str, a: int, b: int, lead: re.Pattern = _LEAD_RE) -> tuple[int, str | None]:
    """Satır başı önekini atlar (boşluk, tırnak, madde imi, etiket, "Ayşe:" / "AYŞE —" konuşmacı adı).

    Döner: (öneksiz konum, konuşmacı ayracı ":" / "-" / None).
    """
    p = lead.match(text, a, b).end()
    sm = _SPEAKER_RE.match(text, p, b)
    if sm:
        return lead.match(text, sm.end(), b).end(), (":" if sm.group("sep") == ":" else "-")
    return p, None


def _at_line_start(text: str, pos: int) -> bool:
    ls = text.rfind("\n", 0, pos) + 1
    return _strip_line_prefix(text, ls, pos)[0] == pos


def _skip_back(text: str, i: int) -> int:
    """i'den geriye boşluk, açılış tırnağı ve etiketleri atlar; ilk anlamlı karakterin konumu (yoksa -1)."""
    while i >= 0:
        c = text[i]
        if c in " \t\u00a0\"'“‘«„(":
            i -= 1
        elif c == "]":
            j = text.rfind("[", 0, i)
            if j < 0 or "\n" in text[j:i]:
                return i
            i = j - 1
        else:
            return i
    return -1


def _prev_kind(text: str, pos: int) -> str:
    """pos'tan önceki bağlam: "start" (metin/satır başı), "sentence" (. ! ? … :), "clause" (, ;) ya da "word"."""
    i = _skip_back(text, pos - 1)
    if i < 0 or text[i] in "\n\r":
        return "start"
    c = text[i]
    if c in ".!?…:":
        return "sentence"
    if c in ",;":
        return "clause"
    return "word"


def _next_kind(text: str, pos: int) -> str:
    """pos'tan sonraki bağlam: "end" (metin/satır sonu), "sentence", "clause", "word" ya da "other" (emoji…)."""
    i, n = pos, len(text)
    while i < n and text[i] in " \t\u00a0\"'”’»)":
        i += 1
    if i >= n or text[i] in "\n\r":
        return "end"
    c = text[i]
    if c in ".!?…":
        return "sentence"
    if c in ",;:":
        return "clause"
    return "word" if c.isalnum() else "other"


_NEXT_WORD_RE = re.compile(r"[ \t\u00a0]*([^\W\d_]+)")


def _sentence_start(text: str, pos: int) -> bool:
    return _prev_kind(text, pos) in ("start", "sentence") or _at_line_start(text, pos)


def _chat_allowed(text: str, m: re.Match, key: str) -> bool:
    """Bağlam kuralları: "sa"/"as" yalnız tek sözcüklük cümlede ya da satır başında; "ok" yalnız tek başına;
    cümle ortasında büyük harfle başlayan sözcük özel addır ("Shinzo Abe"); büyük harfli kurum kısaltmaları
    ("TSK") açılmaz."""
    tok = m.group("k")
    if tok in _CHAT_ACRONYM_GUARD:
        return False
    letters = [c for c in tok if c.isalpha()]
    all_caps = len(letters) >= 2 and all(c.isupper() for c in letters)
    if tok[:1].isupper() and not all_caps and not _sentence_start(text, m.start()):
        return False
    if key not in ("sa", "as", "ok"):
        return True
    if m.group("suf"):                    # "sa'ya", "ok'u" → kısaltma değil
        return False
    nxt = _next_kind(text, m.end())
    alone_after = nxt in ("end", "sentence", "clause")
    if key == "ok":
        before = _prev_kind(text, m.start())
        return alone_after and (before in ("start", "sentence", "clause") or _at_line_start(text, m.start()))
    if _at_line_start(text, m.start()):  # satır başı: ardından noktalama ya da boşluk (sözcük sınırı zaten var)
        if key == "as" and nxt == "word":
            w = _NEXT_WORD_RE.match(text, m.end())
            return not (w and tr_lower(w.group(1)) in _AS_NOT_GREETING)
        return True
    return _prev_kind(text, m.start()) in ("start", "sentence") and alone_after   # tek sözcüklük cümle


def _chat_case(tok: str, expansion: str) -> str:
    """"tmm" → "tamam", "Tmm" → "Tamam", "TMM" → "TAMAM"."""
    letters = [c for c in tok if c.isalpha()]
    if len(letters) >= 2 and all(c.isupper() for c in letters):
        return tr_upper(expansion)
    if tok[:1].isupper():
        return tr_capitalize(expansion)
    return expansion


def expand_chat_speak(text: str) -> str:
    """Sohbet kısaltmalarını açar: "tmm, yrn grs" → "tamam, yarın görüşürüz"; "Tmm" → "Tamam".

    Sözcük sınırı ve Türkçe büyük/küçük harf duyarsız eşleşme (``CHAT_ABBREV``); kesmeli ek bitiştirilir
    ("msj'ı" → "mesajı"). "sa"/"as" yalnızca tek sözcüklük cümlede ya da satır başında (ardından noktalama/boşluk),
    "ok" yalnızca tek başına ("Ok." / "ok, gelirim") açılır; "ok ve yay"daki ok sözcüktür. Etiket, satır içi
    okunuş, URL ve e-postaya dokunulmaz. Çıktıya yeniden uygulamak bir şey değiştirmez.
    """
    if not isinstance(text, str) or not text:
        return text
    regex, table = _chat_matcher()
    if regex is None:
        return text
    src = _nfc(text)
    protected = _protected_spans(src)
    starts = [a for a, _ in protected]
    out: list[str] = []
    last = 0
    changed = False
    for m in regex.finditer(src):
        a, b = m.span()
        if protected and _overlaps(a, b, protected, starts):
            continue
        key = _ident(m.group("k"))
        expansion = table.get(key)
        if expansion is None or not _chat_allowed(src, m, key):
            continue
        rep = _chat_case(m.group("k"), expansion) + (m.group("suf") or "")
        if rep == m.group(0):
            continue
        out.append(src[last:a])
        out.append(rep)
        last = b
        changed = True
    if not changed:
        return text
    out.append(src[last:])
    return "".join(out)


# =============================================================================================================
# 7. KONUŞMA DOLGULARI
# =============================================================================================================

FILLERS_START = ("Yani, ", "Hani, ", "İşte, ", "Şey, ", "Ya, ", "Bak, ", "Valla, ")
FILLERS_COMMA = (" yani", " işte")
FILLERS_END = (" ya", " yani", " işte")
FILLER_MIN_GAP = 4          # dolgulu iki cümle arasında en az bu kadar cümle sırası farkı: her 4 cümlede en çok 1
NO_FILLER_STYLES = frozenset({"haber", "belgesel", "sesli-kitap", "eğitim", "müşteri-hizmeti", "anlatıcı"})

_FILLER_WORDS = frozenset({"yani", "hani", "işte", "şey", "ya", "bak", "valla", "vallahi"})
_FILLER_NOCOMMA = frozenset({"yani", "hani", "işte", "şey", "valla", "vallahi"})   # virgülsüz de dolgudur
# Bu sözcüklerle başlayan cümlenin başına dolgu eklenmez ("Yani, ama…" doğal değil).
_NO_START_WORDS = frozenset({
    "ama", "ve", "fakat", "lakin", "ancak", "çünkü", "zira", "yoksa", "veya", "ya", "yani", "hani", "işte", "şey",
    "bak", "valla", "vallahi", "evet", "hayır", "tamam", "peki", "hmm", "of", "ah", "eh", "oh", "hey", "ay", "aa",
    "vay", "yok", "e", "ee", "ha", "hı", "hıhı", "selam", "selamlar", "merhaba", "merhabalar", "günaydın", "alo",
})
# Selamlaşmadan hemen sonraki virgüle dolgu gelmez ("Selam, işte…" doğal değil).
_GREETINGS = frozenset({"selam", "selamlar", "merhaba", "merhabalar", "günaydın", "alo", "hey"})
# Bu sözcüklerle biten cümlenin sonuna dolgu eklenmez ("Geldim be ya." olmaz).
_NO_END_WORDS = frozenset({
    "ya", "yani", "işte", "be", "lan", "ki", "valla", "vallahi", "yahu", "hani", "şey", "ha", "he", "hı", "mı",
    "mi", "mu", "mü",
})
# Virgülden sonra bunlar gelirse araya dolgu girmez ("…, yani di mi?", "…, işte ama…" doğal değil).
_AFTER_COMMA_SKIP = frozenset({
    "yani", "işte", "ya", "hani", "şey", "valla", "vallahi", "bak", "di", "değil", "diil", "mi", "mı", "ama",
    "fakat", "ancak", "lakin", "çünkü", "zira", "ve", "veya", "yahut", "yoksa", "ki", "de", "da", "hem", "ne",
})
_QUESTION_PARTICLE_RE = re.compile(r"m[ıiuü](?:[sydnz][^\W\d_]*)?")

_QUOTE_SPAN_RE = re.compile(
    r'"[^"\n]*"|“[^”\n]*”|«[^»\n]*»|„[^“”\n]*[“”]|(?<![\w])‘[^‘’\n]*’(?![\w])'
)
_MASK = "\x00"
_OPENERS = "\"'“‘«„(["
_SENT_END_RE = re.compile(r"[.!?…]+[\"'”’»)\]\x00]*(?=[ \t\u00a0]|$)")
_TOKEN_RE = re.compile(r"[^\W_]+")
_WORD_AT_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?")
_START_FILLER_RE = re.compile(r"(?P<w>[^\W\d_]+)(?P<comma>[ \t]*,)?")
_COMMA_RE = re.compile(r",(?=[ \t]+[^\W\d_])")
_END_RE = re.compile(r"([^\W\d_]+)([.!]+)$")
_PREV_WORD_RE = re.compile(r"([^\W\d_]+)$")

_STYLE_FALLBACK = {
    "sesli-kitap": "sesli-kitap", "audiobook": "sesli-kitap", "egitim": "eğitim", "education": "eğitim",
    "anlatici": "anlatıcı", "narrator": "anlatıcı", "news": "haber", "documentary": "belgesel",
    "musteri-hizmeti": "müşteri-hizmeti", "müşteri-hizmetleri": "müşteri-hizmeti",
}


def _style_name(style: object) -> str:
    """Stil adını kanonik ada çevirir ("Sesli Kitap", "audiobook" → "sesli-kitap"); styles.py varsa onu kullanır."""
    if style is None:
        return "sohbet"
    s = str(getattr(style, "name", style)).strip()
    if not s:
        return "sohbet"
    try:
        from .styles import resolve_style

        st = resolve_style(s)
        if st is not None:
            return st.name
    except Exception:  # noqa: BLE001, S110 — stil modülü yüklenemezse yerel eşleme yeterli
        pass
    k = re.sub(r"[\s_]+", "-", tr_lower(s))
    return _STYLE_FALLBACK.get(k, k)


def _mask(text: str) -> str:
    """Etiket, satır içi okunuş, tırnak içi ve URL karakterlerini ``\\x00`` ile örter (uzunluk korunur): bu
    bölgelerde cümle sınırı aranmaz, virgül/sözcük sayılmaz, dolgu eklenmez."""
    chars = list(text)
    for rx in (_TAG_SPAN_RE, _BRACE_SPAN_RE, _QUOTE_SPAN_RE, _URLISH_RE):
        for m in rx.finditer(text):
            for i in range(m.start(), m.end()):
                if chars[i] != "\n":
                    chars[i] = _MASK
    return "".join(chars)


def _is_boundary(text: str, masked: str, ps: int, e: int, line_end: int) -> bool:
    """[ps, e) noktalama öbeği gerçek bir cümle sonu mu ("Dr. Ayşe", "3. sınıf", "A. Yılmaz" değil)."""
    j = e
    while j < line_end and text[j] in " \t\u00a0":
        j += 1
    if j >= line_end:
        return True
    nxt = masked[j]
    if nxt.isalpha() and nxt.islower():          # küçük harfle devam: sıra sayısı / kısaltma
        return False
    if text[ps] == "." and e - ps == 1:
        w = _PREV_WORD_RE.search(text, max(0, ps - 16), ps)
        if w and (len(w.group(1)) == 1 or tr_lower(w.group(1)) in TR_ABBREV):
            return False
    return True


def _sentence_spans(text: str, masked: str) -> list[tuple[int, int]]:
    """Cümle aralıkları (boşluklar kırpılmış). Satır sonu her zaman sınırdır."""
    raw: list[tuple[int, int]] = []
    n = len(text)
    ls = 0
    while ls <= n:
        le = text.find("\n", ls)
        if le < 0:
            le = n
        s = ls
        for m in _SENT_END_RE.finditer(masked, ls, le):
            if _is_boundary(text, masked, m.start(), m.end(), le):
                raw.append((s, m.end()))
                s = m.end()
        if s < le:
            raw.append((s, le))
        ls = le + 1
    spans = []
    for a, b in raw:
        while a < b and text[a].isspace():
            a += 1
        while b > a and text[b - 1].isspace():
            b -= 1
        if a < b:
            spans.append((a, b))
    return spans


def _should_lower(word: str, text: str, pos: int) -> bool:
    """Başına dolgu gelen ilk sözcüğün baş harfi küçültülsün mü? Özel ad belirtisi varsa hayır: tamamı büyük
    (kısaltma), içinde büyük harf (iPhone), kesmeli ek (İstanbul'a) ya da metinde cümle ortasında aynı biçimde
    geçmesi (Ahmet … Ahmet)."""
    if not word[:1].isupper():
        return False
    letters = [c for c in word if c.isalpha()]
    if len(letters) >= 2 and all(c.isupper() for c in letters):
        return False
    if any(c.isupper() for c in word[1:]) or "'" in word or "’" in word:
        return False
    for m in re.finditer(rf"(?<![\w]){re.escape(word)}(?![\w])", text):
        if m.start() == pos or (m.start() and text[m.start() - 1] in _OPENERS):
            continue                              # tırnak / parantez içinin ilk sözcüğü cümle başı gibidir
        if _prev_kind(text, m.start()) in ("word", "clause"):
            return False
    return True


def _filler_word(f: str) -> str:
    return tr_lower(f.strip(" ,"))


def _analyze(text: str, masked: str, a: int, b: int) -> dict:
    """Cümlenin dolgu seçenekleri: başlangıç konumu, uygun virgüller, son konumu; zaten dolgu var mı."""
    seg = masked[a:b]
    words = _TOKEN_RE.findall(seg)
    info: dict = {"words": len(words), "filler": False, "start": None, "lower": None, "commas": [], "end": None}
    if not words:
        return info
    line_first = not text[text.rfind("\n", 0, a) + 1:a].strip()
    if line_first:
        p, sep = _strip_line_prefix(text, a, b, _FILLER_LEAD_RE)
        start_ok = sep != "-"            # "AYŞE — …" / "Ali - …": ad mı sözcük mü belirsiz → başa ekleme
    else:
        p, start_ok = _FILLER_LEAD_RE.match(text, a, b).end(), True

    # --- zaten dolgu var mı (ikinci uygulama bu cümleye eklemez) ---
    fm = _START_FILLER_RE.match(masked, p, b)
    if fm:
        w = tr_lower(fm.group("w"))
        if (w in _FILLER_WORDS and fm.group("comma")) or w in _FILLER_NOCOMMA:
            info["filler"] = True
    for cm in re.finditer(r",[ \t]+([^\W\d_]+)", seg):
        if tr_lower(cm.group(1)) in ("yani", "işte"):
            info["filler"] = True
    em = _END_RE.search(seg)
    if em and tr_lower(em.group(1)) in ("ya", "yani", "işte"):
        info["filler"] = True
    if info["filler"] or len(words) < 2:
        return info

    # --- cümle başı ---
    if start_ok and p < b:
        wm = _WORD_AT_RE.match(text, p, b) if masked[p] != _MASK else None
        if not (wm and tr_lower(wm.group()) in _NO_START_WORDS):
            info["start"] = p
            if wm and _should_lower(wm.group(), text, p):
                info["lower"] = p

    # --- virgülden sonra (sayı listesi ve "elma, armut, muz" gibi sıralamalar hariç) ---
    commas = [a + m.start() for m in _COMMA_RE.finditer(seg)]
    all_commas = [a + i for i, c in enumerate(seg) if c == ","]
    for ci in commas:
        if ci <= p or not text[ci - 1].isalpha():
            continue
        pw = _PREV_WORD_RE.search(text, p, ci)
        if pw and tr_lower(pw.group(1)) in _GREETINGS:
            continue
        prev_c = max((c for c in all_commas if c < ci), default=None)
        next_c = min((c for c in all_commas if c > ci), default=None)
        if prev_c is not None and len(_TOKEN_RE.findall(masked[prev_c:ci])) <= 2:
            continue
        if next_c is not None and len(_TOKEN_RE.findall(masked[ci:next_c])) <= 2:
            continue
        nw = _NEXT_WORD_RE.match(masked, ci + 1, b)
        if nw and tr_lower(nw.group(1)) in _AFTER_COMMA_SKIP:
            continue
        info["commas"].append(ci + 1)

    # --- cümle sonu: yalnız tek "." ya da "!" ile biten düz cümle (soru, üç nokta, tırnakla biten değil) ---
    if em:
        punct, last_word = em.group(2), tr_lower(em.group(1))
        if (punct == "." or set(punct) == {"!"}) and last_word not in _NO_END_WORDS \
                and not _QUESTION_PARTICLE_RE.fullmatch(last_word):
            info["end"] = a + em.start(2)
    return info


def add_fillers(text: str, rate: float = 0.08, seed: int | None = None, style: str = "sohbet") -> str:
    """Konuşma dolguları ekler ("Yani, …", "…, işte …", "… ya.") — doğal, sohbet havasında okuma için.

    * Konumlar: cümle başı ``FILLERS_START``; virgülden sonra ``FILLERS_COMMA``; cümle sonu ``FILLERS_END`` (yalnız
      tek "." ya da "!" ile biten düz cümle; soruya, "..."ya, tırnakla biten cümleye değil).
    * Miktar: dolgulu cümle sayısı ≈ ``rate`` × cümle sayısı (olasılıklı yuvarlama; metinde zaten olan dolgular da
      sayılır) ve her ``FILLER_MIN_GAP`` (4) ardışık cümlede en çok bir dolgu. Aynı dolgu art arda gelmez.
    * ``seed`` verilirse sonuç belirlenimcidir. ``rate`` ≤ 0 → metin değişmez.
    * Haber, belgesel, sesli kitap, eğitim, müşteri hizmeti ve anlatıcı stillerinde hiç eklenmez
      (``NO_FILLER_STYLES``; "Sesli Kitap", "audiobook" gibi eş adlar da tanınır).
    * Köşeli parantez etiketlerinin ve tırnakların içine dokunulmaz; konuşmacı adından ("Ayşe:") sonra eklenir.
    * İdempotent değildir ama ikinci uygulama dolgu içeren cümleye (başı "Yani,/Hani,/İşte,/Şey,/Ya,/Bak,/Valla,"
      olan, virgülden sonra "yani/işte" geçen ya da "ya/yani/işte" ile biten) yeniden eklemez.
    """
    if not isinstance(text, str) or not text.strip():
        return text
    try:
        r = float(rate)
    except (TypeError, ValueError):
        return text
    if not math.isfinite(r) or r <= 0:
        return text
    r = min(r, 1.0)
    if _style_name(style) in NO_FILLER_STYLES:
        return text

    masked = _mask(text)
    infos = [info for a, b in _sentence_spans(text, masked) if (info := _analyze(text, masked, a, b))["words"]]
    n = len(infos)
    if not n:
        return text
    rng = random.Random(seed)
    existing = [i for i, s in enumerate(infos) if s["filler"]]
    budget = math.floor(r * n + rng.random()) - len(existing)
    if budget <= 0:
        return text
    candidates = [i for i, s in enumerate(infos)
                  if not s["filler"] and (s["start"] is not None or s["commas"] or s["end"] is not None)]
    rng.shuffle(candidates)
    taken = list(existing)
    chosen: list[int] = []
    for i in candidates:
        if len(chosen) >= budget:
            break
        if all(abs(i - j) >= FILLER_MIN_GAP for j in taken):
            chosen.append(i)
            taken.append(i)
    if not chosen:
        return text

    edits: list[tuple[int, int, str]] = []
    last_word: str | None = None
    for i in sorted(chosen):
        s = infos[i]
        kinds = [k for k, ok in (("start", s["start"] is not None), ("comma", bool(s["commas"])),
                                 ("end", s["end"] is not None)) if ok]
        kind = rng.choice(kinds)
        pool = {"start": FILLERS_START, "comma": FILLERS_COMMA, "end": FILLERS_END}[kind]
        filler = rng.choice([f for f in pool if _filler_word(f) != last_word] or list(pool))
        last_word = _filler_word(filler)
        if kind == "start":
            p = s["start"]
            if s["lower"] is not None:
                edits.append((p, p + 1, filler + tr_lower(text[p])))
            else:
                edits.append((p, p, filler))
        elif kind == "comma":
            p = rng.choice(s["commas"])
            edits.append((p, p, filler))
        else:
            edits.append((s["end"], s["end"], filler))
    out = text
    for a, b, rep in sorted(edits, reverse=True):
        out = out[:a] + rep + out[b:]
    return out
