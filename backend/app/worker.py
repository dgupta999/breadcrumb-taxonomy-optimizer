"""Background worker. Run standalone with:  python -m app.worker

Polls job_runs for QUEUED jobs. Several threads so a 1000-URL crawl does not
block quick jobs (mapping, exports) queued behind it.
"""
from __future__ import annotations

import logging
import os
import threading
import time

from .config import settings
from .db import SessionLocal, init_db
from .jobs import claim_next, recover_stale_jobs, run_job

log = logging.getLogger("worker")
_stop = threading.Event()


def _loop(name: str) -> None:
    while not _stop.is_set():
        job = None
        try:
            with SessionLocal() as db:
                job = claim_next(db)
        except Exception:
            log.exception("%s: failed to claim job", name)
        if job is None:
            _stop.wait(settings.worker_poll_seconds)
            continue
        log.info("%s: running job %s (%s)", name, job.id, job.job_type)
        run_job(job.id)


def _keep_awake() -> None:
    """Render's free plan sleeps after ~15 min without inbound HTTP traffic — background
    jobs don't count. While a job is running, ping our own public URL every 4 minutes."""
    import httpx
    from sqlalchemy import func, select

    from .models import JobRun

    url = (os.getenv("RENDER_EXTERNAL_URL") or os.getenv("PUBLIC_URL") or "").rstrip("/")
    if not url:
        return
    while not _stop.is_set():
        try:
            with SessionLocal() as db:
                active = db.scalar(select(func.count()).where(JobRun.status.in_(("QUEUED", "RUNNING"))))
            if active:
                httpx.get(f"{url}/api/health", timeout=20)
        except Exception:
            log.debug("keep-awake ping failed", exc_info=True)
        _stop.wait(240)


def start_background(threads: int | None = None) -> list[threading.Thread]:
    n = threads or int(os.getenv("WORKER_THREADS", "3"))
    out = [threading.Thread(target=_keep_awake, daemon=True, name="keep-awake")]
    out[0].start()
    for i in range(n):
        t = threading.Thread(target=_loop, args=(f"worker-{i+1}",), daemon=True)
        t.start()
        out.append(t)
    return out


def stop() -> None:
    _stop.set()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_db()
    recover_stale_jobs()
    start_background()
    log.info("worker started")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        stop()


if __name__ == "__main__":
    main()
