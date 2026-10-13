"""SQLite kalıcılık katmanı: sesler, duygu örnekleri ve üretim geçmişi.

- Her çağrı kendi kısa ömürlü bağlantısını açar; bağlantılar iş parçacıkları arasında paylaşılmaz.
- Veritabanı WAL kipindedir: API iş parçacığı ile kuyruk işçisi aynı anda okuyup yazabilir (kilitliyse 10 sn bekler).
- Şema göçü `init_db()` içindedir: eski sürümün veritabanında eksik sütunlar `PRAGMA table_info` ile bulunur ve
  `ALTER TABLE ... ADD COLUMN` ile eklenir. Yeni sütun eklerken hem `_SCHEMA`'ya hem `_COLUMNS`'a yazın.
- JSON alanları (analysis, params) okunurken çözülür; bozuk JSON uygulamayı çökertmez (None / {} döner).
- Metin araması Türkçe büyük/küçük harf duyarsızdır: SQLite'a `tr_lower` fonksiyonu kaydedilir (İ→i, I→ı).
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import DB_PATH, SUPPORTED_LANGUAGES
from .tr import tr_lower

log = logging.getLogger("sesklon.db")

PAUSE_SCALE_MIN, PAUSE_SCALE_MAX = 0.5, 2.0     # sese özgü duraklama çarpanı sınırları (API pause_scale ile aynı)
VOICE_FIELDS = ("name", "notes", "default_style", "pause_scale", "language")   # update_voice ile değişebilen alanlar
_INT64_MIN, _INT64_MAX = -(2 ** 63), 2 ** 63 - 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex[:12]


# ---------- bağlantı ----------

def _sql_tr_lower(s: Any) -> str | None:
    """SQL içinde `tr_lower(sütun)`: Türkçe'ye uygun küçük harf. NULL → NULL."""
    if s is None:
        return None
    return tr_lower(s if isinstance(s, str) else str(s))


def _connect() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA synchronous=NORMAL")      # bağlantı başına geçerlidir; WAL ile güvenli ve hızlı
    try:
        c.create_function("tr_lower", 1, _sql_tr_lower, deterministic=True)
    except sqlite3.NotSupportedError:           # çok eski SQLite: deterministic bayrağı yok
        c.create_function("tr_lower", 1, _sql_tr_lower)
    return c


@contextmanager
def conn(immediate: bool = False) -> Iterator[sqlite3.Connection]:
    """Kısa ömürlü bağlantı; hatasız çıkışta commit, hatada geri alma.

    immediate=True: yazma kilidini en başta alır (önce okuyup sonra yazan işlemler arada başka yazarla
    karışmasın diye).
    """
    c = _connect()
    try:
        if immediate:
            c.execute("BEGIN IMMEDIATE")
        yield c
        c.commit()
    finally:
        c.close()                               # commit edilmemiş değişiklik kapanışta geri alınır


# ---------- şema ve göç ----------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS voices (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    filename TEXT NOT NULL,
    duration REAL NOT NULL,
    language TEXT NOT NULL DEFAULT 'tr',
    created_at TEXT NOT NULL,
    analysis TEXT,                 -- json: referans kaydı analizi (analysis.py şeması)
    notes TEXT,
    default_style TEXT,            -- styles.py anahtarı
    pause_scale REAL               -- kişinin duraklama çarpanı (analizden ya da elle)
);
CREATE TABLE IF NOT EXISTS voice_samples (
    id TEXT PRIMARY KEY,
    voice_id TEXT NOT NULL,
    emotion TEXT NOT NULL,
    filename TEXT NOT NULL,
    duration REAL NOT NULL,
    created_at TEXT NOT NULL,
    analysis TEXT,                 -- json
    UNIQUE(voice_id, emotion)
);
CREATE TABLE IF NOT EXISTS generations (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,            -- tts | vc
    text TEXT,
    voice_id TEXT,
    voice_name TEXT,
    language TEXT,
    params TEXT,                   -- json
    filename TEXT NOT NULL,
    duration REAL NOT NULL,
    elapsed REAL NOT NULL,
    created_at TEXT NOT NULL,
    seed INTEGER,
    group_id TEXT,                 -- varyant grubu (aynı istekten farklı tohumlarla üretilenler)
    favorite INTEGER DEFAULT 0
);
"""

# Eski veritabanlarına sonradan eklenen sütunlar: tablo → [(sütun, tanım)].
_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "voices": [("analysis", "TEXT"), ("notes", "TEXT"), ("default_style", "TEXT"), ("pause_scale", "REAL")],
    "voice_samples": [("analysis", "TEXT")],
    "generations": [("seed", "INTEGER"), ("group_id", "TEXT"), ("favorite", "INTEGER DEFAULT 0")],
}

# İndeksler göçten SONRA kurulur (group_id eski tabloda göçle gelir).
_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_generations_created ON generations(created_at);
CREATE INDEX IF NOT EXISTS idx_generations_voice ON generations(voice_id);
CREATE INDEX IF NOT EXISTS idx_generations_group ON generations(group_id);
CREATE INDEX IF NOT EXISTS idx_voice_samples_voice ON voice_samples(voice_id);
"""


