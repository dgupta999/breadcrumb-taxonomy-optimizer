"""Job definitions + queue helpers. Long-running work never runs in the request."""
from __future__ import annotations

import logging
import threading
import traceback
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import Competitor, CrawlJob, JobRun, Project, Upload

log = logging.getLogger(__name__)
_claim_lock = threading.Lock()

JOB_TYPES = [
    "IMPORT_TAXONOMY", "IMPORT_SRP", "BUILD_TAXONOMY", "MAP_SRP", "AUDIT_BREADCRUMBS", "CRAWL_COMPETITOR",
    "BUILD_COMPETITOR_TREE", "COMPARE_TAXONOMY", "DETECT_GAPS", "GENERATE_EXPORT", "IMPORT_COMPETITOR_CRAWL",
]


def now() -> datetime:
    return datetime.now(timezone.utc)


def enqueue(db: Session, project_id: int, job_type: str, params: dict | None = None) -> JobRun:
    if job_type not in JOB_TYPES:
        raise ValueError(f"unknown job type {job_type}")
    job = JobRun(project_id=project_id, job_type=job_type, status="QUEUED", params=params or {})
    db.add(job)
    db.flush()
    return job


class JobContext:
    def __init__(self, db: Session, job: JobRun):
        self.db, self.job = db, job

    def progress(self, processed: int, total: int, message: str | None = None) -> None:
        self.job.processed_items, self.job.total_items = processed, total
        self.job.progress = round(100.0 * processed / total, 1) if total else 0
        if message:
            self.job.message = message
        self.db.commit()

    def cancelled(self) -> bool:
        with SessionLocal() as s:
            st = s.scalar(select(JobRun.status).where(JobRun.id == self.job.id))
        return st == "CANCEL_REQUESTED"


# --------------------------------------------------------------------------- handlers
def _project(db: Session, job: JobRun) -> Project:
    p = db.get(Project, job.project_id)
    if p is None:
        raise ValueError("project not found")
    return p


def h_import(kind: str):
    def run(jc: JobContext) -> dict:
        from .core.context import ensure_default_synonyms
        from .core.fileio import import_rows
        from .core.taxonomy import build_tree

        db, job = jc.db, jc.job
        up = db.get(Upload, job.params["upload_id"])
        mapping = job.params.get("mapping") or up.mapping
        jc.progress(0, 3, f"Importing {up.filename}")
        res = import_rows(db, kind, job.project_id, up.stored_path, mapping, replace=job.params.get("replace", True))
        up.status, up.mapping = "IMPORTED", mapping
        if kind == "TAXONOMY":
            jc.progress(1, 3, "Building taxonomy tree")
            res["tree"] = build_tree(db, _project(db, job))
            res["default_synonyms_added"] = ensure_default_synonyms(db, job.project_id)
        jc.progress(3, 3, "Done")
        return res
    return run


def h_build_taxonomy(jc: JobContext) -> dict:
    from .core.taxonomy import build_tree

    return build_tree(jc.db, _project(jc.db, jc.job))


def h_map_srp(jc: JobContext) -> dict:
    from .core.context import ensure_default_synonyms, load_context
    from .core.srp_mapping import map_srps

    ensure_default_synonyms(jc.db, jc.job.project_id)
    ctx = load_context(jc.db, _project(jc.db, jc.job))
    if not ctx.index.nodes:
        raise ValueError("Upload the current taxonomy first")
    return map_srps(jc.db, ctx, jc.progress, jc.job.params.get("srp_ids"))


def h_audit(jc: JobContext) -> dict:
    from .core.audit import run_audit
    from .core.context import load_context

    ctx = load_context(jc.db, _project(jc.db, jc.job))
    if not ctx.index.nodes:
        raise ValueError("Upload the current taxonomy first")
    return run_audit(jc.db, ctx, jc.progress)


def h_crawl(jc: JobContext) -> dict:
    from .core.competitor_tree import build_competitor_tree
    from .crawler.crawler import crawl_competitor

    db = jc.db
    comp = db.get(Competitor, jc.job.params["competitor_id"])
    if comp is None:
        raise ValueError("competitor not found")
    cj = CrawlJob(project_id=comp.project_id, competitor_id=comp.id, job_run_id=jc.job.id, status="QUEUED")
    db.add(cj)
    comp.status = "CRAWLING"
    db.commit()
    res = crawl_competitor(db, comp, cj, jc.progress, jc.cancelled)
    comp.status = "CRAWLED" if res["status"] == "COMPLETED" else res["status"]
    res["crawl_job_id"] = cj.id
    res["tree"] = build_competitor_tree(db, comp)
    if res["status"] == "CANCELLED":
        jc.job.status = "CANCELLED"
    return res


