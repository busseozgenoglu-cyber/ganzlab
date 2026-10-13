"""db.py (şema göçü, analiz, geçmiş süzgeçleri, istatistik) ve jobs.py (iptal, ara parça, eta, sıra) testleri."""
import json
import sqlite3
import threading
import time
from contextlib import closing

import numpy as np
import pytest

from app import db
from app.jobs import FINISHED, Job, JobCancelled, JobQueue, get_queue

# ---------- yardımcılar ----------

# v2 sürümünün şeması (analysis/seed/group_id/favorite... sütunları yok) — göç testi için.
OLD_SCHEMA = """
CREATE TABLE voices (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, filename TEXT NOT NULL, duration REAL NOT NULL,
    language TEXT NOT NULL DEFAULT 'tr', created_at TEXT NOT NULL
);
CREATE TABLE voice_samples (
    id TEXT PRIMARY KEY, voice_id TEXT NOT NULL, emotion TEXT NOT NULL, filename TEXT NOT NULL,
    duration REAL NOT NULL, created_at TEXT NOT NULL, UNIQUE(voice_id, emotion)
);
CREATE TABLE generations (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, text TEXT, voice_id TEXT, voice_name TEXT, language TEXT,
    params TEXT, filename TEXT NOT NULL, duration REAL NOT NULL, elapsed REAL NOT NULL, created_at TEXT NOT NULL
);
INSERT INTO voices VALUES ('v1', 'Eski ses', 'v1.wav', 9.5, 'tr', '2025-01-01T00:00:00+00:00');
INSERT INTO voice_samples VALUES ('s1', 'v1', 'üzgün', 's1.wav', 4.0, '2025-01-01T00:00:01+00:00');
INSERT INTO generations VALUES ('g1', 'tts', 'Eski kayıt', 'v1', 'Eski ses', 'tr', '{"seed": 5}', 'g1.wav',
                                2.0, 1.0, '2025-01-01T00:00:02+00:00');
"""

NEW_COLUMNS = {
    "voices": {"analysis", "notes", "default_style", "pause_scale"},
    "voice_samples": {"analysis"},
    "generations": {"seed", "group_id", "favorite"},
}
INDEXES = {"idx_generations_created", "idx_generations_voice", "idx_generations_group", "idx_voice_samples_voice"}


@pytest.fixture()
def tdb(tmp_path, monkeypatch):
    """Her test için ayrı, boş veritabanı (test_api'nin paylaşılan veritabanına dokunmaz)."""
    path = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()
    return path


def _columns(path, table):
    with closing(sqlite3.connect(path)) as c:
        return {r[1] for r in c.execute(f"PRAGMA table_info({table})")}


def _indexes(path):
    with closing(sqlite3.connect(path)) as c:
        return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}


def _journal_mode(path):
    with closing(sqlite3.connect(path)) as c:
        return c.execute("PRAGMA journal_mode").fetchone()[0]


def _gen(**kw):
    base = dict(kind="tts", text="Merhaba dünya", voice_id=None, voice_name="Varsayılan ses", language="tr",
                params={}, filename=f"{db.new_id()}.wav", duration=1.0, elapsed=0.5)
    base.update(kw)
    return db.add_generation(**base)


def _wait(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.005)
    return pred()


def _blocker(started: threading.Event, release: threading.Event):
    """Bırakılana kadar işçiyi meşgul eden iş."""
    def fn(job):
        started.set()
        release.wait(5)
        return {"ok": True}
    return fn


# ---------- db: şema ve göç ----------

def test_init_db_idempotent_with_wal_and_indexes(tdb):
    db.init_db()
    db.init_db()                                     # tekrar çağrılabilir
    for table, cols in NEW_COLUMNS.items():
        assert cols <= _columns(tdb, table), table
    assert INDEXES <= _indexes(tdb)
    assert _journal_mode(tdb) == "wal"


