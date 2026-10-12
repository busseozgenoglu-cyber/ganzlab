"""Basit, tek işçili iş kuyruğu. Uzun üretimler HTTP isteğini bloklamaz; istemci ilerlemeyi sorgular."""
from __future__ import annotations

import logging
import queue
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger("sesklon.jobs")

JobFn = Callable[["Job"], Any]


@dataclass
class Job:
    id: str
    kind: str
    fn: JobFn
    status: str = "queued"          # queued | running | done | error
    progress: float = 0.0           # 0..1
    step: int = 0
    total: int = 0
    message: str = ""
    result: Any = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None

    def set_progress(self, step: int, total: int, message: str = "") -> None:
        self.step, self.total, self.message = step, total, message
        self.progress = (step / total) if total else 0.0

    def to_dict(self) -> dict:
        d = {
            "id": self.id, "kind": self.kind, "status": self.status, "progress": round(self.progress, 3),
            "step": self.step, "total": self.total, "message": self.message, "error": self.error,
            "created_at": self.created_at, "started_at": self.started_at, "finished_at": self.finished_at,
            "elapsed": round((self.finished_at or time.time()) - (self.started_at or self.created_at), 1),
        }
        if self.status == "done":
            d["result"] = self.result
        return d


class JobQueue:
    def __init__(self, keep: int = 200) -> None:
        self._q: queue.Queue[Job] = queue.Queue()
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._keep = keep
        self._worker = threading.Thread(target=self._run, name="sesklon-worker", daemon=True)
        self._worker.start()

    def submit(self, kind: str, fn: JobFn) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, fn=fn)
        with self._lock:
            self._jobs[job.id] = job
            self._trim()
        self._q.put(job)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def pending(self) -> int:
        return self._q.qsize()

    def _trim(self) -> None:
        if len(self._jobs) <= self._keep:
            return
        finished = sorted((j for j in self._jobs.values() if j.status in ("done", "error")), key=lambda j: j.created_at)
        for j in finished[: len(self._jobs) - self._keep]:
            self._jobs.pop(j.id, None)

    def _run(self) -> None:
        while True:
            job = self._q.get()
            job.status, job.started_at = "running", time.time()
            try:
                job.result = job.fn(job)
                job.status = "done"
                job.progress = 1.0
            except Exception as e:  # noqa: BLE001
                job.status, job.error = "error", str(e) or e.__class__.__name__
                log.error("İş %s hata: %s\n%s", job.id, e, traceback.format_exc())
            finally:
                job.finished_at = time.time()
                self._q.task_done()


_queue: JobQueue | None = None


def get_queue() -> JobQueue:
    global _queue
    if _queue is None:
        _queue = JobQueue()
    return _queue
