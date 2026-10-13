"""Basit, tek işçili iş kuyruğu. Uzun üretimler HTTP isteğini bloklamaz; istemci ilerlemeyi sorgular.

Durumlar: queued → running → done | error | cancelled.
- Sıradaki iş `JobQueue.cancel` ile hemen kuyruktan düşer ("cancelled").
- Çalışan işte yalnızca iptal bayrağı kalkar; iş fonksiyonu (motor) parçalar arasında `job.check_cancelled()`
  çağırdığında `JobCancelled` fırlar ve işçi bunu hata değil "cancelled" olarak kaydeder.
- Motor hazır olan parçaları `job.add_partial({...})` ile ekler; istemci iş bitmeden dinlemeye başlayabilir.
"""
from __future__ import annotations

import logging
import threading
import time
import traceback
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger("sesklon.jobs")

JobFn = Callable[["Job"], Any]

FINISHED = ("done", "error", "cancelled")
STEP_STATS_JOBS = 20            # ortalama adım süresi için bakılan son tamamlanan iş sayısı


class JobCancelled(Exception):
    """İş kullanıcı isteğiyle iptal edildi (hata sayılmaz; durum "cancelled")."""


@dataclass(eq=False)            # kimlikle karşılaştırma: her iş tekildir
class Job:
    id: str
    kind: str
    fn: JobFn
    status: str = "queued"          # queued | running | done | error | cancelled
    progress: float = 0.0           # 0..1
    step: int = 0
    total: int = 0
    message: str = ""
    result: Any = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    partial: list[dict] = field(default_factory=list)   # [{"index", "url", "text", "duration"}, ...]
    cancelled: bool = False         # iptal istendi mi
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _queue: JobQueue | None = field(default=None, init=False, repr=False)

    def set_progress(self, step: int, total: int, message: str = "") -> None:
        self.step, self.total, self.message = step, total, message
        self.progress = (step / total) if total else 0.0

    def add_partial(self, d: dict) -> None:
        """Hazır olan bir ara parçayı ekler (kopyası saklanır)."""
        with self._lock:
            self.partial.append(dict(d))

    def cancel(self) -> bool:
        """İptal ister. Kuyruğa bağlıysa `JobQueue.cancel` ile aynıdır; bitmiş işte False."""
        if self._queue is not None:
            return self._queue._cancel_job(self)
        if self.status in FINISHED:
            return False
        self.cancelled = True
        return True

    def check_cancelled(self) -> None:
        """İptal istendiyse JobCancelled fırlatır. Motor her parça arasında çağırmalı."""
        if self.cancelled:
            raise JobCancelled(f"İş {self.id} iptal edildi")

    def _eta(self, now: float) -> float | None:
        """Kalan tahmini süre (sn). Çalışırken ilerlemeden; sıradayken geçmiş işlerin ortalama adım süresinden."""
        if self.status == "running":
            if self.step > 0 and self.total and self.started_at is not None:
                elapsed = max(0.0, now - self.started_at)
                return round(elapsed / self.step * max(0, self.total - self.step), 1)
            return None
        if self.status == "queued" and self.total and self._queue is not None:
            avg = self._queue.avg_seconds_per_step(self.kind)
            if avg is None:
                avg = self._queue.avg_seconds_per_step()
            if avg is not None:
                return round(avg * self.total, 1)
        return None

    def _position(self) -> int | None:
        if self._queue is not None:
            return self._queue._position_of(self)
        return 0 if self.status == "running" else None

    def to_dict(self) -> dict:
        now = time.time()
        with self._lock:
            partial = [dict(p) for p in self.partial]
        d = {
            "id": self.id, "kind": self.kind, "status": self.status, "progress": round(self.progress, 3),
            "step": self.step, "total": self.total, "message": self.message, "error": self.error,
            "created_at": self.created_at, "started_at": self.started_at, "finished_at": self.finished_at,
            "elapsed": round((self.finished_at or now) - (self.started_at or self.created_at), 1),
            "partial": partial,
            "cancelled": self.cancelled,
            "eta_s": self._eta(now),
            "position": self._position(),     # sıradaysa önündeki iş sayısı, çalışıyorsa 0, bittiyse None
        }
        if self.status == "done":
            d["result"] = self.result
        return d