def test_old_schema_is_migrated(tmp_path, monkeypatch):
    path = tmp_path / "eski.db"
    with closing(sqlite3.connect(path)) as c:
        c.executescript(OLD_SCHEMA)
        c.commit()
    assert "analysis" not in _columns(path, "voices")
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()
    for table, cols in NEW_COLUMNS.items():
        assert cols <= _columns(path, table), table
    assert INDEXES <= _indexes(path)                 # group_id indeksi göçten sonra kurulabildi
    assert _journal_mode(path) == "wal"

    # eski kayıtlar yeni alanlarla okunur
    v = db.get_voice("v1")
    assert v["name"] == "Eski ses" and v["analysis"] is None and v["pause_scale"] is None and v["notes"] is None
    assert db.list_voice_samples("v1")[0]["analysis"] is None
    g = db.get_generation("g1")
    assert g["favorite"] is False and g["group_id"] is None and g["seed"] is None and g["params"] == {"seed": 5}

    # yeni özellikler göç edilmiş veritabanında çalışır
    db.set_voice_analysis("v1", {"pauses": {"scale": 1.1}})
    assert db.get_voice("v1")["pause_scale"] == 1.1
    _gen(group_id="grp", seed=3)
    assert [x["seed"] for x in db.list_generations(group_id="grp")] == [3]
    db.init_db()                                     # ikinci göç denemesi sorunsuz
    assert db.count_generations() == 2


# ---------- db: sesler ----------

def test_voice_analysis_roundtrip_and_sanitizing(tdb):
    v = db.add_voice("Ayşe", "a.wav", 9.0, "tr")
    assert v["analysis"] is None and v["pause_scale"] is None
    analysis = {
        "duration": np.float32(9.5), "snr_db": float("nan"), "f0": {"median_hz": np.float64(181.25)},
        "breaths": {"count": np.int64(2), "positions_s": np.array([3.5, 7.25])},
        "pauses": {"count": 4, "scale": np.float32(1.25)}, "grade": "iyi", "tips": ["Daha sessiz bir oda seçin"],
    }
    assert db.set_voice_analysis(v["id"], analysis) is None
    got = db.get_voice(v["id"])
    a = got["analysis"]
    assert isinstance(a, dict) and a["grade"] == "iyi"
    assert a["snr_db"] is None                       # NaN → None (JSON yanıtı bozulmasın)
    assert a["breaths"] == {"count": 2, "positions_s": [3.5, 7.25]}
    assert a["duration"] == 9.5 and a["f0"]["median_hz"] == 181.25
    assert isinstance(got["pause_scale"], float) and got["pause_scale"] == 1.25
    assert db.list_voices()[0]["analysis"]["tips"] == ["Daha sessiz bir oda seçin"]

    db.set_voice_analysis(v["id"], {"pauses": {"scale": 9}})       # aralık dışı → sıkıştırılır
    assert db.get_voice(v["id"])["pause_scale"] == db.PAUSE_SCALE_MAX
    db.set_voice_analysis(v["id"], None)                            # analiz silinir, çarpan kalır
    assert db.get_voice(v["id"])["analysis"] is None
    assert db.get_voice(v["id"])["pause_scale"] == db.PAUSE_SCALE_MAX

    v2 = db.add_voice("Mehmet", "m.wav", 8.0, "tr", analysis={"pauses": {"scale": 0.8}})
    assert v2["analysis"] == {"pauses": {"scale": 0.8}} and v2["pause_scale"] == 0.8


def test_update_voice_and_helpers(tdb):
    vid = db.add_voice("Eski ad", "x.wav", 8.0, "tr")["id"]
    v = db.update_voice(vid, name="  Yeni ad ", notes="  Sıcak, samimi  ", default_style="anlatıcı",
                        pause_scale=1.2, language="en")
    assert (v["name"], v["notes"], v["default_style"], v["pause_scale"], v["language"]) == \
        ("Yeni ad", "Sıcak, samimi", "anlatıcı", 1.2, "en")
    assert db.update_voice(vid) == v                 # alan yoksa değişiklik yok
    for bad in ({"analysis": {}}, {"id": "x"}, {"filename": "y.wav"}):
        with pytest.raises(ValueError):
            db.update_voice(vid, **bad)
    with pytest.raises(ValueError):
        db.update_voice(vid, name="   ")
    with pytest.raises(ValueError):
        db.update_voice(vid, language="xx")
    with pytest.raises(ValueError):
        db.update_voice(vid, pause_scale=5)
    with pytest.raises(ValueError):
        db.update_voice(vid, pause_scale="hızlı")
    assert db.get_voice(vid) == v                    # başarısız güncellemeler kaydı bozmadı
    assert db.set_voice_notes(vid, "")["notes"] is None
    assert db.set_voice_default_style(vid, None)["default_style"] is None
    assert db.update_voice(vid, pause_scale=None)["pause_scale"] is None
    assert db.rename_voice(vid, "Üçüncü ad")["name"] == "Üçüncü ad"
    assert db.update_voice("yok", notes="x") is None


