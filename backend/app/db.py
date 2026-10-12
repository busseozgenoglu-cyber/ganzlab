import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DB_PATH


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex[:12]


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db():
    with conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS voices (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                filename TEXT NOT NULL,
                duration REAL NOT NULL,
                language TEXT NOT NULL DEFAULT 'tr',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS voice_samples (
                id TEXT PRIMARY KEY,
                voice_id TEXT NOT NULL,
                emotion TEXT NOT NULL,
                filename TEXT NOT NULL,
                duration REAL NOT NULL,
                created_at TEXT NOT NULL,
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
                created_at TEXT NOT NULL
            );
            """
        )


# ---------- voices ----------

def add_voice(name: str, filename: str, duration: float, language: str) -> dict:
    vid = new_id()
    with conn() as c:
        c.execute(
            "INSERT INTO voices (id, name, filename, duration, language, created_at) VALUES (?,?,?,?,?,?)",
            (vid, name, filename, duration, language, _now()),
        )
    return get_voice(vid)


def list_voices() -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM voices ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_voice(vid: str) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT * FROM voices WHERE id=?", (vid,)).fetchone()
    return dict(r) if r else None


def rename_voice(vid: str, name: str) -> dict | None:
    with conn() as c:
        c.execute("UPDATE voices SET name=? WHERE id=?", (name, vid))
    return get_voice(vid)


def delete_voice(vid: str) -> None:
    with conn() as c:
        c.execute("DELETE FROM voices WHERE id=?", (vid,))


# ---------- generations ----------

def add_generation(**kw) -> dict:
    gid = new_id()
    with conn() as c:
        c.execute(
            """INSERT INTO generations
               (id, kind, text, voice_id, voice_name, language, params, filename, duration, elapsed, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                gid, kw["kind"], kw.get("text"), kw.get("voice_id"), kw.get("voice_name"),
                kw.get("language"), json.dumps(kw.get("params") or {}), kw["filename"],
                kw["duration"], kw["elapsed"], _now(),
            ),
        )
    return get_generation(gid)


def get_generation(gid: str) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT * FROM generations WHERE id=?", (gid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["params"] = json.loads(d["params"] or "{}")
    return d


def list_generations(limit: int = 100) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM generations ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["params"] = json.loads(d["params"] or "{}")
        out.append(d)
    return out


def delete_generation(gid: str) -> None:
    with conn() as c:
        c.execute("DELETE FROM generations WHERE id=?", (gid,))


# ---------- duygu örnekleri ----------

def set_voice_sample(voice_id: str, emotion: str, filename: str, duration: float) -> dict:
    sid = new_id()
    with conn() as c:
        old = c.execute("SELECT filename FROM voice_samples WHERE voice_id=? AND emotion=?", (voice_id, emotion)).fetchone()
        c.execute("DELETE FROM voice_samples WHERE voice_id=? AND emotion=?", (voice_id, emotion))
        c.execute(
            "INSERT INTO voice_samples (id, voice_id, emotion, filename, duration, created_at) VALUES (?,?,?,?,?,?)",
            (sid, voice_id, emotion, filename, duration, _now()),
        )
    d = {"id": sid, "voice_id": voice_id, "emotion": emotion, "filename": filename, "duration": duration}
    d["replaced_filename"] = old["filename"] if old else None
    return d


def list_voice_samples(voice_id: str) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM voice_samples WHERE voice_id=? ORDER BY emotion", (voice_id,)).fetchall()
    return [dict(r) for r in rows]


def delete_voice_sample(voice_id: str, emotion: str) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT * FROM voice_samples WHERE voice_id=? AND emotion=?", (voice_id, emotion)).fetchone()
        c.execute("DELETE FROM voice_samples WHERE voice_id=? AND emotion=?", (voice_id, emotion))
    return dict(r) if r else None


def delete_all_voice_samples(voice_id: str) -> list[dict]:
    rows = list_voice_samples(voice_id)
    with conn() as c:
        c.execute("DELETE FROM voice_samples WHERE voice_id=?", (voice_id,))
    return rows