def h_import_comp_crawl(jc: JobContext) -> dict:
    from .core.competitor_import import import_competitor_crawl
    from .core.competitor_tree import build_competitor_tree

    db, p = jc.db, jc.job.params
    comp = db.get(Competitor, p["competitor_id"])
    up = db.get(Upload, p["upload_id"])
    if comp is None or up is None:
        raise ValueError("competitor or upload not found")
    jc.progress(0, 2, f"Importing {up.filename} for {comp.name}")
    res = import_competitor_crawl(db, comp, up.stored_path, p.get("mapping") or up.mapping, jc.job.id, bool(p.get("append")))
    up.status = "IMPORTED"
    jc.progress(1, 2, "Building competitor taxonomy tree")
    res["tree"] = build_competitor_tree(db, comp)
    jc.progress(2, 2, "Done")
    return res


def h_build_comp_tree(jc: JobContext) -> dict:
    from .core.competitor_tree import build_competitor_tree

    db = jc.db
    cid = jc.job.params.get("competitor_id")
    q = select(Competitor).where(Competitor.project_id == jc.job.project_id)
    if cid:
        q = q.where(Competitor.id == cid)
    return {"trees": [build_competitor_tree(db, c) for c in db.scalars(q)]}


def h_compare(jc: JobContext) -> dict:
    from .core.compare import compare_taxonomy
    from .core.context import load_context

    return compare_taxonomy(jc.db, load_context(jc.db, _project(jc.db, jc.job)), jc.progress)


def h_gaps(jc: JobContext) -> dict:
    from .core.context import load_context
    from .core.gaps import detect_gaps

    return detect_gaps(jc.db, load_context(jc.db, _project(jc.db, jc.job)), jc.progress)


def h_export(jc: JobContext) -> dict:
    from .exporter import write_export

    p = jc.job.params
    path, rows = write_export(jc.db, jc.job.project_id, p["export_key"], p.get("format", "xlsx"))
    return {"file": path.name, "rows": rows}


HANDLERS: dict[str, Callable[[JobContext], dict]] = {
    "IMPORT_TAXONOMY": h_import("TAXONOMY"),
    "IMPORT_SRP": h_import("SRP"),
    "BUILD_TAXONOMY": h_build_taxonomy,
    "MAP_SRP": h_map_srp,
    "AUDIT_BREADCRUMBS": h_audit,
    "CRAWL_COMPETITOR": h_crawl,
    "BUILD_COMPETITOR_TREE": h_build_comp_tree,
    "COMPARE_TAXONOMY": h_compare,
    "DETECT_GAPS": h_gaps,
    "GENERATE_EXPORT": h_export,
    "IMPORT_COMPETITOR_CRAWL": h_import_comp_crawl,
}


def claim_next(db: Session) -> JobRun | None:
    with _claim_lock:
        return _claim(db)


def _claim(db: Session) -> JobRun | None:
    # Analysis jobs of one project run one at a time (they rewrite the same tables);
    # crawls run alongside them.
    busy = set(db.scalars(select(JobRun.project_id).where(JobRun.status.in_(("RUNNING", "CANCEL_REQUESTED")), JobRun.job_type != "CRAWL_COMPETITOR")))
    for job in db.scalars(select(JobRun).where(JobRun.status == "QUEUED").order_by(JobRun.id).limit(50)):
        if job.job_type != "CRAWL_COMPETITOR" and job.project_id in busy:
            continue
        res = db.execute(update(JobRun).where(JobRun.id == job.id, JobRun.status == "QUEUED")
                         .values(status="RUNNING", started_at=now(), message="Started"))
        db.commit()
        if res.rowcount == 1:
            db.refresh(job)
            return job
    return None


def run_job(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.get(JobRun, job_id)
        jc = JobContext(db, job)
        try:
            result = HANDLERS[job.job_type](jc)
            db.commit()
            job = db.get(JobRun, job_id)
            job.result = result or {}
            if job.status not in ("CANCELLED",):
                job.status = "COMPLETED"
                job.progress = 100
            job.completed_at = now()
            job.message = "Completed" if job.status == "COMPLETED" else job.message
            db.commit()
            for nxt in (job.params or {}).get("then", []):
                enqueue(db, job.project_id, nxt["job_type"] if isinstance(nxt, dict) else nxt,
                        (nxt.get("params") if isinstance(nxt, dict) else None) or {})
            db.commit()
        except Exception as e:
            db.rollback()
            log.exception("job %s failed", job_id)
            job = db.get(JobRun, job_id)
            job.status = "FAILED"
            job.error_count = (job.error_count or 0) + 1
            job.error_message = f"{e.__class__.__name__}: {e}"
            job.result = {"traceback": traceback.format_exc()[-4000:]}
            job.completed_at = now()
            db.commit()
    finally:
        db.close()


def recover_stale_jobs() -> None:
    with SessionLocal() as db:
        db.execute(update(JobRun).where(JobRun.status.in_(("RUNNING", "CANCEL_REQUESTED")))
                   .values(status="FAILED", error_message="Worker restarted while job was running; re-run it.", completed_at=now()))
        db.execute(update(CrawlJob).where(CrawlJob.status == "RUNNING").values(status="FAILED", completed_at=now()))
        db.commit()