def test_voice_samples_with_analysis(tdb):
    vid = db.add_voice("Ses", "v.wav", 8.0, "tr")["id"]
    s1 = db.set_voice_sample(vid, "üzgün", "a.wav", 3.0)          # eski çağrı biçimi
    assert s1["analysis"] is None and s1["replaced_filename"] is None
    s2 = db.set_voice_sample(vid, "üzgün", "b.wav", 4.0, analysis={"grade": "orta"})
    assert s2["replaced_filename"] == "a.wav" and s2["analysis"] == {"grade": "orta"}
    db.set_voice_sample(vid, "heyecanlı", "c.wav", 5.0)
    db.set_sample_analysis(s2["id"], {"grade": "iyi", "quality_score": 77})
    samples = db.list_voice_samples(vid)
    assert [s["emotion"] for s in samples] == ["heyecanlı", "üzgün"]
    assert samples[0]["analysis"] is None and samples[1]["analysis"] == {"grade": "iyi", "quality_score": 77}
    rec = db.delete_voice_sample(vid, "üzgün")
    assert rec["filename"] == "b.wav" and rec["analysis"]["grade"] == "iyi"
    assert db.delete_voice_sample(vid, "üzgün") is None
    assert [s["filename"] for s in db.delete_all_voice_samples(vid)] == ["c.wav"]
    assert db.list_voice_samples(vid) == []


# ---------- db: üretim geçmişi ----------

def test_generation_filters_search_and_paging(tdb):
    a = db.add_voice("Işıl", "a.wav", 8.0, "tr")["id"]
    b = db.add_voice("Ömer", "b.wav", 8.0, "tr")["id"]
    texts = ["İSTANBUL'da yağmur var", "ILIK bir rüzgâr esti", "%50 indirim başladı", "alt_çizgi deneme",
             "Sıradan bir cümle"]
    ids = [_gen(text=t, voice_id=(a, b)[i % 2], voice_name=("Işıl", "Ömer")[i % 2])["id"] for i, t in enumerate(texts)]
    ids.append(_gen(kind="vc", text=None, voice_id=b, voice_name="Ömer")["id"])

    assert [g["id"] for g in db.list_generations()] == ids[::-1]   # yeniden eskiye
    page1, page2 = db.list_generations(limit=4, offset=0), db.list_generations(limit=4, offset=4)
    assert len(page1) == 4 and len(page2) == 2
    assert [g["id"] for g in page1 + page2] == ids[::-1]
    assert db.list_generations(limit=10, offset=10) == []

    assert [g["id"] for g in db.list_generations(kind="vc")] == [ids[5]]
    assert db.count_generations(kind="tts") == 5
    assert db.count_generations(voice_id=a) == 3 and db.count_generations(voice_id=b) == 3
    assert db.count_generations(kind="tts", voice_id=b) == 2

    # Türkçe büyük/küçük harf duyarsız arama (İ→i, I→ı)
    assert [g["id"] for g in db.list_generations(q="istanbul")] == [ids[0]]
    assert [g["id"] for g in db.list_generations(q="ılık")] == [ids[1]]
    assert db.list_generations(q="ilik") == []       # ı ≠ i
    assert db.count_generations(q="IŞIL") == 3        # ses adında arama
    assert db.count_generations(q="ömer", kind="vc") == 1
    # joker karakterler düz karakter olarak aranır
    assert [g["id"] for g in db.list_generations(q="%")] == [ids[2]]
    assert [g["id"] for g in db.list_generations(q="_")] == [ids[3]]
    assert db.count_generations(q="   ") == db.count_generations() == 6