class JobQueue:
    def __init__(self, keep: int = 200) -> None:
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._pending: deque[Job] = deque()                     # sıradaki işler (FIFO)
        self._jobs: dict[str, Job] = {}                         # ekleme sırası = gönderim sırası
        self._current: Job | None = None
        self._step_times: deque[tuple[str, float]] = deque(maxlen=STEP_STATS_JOBS * 10)   # (tür, sn/adım)
        self._keep = keep
        self._worker = threading.Thread(target=self._run, name="sesklon-worker", daemon=True)
        self._worker.start()

    def submit(self, kind: str, fn: JobFn, total: int = 0) -> Job:
        """İşi kuyruğa ekler. total: adım sayısı önceden biliniyorsa (sıradayken eta için)."""
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, fn=fn, total=max(0, int(total or 0)))
        job._queue = self
        with self._cv:
            self._jobs[job.id] = job
            self._pending.append(job)
            self._trim()
            self._cv.notify()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def pending(self) -> int:
        with self._lock:
            return len(self._pending)

    def running(self) -> Job | None:
        with self._lock:
            return self._current

    def list(self, limit: int = 50) -> list[dict]:
        """Son işler, yeniden eskiye."""
        with self._lock:
            jobs = [*reversed(self._jobs.values())][: max(0, int(limit))]
        return [j.to_dict() for j in jobs]

    def cancel(self, job_id: str) -> bool:
        """Sıradaysa kuyruktan çıkarır; çalışıyorsa iptal bayrağını kaldırır. Bitmiş/bilinmeyen işte False."""
        job = self.get(job_id)
        return self._cancel_job(job) if job is not None else False

    def avg_seconds_per_step(self, kind: str | None = None) -> float | None:
        """Son STEP_STATS_JOBS tamamlanan işin (kind verilirse o türden) ortalama adım süresi; veri yoksa None."""
        with self._lock:
            vals = [s for k, s in self._step_times if kind is None or k == kind][-STEP_STATS_JOBS:]
        return sum(vals) / len(vals) if vals else None

    # ---- iç işler ----

    def _cancel_job(self, job: Job) -> bool:
        with self._lock:
            if job.status == "queued":
                try:
                    self._pending.remove(job)
                except ValueError:
                    pass
                job.cancelled = True
                job.message = "İptal edildi"
                job.finished_at = time.time()
                job.status = "cancelled"
                return True
            if job.status == "running":
                job.cancelled = True        # işçi, fn check_cancelled çağırınca durur
                return True
            return False

    def _position_of(self, job: Job) -> int | None:
        with self._lock:
            if job.status == "running":
                return 0
            if job.status != "queued":
                return None
            ahead = 1 if self._current is not None else 0
            for i, j in enumerate(self._pending):
                if j is job:
                    return i + ahead
            return None

    def _trim(self) -> None:
        """Bellekte en fazla `keep` iş tutar; en eski biten işler atılır. Kilit altında çağrılır."""
        excess = len(self._jobs) - self._keep
        if excess <= 0:
            return
        for jid in [j.id for j in self._jobs.values() if j.status in FINISHED][:excess]:
            self._jobs.pop(jid, None)

    def _next(self) -> Job:
        with self._cv:
            while not self._pending:
                self._cv.wait()
            job = self._pending.popleft()
            job.status, job.started_at = "running", time.time()   # cancel() ile aynı kilit altında
            self._current = job
            return job

    def _run(self) -> None:
        while True:
            job = self._next()
            status, result, error = "done", None, None
            try:
                job.check_cancelled()           # sıradayken bayrak doğrudan kaldırılmış olabilir
                result = job.fn(job)
            except JobCancelled:
                status = "cancelled"
                log.info("İş %s iptal edildi", job.id)
            except BaseException as e:  # noqa: BLE001 — işçi iş parçacığı hiçbir hatada ölmemeli
                status, error = "error", _describe(e)
                log.error("İş %s hata: %s\n%s", job.id, error, traceback.format_exc())
            self._finish(job, status, result, error)

    def _finish(self, job: Job, status: str, result: Any, error: str | None) -> None:
        finished = time.time()
        with self._lock:
            if status == "done":
                if result is not None or job.result is None:   # fn sonucu kendisi yazdıysa ezme
                    job.result = result
                job.progress = 1.0
                if job.total > 0 and job.started_at is not None:
                    self._step_times.append((job.kind, (finished - job.started_at) / job.total))
            elif status == "cancelled":
                job.cancelled = True
                job.message = "İptal edildi"
            else:
                job.error = error
            job.finished_at = finished
            if self._current is job:
                self._current = None
            job.status = status                 # en son: bekleyen istemci sonucu hazır görür


def _describe(e: BaseException) -> str:
    try:
        msg = str(e)
    except Exception:  # noqa: BLE001
        msg = ""
    return msg or e.__class__.__name__


_queue: JobQueue | None = None
_queue_lock = threading.Lock()


def get_queue() -> JobQueue:
    global _queue
    if _queue is None:
        with _queue_lock:
            if _queue is None:
                _queue = JobQueue()
    return _queue