def _migrate(c: sqlite3.Connection) -> list[str]:
    """Eksik sütunları ekler; eklenenlerin listesini döndürür."""
    added = []
    for table, cols in _COLUMNS.items():
        have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
        for name, decl in cols:
            if name in have:
                continue
            try:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
                added.append(f"{table}.{name}")
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():   # başka bir süreç aynı anda eklemiş olabilir
                    raise
    return added


def init_db() -> None:
    """Tabloları kurar, eski şemayı günceller, indeksleri ve WAL kipini ayarlar. Tekrar çağrılabilir."""
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with conn() as c:
        try:
            mode = c.execute("PRAGMA journal_mode=WAL").fetchone()[0]   # kalıcıdır: dosyaya bir kez yazılır
            if str(mode).lower() != "wal":
                log.warning("SQLite WAL kipine geçilemedi (kip: %s); varsayılan günlükle devam ediliyor", mode)
        except sqlite3.DatabaseError as e:
            log.warning("SQLite WAL kipi ayarlanamadı: %s", e)
        c.executescript(_SCHEMA)
        added = _migrate(c)
        c.executescript(_INDEXES)
    if added:
        log.info("Veritabanı şeması güncellendi, eklenen sütunlar: %s", ", ".join(added))


# ---------- JSON / değer yardımcıları ----------

def _clean(o: Any) -> Any:
    """JSON'a güvenle yazılabilir yapı: numpy sayı/dizileri → Python, NaN/sonsuz → None, bilinmeyen → str."""
    if o is None or isinstance(o, (bool, int, str)):
        return o
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set, frozenset)):
        return [_clean(v) for v in o]
    if hasattr(o, "tolist"):                    # numpy skaler / dizi
        return _clean(o.tolist())
    return str(o)


def _dumps(o: Any) -> str:
    return json.dumps(_clean(o), ensure_ascii=False, allow_nan=False)


def _dumps_or_none(o: Any) -> str | None:
    return None if o is None else _dumps(o)


def _loads(s: Any) -> Any:
    if not s:
        return None
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        log.warning("Bozuk JSON alanı yok sayıldı: %.80r", s)
        return None


def _loads_dict(s: Any) -> dict | None:
    v = _loads(s)
    return v if isinstance(v, dict) else None