def test_generation_seed_group_and_favorite(tdb):
    g1 = _gen(seed=42)
    assert g1["seed"] == 42 and g1["favorite"] is False and g1["group_id"] is None
    assert _gen(params={"seed": 7})["seed"] == 7      # seed verilmezse params'tan
    assert _gen(params={"seed": None})["seed"] is None
    assert _gen(seed=2 ** 70)["seed"] is None          # 64 bite sığmayan tohum kaydı bozmaz

    grp = [_gen(group_id="g1", seed=s) for s in (1, 2, 3)]
    _gen(group_id="g2")
    assert [g["id"] for g in db.list_group("g1")] == [g["id"] for g in grp]   # üretim sırası (ilk = ana sonuç)
    assert [g["seed"] for g in db.list_group("g1")] == [1, 2, 3]
    assert db.count_generations(group_id="g1") == 3 and db.list_group("") == []

    assert db.set_generation_favorite(grp[1]["id"], True)["favorite"] is True
    assert [g["id"] for g in db.list_generations(favorite=True)] == [grp[1]["id"]]
    assert db.count_generations(favorite=False) == db.count_generations() - 1
    assert db.set_generation_favorite(grp[1]["id"], False)["favorite"] is False
    assert db.count_generations(favorite=True) == 0
    assert db.set_generation_favorite("yok", True) is None

    db.delete_generation(grp[0]["id"])
    assert db.get_generation(grp[0]["id"]) is None and len(db.list_group("g1")) == 2


def test_add_generation_backward_compatible(tdb):
    # main.py'nin bugünkü çağrı biçimi: seed/group_id yok
    g = db.add_generation(kind="vc", text=None, voice_id="v", voice_name="Ses", language="tr", params={},
                          filename="x.wav", duration=2.5, elapsed=1.25)
    assert g["params"] == {} and g["seed"] is None and g["favorite"] is False and g["duration"] == 2.5
    assert db.list_generations(5)[0]["id"] == g["id"]                  # limit konumsal
    with pytest.raises(KeyError):
        db.add_generation(kind="tts", filename="y.wav", duration=1.0)   # elapsed zorunlu


def test_stats_and_export_bundle(tdb):
    assert db.stats() == {"voices": 0, "samples": 0, "generations": 0, "favorites": 0, "by_kind": {},
                          "total_duration_s": 0.0, "total_elapsed_s": 0.0, "rtf": None}
    v = db.add_voice("Ayşe", "ayse.wav", 9.0, "tr", analysis={"grade": "iyi", "pauses": {"scale": 1.1}})
    db.set_voice_sample(v["id"], "üzgün", "ayse_uzgun.wav", 4.0, analysis={"grade": "orta"})
    db.set_voice_sample(v["id"], "heyecanlı", "ayse_heyecan.wav", 3.0)
    db.set_generation_favorite(_gen(duration=2.0, elapsed=1.0)["id"], True)
    _gen(duration=3.0, elapsed=2.0)
    _gen(kind="vc", duration=5.0, elapsed=1.0)

    s = db.stats()
    assert (s["voices"], s["samples"], s["generations"], s["favorites"]) == (1, 2, 3, 1)
    assert s["by_kind"] == {"tts": 2, "vc": 1}
    assert s["total_duration_s"] == 10.0 and s["total_elapsed_s"] == 4.0 and s["rtf"] == 0.4

    b = db.export_voice_bundle(v["id"])
    assert b["format"] == "sesklon-voice" and b["voice"]["name"] == "Ayşe"
    assert b["voice"]["analysis"]["grade"] == "iyi" and b["voice"]["pause_scale"] == 1.1
    assert [x["emotion"] for x in b["samples"]] == ["heyecanlı", "üzgün"]
    assert b["samples"][1]["analysis"] == {"grade": "orta"}
    assert b["files"] == ["ayse.wav", "ayse_heyecan.wav", "ayse_uzgun.wav"]
    assert json.loads(json.dumps(b)) == b             # JSON'a yazılabilir
    assert db.export_voice_bundle("yok") is None


def test_concurrent_writes_from_threads(tdb):
    errors = []

    def worker(n):
        try:
            for i in range(15):
                g = _gen(text=f"iş parçacığı {n} kayıt {i}")
                db.set_generation_favorite(g["id"], i % 2 == 0)
                db.list_generations(limit=5, q="kayıt")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert errors == []
    assert db.count_generations() == 60 and db.count_generations(favorite=True) == 32


# ---------- jobs ----------

def test_job_done_with_partial_and_new_fields():
    q = JobQueue()

    def fn(job):
        for i in range(3):
            job.check_cancelled()
            job.set_progress(i, 3, f"parça {i}")
            job.add_partial({"index": i, "url": f"/files/outputs/partial/{i}.wav", "text": f"parça {i}",
                             "duration": 1.0})
        return {"url": "/files/outputs/x.wav"}

    job = q.submit("tts", fn)
    assert _wait(lambda: job.status in FINISHED)
    d = job.to_dict()
    assert d["status"] == "done" and d["progress"] == 1.0 and d["error"] is None
    assert d["result"] == {"url": "/files/outputs/x.wav"}             # işçi sonuca dokunmaz
    assert [p["index"] for p in d["partial"]] == [0, 1, 2]
    assert d["cancelled"] is False and d["eta_s"] is None and d["position"] is None
    d["partial"].append({"index": 99})                                # kopya: iç listeyi bozmaz
    assert len(job.partial) == 3
    assert q.running() is None and q.pending() == 0


def test_job_error_does_not_stop_worker():
    q = JobQueue()
    bad = q.submit("tts", lambda job: 1 / 0)
    good = q.submit("tts", lambda job: "tamam")
    assert _wait(lambda: good.status in FINISHED)
    assert bad.status == "error" and "division" in bad.error and bad.cancelled is False
    assert good.status == "done" and good.result == "tamam"


def test_result_written_by_fn_is_kept():
    q = JobQueue()

    def fn(job):
        job.result = {"url": "/x.wav", "variants": []}

    j = q.submit("tts", fn)
    assert _wait(lambda: j.status == "done")
    assert j.result == {"url": "/x.wav", "variants": []}


def test_cancel_queued_job_and_positions():
    q = JobQueue()
    started, release = threading.Event(), threading.Event()
    ran = []
    try:
        a = q.submit("tts", _blocker(started, release))
        assert started.wait(5)
        b = q.submit("tts", lambda job: ran.append("b"))
        c = q.submit("tts", lambda job: ran.append("c"))
        assert q.running() is a
        assert [a.to_dict()["position"], b.to_dict()["position"], c.to_dict()["position"]] == [0, 1, 2]
        assert q.pending() == 2
        assert q.cancel(b.id) is True
        assert b.status == "cancelled" and b.cancelled and b.finished_at is not None and b.error is None
        assert q.pending() == 1 and c.to_dict()["position"] == 1 and b.to_dict()["position"] is None
        assert q.cancel(b.id) is False                                # zaten iptal
    finally:
        release.set()
    assert _wait(lambda: c.status == "done")
    assert ran == ["c"]                                               # iptal edilen iş hiç çalışmadı
    assert a.status == "done" and q.cancel(a.id) is False and q.cancel("yok") is False


def test_cancel_running_job_via_check_cancelled():
    q = JobQueue()
    started = threading.Event()

    def fn(job):
        for i in range(500):
            job.check_cancelled()
            job.set_progress(i, 500, f"parça {i}")
            started.set()
            time.sleep(0.01)
        return "bitmemeliydi"

    job = q.submit("tts", fn)
    assert started.wait(5)
    assert job.status == "running" and job.to_dict()["position"] == 0
    assert job.cancel() is True                                       # Job.cancel = JobQueue.cancel
    assert _wait(lambda: job.status in FINISHED)
    d = job.to_dict()
    assert d["status"] == "cancelled" and d["cancelled"] is True and d["error"] is None
    assert "result" not in d and job.result is None and job.step < 499
    assert q.running() is None