def _as_int(v: Any) -> int | None:
    """Tohum gibi tam sayı alanları: çevrilemiyorsa ya da 64 bite sığmıyorsa None."""
    if v is None or isinstance(v, bool):
        return None
    try:
        i = int(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return i if _INT64_MIN <= i <= _INT64_MAX else None


def _pause_scale_of(analysis: Any) -> float | None:
    """Analizdeki pauses.scale (PAUSE_SCALE_MIN–MAX aralığına sıkıştırılmış) ya da None."""
    pauses = analysis.get("pauses") if isinstance(analysis, dict) else None
    if not isinstance(pauses, dict):
        return None
    try:
        v = float(pauses.get("scale"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v <= 0:
        return None
    return round(min(PAUSE_SCALE_MAX, max(PAUSE_SCALE_MIN, v)), 3)


def _like_pattern(q: str) -> str:
    """Aramayı LIKE desenine çevirir: Türkçe küçük harf; % ve _ joker değil düz karakterdir."""
    s = tr_lower(q).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{s}%"


# ---------- voices ----------

def _voice_row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    d["analysis"] = _loads_dict(d.get("analysis"))
    ps = d.get("pause_scale")
    d["pause_scale"] = float(ps) if ps is not None else None
    return d


def add_voice(name: str, filename: str, duration: float, language: str, analysis: dict | None = None) -> dict:
    vid = new_id()
    with conn() as c:
        c.execute(
            """INSERT INTO voices (id, name, filename, duration, language, created_at, analysis, pause_scale)
               VALUES (?,?,?,?,?,?,?,?)""",
            (vid, name, filename, float(duration), language, _now(), _dumps_or_none(analysis),
             _pause_scale_of(analysis)),
        )
    return get_voice(vid)


def list_voices() -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM voices ORDER BY created_at DESC").fetchall()
    return [_voice_row(r) for r in rows]


def get_voice(vid: str) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT * FROM voices WHERE id=?", (vid,)).fetchone()
    return _voice_row(r)


def rename_voice(vid: str, name: str) -> dict | None:
    with conn() as c:
        c.execute("UPDATE voices SET name=? WHERE id=?", (name, vid))
    return get_voice(vid)


def _voice_value(key: str, value: Any) -> Any:
    """update_voice alan doğrulaması; geçersizse ValueError (Türkçe ileti)."""
    if key == "name":
        name = str(value or "").strip()
        if not name:
            raise ValueError("Ses adı boş olamaz")
        return name
    if key == "language":
        if value not in SUPPORTED_LANGUAGES:
            raise ValueError(f"Desteklenmeyen dil: {value}")
        return value
    if key == "pause_scale":
        if value is None:
            return None
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise ValueError("pause_scale bir sayı olmalı") from None
        if not PAUSE_SCALE_MIN <= v <= PAUSE_SCALE_MAX:   # NaN da burada elenir
            raise ValueError(f"pause_scale {PAUSE_SCALE_MIN}–{PAUSE_SCALE_MAX} arasında olmalı")
        return v
    # notes, default_style: boş metin → NULL
    if value is None:
        return None
    return str(value).strip() or None


def update_voice(vid: str, **fields: Any) -> dict | None:
    """Sesin izinli alanlarını günceller (VOICE_FIELDS). Bilinmeyen alan ya da geçersiz değer → ValueError.

    Dönüş: güncel ses sözlüğü; ses yoksa None. Alan verilmezse yalnızca mevcut kaydı döndürür.
    """
    unknown = sorted(set(fields) - set(VOICE_FIELDS))
    if unknown:
        raise ValueError(f"Güncellenemeyen alan: {', '.join(unknown)} (izinli: {', '.join(VOICE_FIELDS)})")
    values = {k: _voice_value(k, v) for k, v in fields.items()}
    if values:
        sets = ", ".join(f"{k}=?" for k in values)       # anahtarlar VOICE_FIELDS'tan; enjeksiyon yok
        with conn() as c:
            c.execute(f"UPDATE voices SET {sets} WHERE id=?", (*values.values(), vid))
    return get_voice(vid)


def set_voice_notes(vid: str, notes: str | None) -> dict | None:
    return update_voice(vid, notes=notes)


def set_voice_default_style(vid: str, style: str | None) -> dict | None:
    return update_voice(vid, default_style=style)


def set_voice_analysis(vid: str, analysis: dict | None) -> None:
    """Sesin analizini yazar (None → siler). Analizde pauses.scale varsa voices.pause_scale de güncellenir."""
    ps = _pause_scale_of(analysis)
    with conn() as c:
        if ps is None:
            c.execute("UPDATE voices SET analysis=? WHERE id=?", (_dumps_or_none(analysis), vid))
        else:
            c.execute("UPDATE voices SET analysis=?, pause_scale=? WHERE id=?", (_dumps_or_none(analysis), ps, vid))


def delete_voice(vid: str) -> None:
    with conn() as c:
        c.execute("DELETE FROM voices WHERE id=?", (vid,))


def export_voice_bundle(vid: str) -> dict | None:
    """Dışa aktarma paketi: ses kaydı + duygu örnekleri + analizler ve paketlenecek dosya adları.

    Dosyalar `config.VOICES_DIR` altındadır; zip/indirme API katmanında yapılır. Ses yoksa None.
    """
    with conn() as c:
        c.execute("BEGIN")                      # iki okuma aynı anlık görüntüden
        v = c.execute("SELECT * FROM voices WHERE id=?", (vid,)).fetchone()
        rows = c.execute("SELECT * FROM voice_samples WHERE voice_id=? ORDER BY emotion", (vid,)).fetchall()
    if v is None:
        return None
    voice = _voice_row(v)
    samples = [_sample_row(r) for r in rows]
    return {
        "format": "sesklon-voice",
        "version": 1,
        "exported_at": _now(),
        "voice": voice,
        "samples": samples,
        "files": [voice["filename"], *(s["filename"] for s in samples)],
    }


# ---------- generations ----------

def _gen_row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    p = _loads(d.get("params"))
    d["params"] = p if p is not None else {}
    d["favorite"] = bool(d.get("favorite") or 0)
    return d


def add_generation(**kw: Any) -> dict:
    """Zorunlu: kind, filename, duration, elapsed. İsteğe bağlı: text, voice_id, voice_name, language, params,
    seed, group_id, favorite (eksikler None). seed verilmezse params["seed"] kullanılır."""
    gid = new_id()
    params = kw.get("params") or {}
    seed = kw.get("seed")
    if seed is None and isinstance(params, dict):
        seed = params.get("seed")
    with conn() as c:
        c.execute(
            """INSERT INTO generations
               (id, kind, text, voice_id, voice_name, language, params, filename, duration, elapsed, created_at,
                seed, group_id, favorite)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                gid, kw["kind"], kw.get("text"), kw.get("voice_id"), kw.get("voice_name"),
                kw.get("language"), _dumps(params), kw["filename"],
                float(kw["duration"]), float(kw["elapsed"]), _now(),
                _as_int(seed), kw.get("group_id"), 1 if kw.get("favorite") else 0,
            ),
        )
    return get_generation(gid)


def get_generation(gid: str) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT * FROM generations WHERE id=?", (gid,)).fetchone()
    return _gen_row(r)


def _gen_where(kind: str | None = None, voice_id: str | None = None, q: str | None = None,
               favorite: bool | None = None, group_id: str | None = None) -> tuple[str, list]:
    clauses: list[str] = []
    args: list[Any] = []
    if kind:
        clauses.append("kind=?")
        args.append(kind)
    if voice_id:
        clauses.append("voice_id=?")
        args.append(voice_id)
    if group_id:
        clauses.append("group_id=?")
        args.append(group_id)
    if favorite is not None:
        clauses.append("COALESCE(favorite, 0)=?")
        args.append(1 if favorite else 0)
    q = (q or "").strip()
    if q:
        clauses.append(
            "(tr_lower(COALESCE(text, '')) LIKE ? ESCAPE '\\' OR tr_lower(COALESCE(voice_name, '')) LIKE ? ESCAPE '\\')"
        )
        pat = _like_pattern(q)
        args += [pat, pat]
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", args


def list_generations(limit: int | None = 100, offset: int = 0, kind: str | None = None, voice_id: str | None = None,
                     q: str | None = None, favorite: bool | None = None, group_id: str | None = None) -> list[dict]:
    """Geçmiş, yeniden eskiye. q: metin ve ses adında Türkçe büyük/küçük harf duyarsız arama. limit=None → sınırsız."""
    where, args = _gen_where(kind, voice_id, q, favorite, group_id)
    lim = -1 if limit is None else max(0, int(limit))
    off = max(0, int(offset or 0))
    with conn() as c:
        rows = c.execute(
            f"SELECT * FROM generations{where} ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
            (*args, lim, off),
        ).fetchall()
    return [_gen_row(r) for r in rows]


def count_generations(kind: str | None = None, voice_id: str | None = None, q: str | None = None,
                      favorite: bool | None = None, group_id: str | None = None) -> int:
    """list_generations ile aynı süzgeçlerle toplam kayıt sayısı (sayfalama için)."""
    where, args = _gen_where(kind, voice_id, q, favorite, group_id)
    with conn() as c:
        return int(c.execute(f"SELECT COUNT(*) FROM generations{where}", args).fetchone()[0])


def set_generation_favorite(gid: str, favorite: bool = True) -> dict | None:
    with conn() as c:
        c.execute("UPDATE generations SET favorite=? WHERE id=?", (1 if favorite else 0, gid))
    return get_generation(gid)


def list_group(group_id: str) -> list[dict]:
    """Bir varyant grubunun üretimleri, üretim sırasıyla (ilk = ana sonuç)."""
    if not group_id:
        return []
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM generations WHERE group_id=? ORDER BY created_at ASC, rowid ASC", (group_id,)
        ).fetchall()
    return [_gen_row(r) for r in rows]


def delete_generation(gid: str) -> None:
    with conn() as c:
        c.execute("DELETE FROM generations WHERE id=?", (gid,))


def stats() -> dict:
    """Arayüz istatistik rozetleri.

    voices / samples / generations / favorites: sayılar; by_kind: {"tts": n, "vc": n};
    total_duration_s: üretilen toplam ses süresi; total_elapsed_s: üretime harcanan toplam süre;
    rtf: gerçek zaman çarpanı (harcanan / üretilen; <1 → gerçek zamandan hızlı), üretim yoksa None.
    """
    with conn() as c:
        c.execute("BEGIN")
        voices = c.execute("SELECT COUNT(*) FROM voices").fetchone()[0]
        samples = c.execute("SELECT COUNT(*) FROM voice_samples").fetchone()[0]
        g = c.execute(
            "SELECT COUNT(*), COALESCE(SUM(duration), 0), COALESCE(SUM(elapsed), 0), "
            "COALESCE(SUM(COALESCE(favorite, 0)), 0) FROM generations"
        ).fetchone()
        kinds = c.execute("SELECT kind, COUNT(*) FROM generations GROUP BY kind ORDER BY kind").fetchall()
    total_duration, total_elapsed = float(g[1]), float(g[2])
    return {
        "voices": int(voices),
        "samples": int(samples),
        "generations": int(g[0]),
        "favorites": int(g[3]),
        "by_kind": {k: int(n) for k, n in kinds},
        "total_duration_s": round(total_duration, 2),
        "total_elapsed_s": round(total_elapsed, 2),
        "rtf": round(total_elapsed / total_duration, 3) if total_duration > 0 else None,
    }


# ---------- duygu örnekleri ----------

def _sample_row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    d["analysis"] = _loads_dict(d.get("analysis"))
    return d


def set_voice_sample(voice_id: str, emotion: str, filename: str, duration: float,
                     analysis: dict | None = None) -> dict:
    """Sesin bu duygu için örneğini yazar (varsa değiştirir). replaced_filename: silinmesi gereken eski dosya."""
    sid, now, aj = new_id(), _now(), _dumps_or_none(analysis)
    with conn(immediate=True) as c:
        old = c.execute("SELECT filename FROM voice_samples WHERE voice_id=? AND emotion=?", (voice_id, emotion)).fetchone()
        c.execute("DELETE FROM voice_samples WHERE voice_id=? AND emotion=?", (voice_id, emotion))
        c.execute(
            """INSERT INTO voice_samples (id, voice_id, emotion, filename, duration, created_at, analysis)
               VALUES (?,?,?,?,?,?,?)""",
            (sid, voice_id, emotion, filename, float(duration), now, aj),
        )
    return {
        "id": sid, "voice_id": voice_id, "emotion": emotion, "filename": filename, "duration": float(duration),
        "created_at": now, "analysis": _loads_dict(aj),
        "replaced_filename": old["filename"] if old else None,
    }


def set_sample_analysis(sid: str, analysis: dict | None) -> None:
    with conn() as c:
        c.execute("UPDATE voice_samples SET analysis=? WHERE id=?", (_dumps_or_none(analysis), sid))


def list_voice_samples(voice_id: str) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM voice_samples WHERE voice_id=? ORDER BY emotion", (voice_id,)).fetchall()
    return [_sample_row(r) for r in rows]


def delete_voice_sample(voice_id: str, emotion: str) -> dict | None:
    with conn(immediate=True) as c:
        r = c.execute("SELECT * FROM voice_samples WHERE voice_id=? AND emotion=?", (voice_id, emotion)).fetchone()
        c.execute("DELETE FROM voice_samples WHERE voice_id=? AND emotion=?", (voice_id, emotion))
    return _sample_row(r)


def delete_all_voice_samples(voice_id: str) -> list[dict]:
    """Sesin tüm örneklerini siler; silinen kayıtları (dosya adlarıyla) döndürür."""
    with conn(immediate=True) as c:
        rows = c.execute("SELECT * FROM voice_samples WHERE voice_id=? ORDER BY emotion", (voice_id,)).fetchall()
        c.execute("DELETE FROM voice_samples WHERE voice_id=?", (voice_id,))
    return [_sample_row(r) for r in rows]