def test_cancel_flag_before_start_skips_fn():
    q = JobQueue()
    started, release = threading.Event(), threading.Event()
    called = []
    try:
        q.submit("tts", _blocker(started, release))
        assert started.wait(5)
        job = q.submit("tts", lambda j: called.append(1))
        job.cancelled = True                                          # yalnızca bayrak, kuyruktan çıkarılmadan
        assert job.status == "queued"
    finally:
        release.set()
    assert _wait(lambda: job.status in FINISHED)
    assert job.status == "cancelled" and called == []                 # işçi fn'den önce kontrol etti


def test_detached_job_cancel_and_check():
    j = Job(id="x", kind="tts", fn=lambda job: None)
    j.check_cancelled()                                               # bayrak yokken sessiz
    assert j.cancel() is True and j.cancelled
    with pytest.raises(JobCancelled):
        j.check_cancelled()
    assert issubclass(JobCancelled, Exception)
    j.status = "done"
    assert j.cancel() is False


def test_eta_from_progress():
    j = Job(id="e", kind="tts", fn=lambda job: None)
    assert j.to_dict()["eta_s"] is None                               # sırada, kuyruğa bağlı değil
    j.status, j.started_at = "running", time.time() - 10.0
    j.set_progress(0, 6)
    assert j.to_dict()["eta_s"] is None                               # henüz biten adım yok
    j.set_progress(2, 6)
    assert j.to_dict()["eta_s"] == pytest.approx(20.0, abs=0.3)       # 10 sn / 2 adım × 4 kalan adım
    j.set_progress(6, 6)
    assert j.to_dict()["eta_s"] == 0.0 and j.to_dict()["position"] == 0
    j.status = "done"
    assert j.to_dict()["eta_s"] is None


def test_avg_step_time_and_queued_eta():
    q = JobQueue()
    assert q.avg_seconds_per_step() is None

    def fn(job):
        for i in range(4):
            job.set_progress(i + 1, 4)
            time.sleep(0.03)

    first = q.submit("tts", fn)
    assert _wait(lambda: first.status == "done")
    avg = q.avg_seconds_per_step("tts")
    assert avg is not None and 0.025 <= avg <= 1.0
    assert q.avg_seconds_per_step() == avg and q.avg_seconds_per_step("vc") is None

    started, release = threading.Event(), threading.Event()
    try:
        q.submit("tts", _blocker(started, release))
        assert started.wait(5)
        waiting = q.submit("tts", lambda job: None, total=10)       # adım sayısı önceden biliniyor
        unknown = q.submit("tts", lambda job: None)
        assert waiting.to_dict()["eta_s"] == round(avg * 10, 1)
        assert unknown.to_dict()["eta_s"] is None
        assert [waiting.to_dict()["position"], unknown.to_dict()["position"]] == [1, 2]
    finally:
        release.set()


def test_list_newest_first_and_limit():
    q = JobQueue()
    jobs = [q.submit("tts", lambda job, i=i: i) for i in range(5)]
    assert _wait(lambda: all(j.status == "done" for j in jobs))
    listed = q.list()
    assert [d["id"] for d in listed] == [j.id for j in reversed(jobs)]
    assert [d["result"] for d in listed] == [4, 3, 2, 1, 0]
    assert len(q.list(limit=2)) == 2 and q.list(limit=0) == []
    assert q.get(jobs[0].id) is jobs[0] and q.get("yok") is None


def test_trim_keeps_recent_jobs():
    q = JobQueue(keep=3)
    jobs = []
    for _ in range(6):
        j = q.submit("tts", lambda job: None)
        assert _wait(lambda: j.status == "done")
        jobs.append(j)
    assert [d["id"] for d in q.list()] == [jobs[5].id, jobs[4].id, jobs[3].id]
    assert q.get(jobs[0].id) is None


def test_add_partial_is_thread_safe():
    j = Job(id="p", kind="tts", fn=lambda job: None)

    def add(n):
        for i in range(200):
            j.add_partial({"index": n * 1000 + i})
            j.to_dict()

    threads = [threading.Thread(target=add, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert len(j.to_dict()["partial"]) == 800
    assert len({p["index"] for p in j.partial}) == 800


def test_get_queue_singleton():
    got = []
    threads = [threading.Thread(target=lambda: got.append(get_queue())) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert len(got) == 8 and all(g is got[0] for g in got) and get_queue() is got[0]
