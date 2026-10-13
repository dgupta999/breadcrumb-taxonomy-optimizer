"""REST API consumed by the (Lovable-compatible) React frontend."""
from __future__ import annotations

import shutil
import uuid
from collections import Counter, defaultdict
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..core.fileio import FIELDS, read_table, suggest_mapping, validate_mapping
from ..core.normalize import norm_key
from ..core.review import ACTIONS, ReviewError, apply_review
from ..db import get_db
from ..exporter import EXPORTS, build_export
from ..jobs import JOB_TYPES, enqueue
from ..models import (
    SRP, ApprovedMapping, BreadcrumbAudit, CategoryNode, Competitor, CompetitorCategory, CompetitorMapping,
    CompetitorSeedUrl, CrawlJob, CrawlPage, Export, GapChild, JobRun, ManualOverride, Project, ReviewAction, Synonym,
    TaxonomyGap, Upload,
)
from .common import Page, get_project, multi, paginate, to_dict

router = APIRouter(prefix="/api")


# ============================================================== projects
class ProjectIn(BaseModel):
    name: str
    description: str | None = None
    target_category: str | None = None
    home_label_cn: str | None = None
    home_label_en: str | None = None
    settings: dict = Field(default_factory=dict)


@router.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    return [to_dict(p) for p in db.scalars(select(Project).order_by(Project.id.desc()))]


@router.post("/projects")
def create_project(body: ProjectIn, db: Session = Depends(get_db)):
    p = Project(**body.model_dump())
    db.add(p)
    db.commit()
    return to_dict(p)


@router.get("/projects/{project_id}")
def get_project_ep(p: Project = Depends(get_project)):
    return to_dict(p)


@router.patch("/projects/{project_id}")
def update_project(body: dict = Body(...), p: Project = Depends(get_project), db: Session = Depends(get_db)):
    for k in ("name", "description", "target_category", "home_label_cn", "home_label_en", "settings"):
        if k in body:
            setattr(p, k, body[k])
    db.commit()
    return to_dict(p)


@router.delete("/projects/{project_id}")
def delete_project(p: Project = Depends(get_project), db: Session = Depends(get_db)):
    db.delete(p)
    db.commit()
    return {"deleted": True}


def _counts(db: Session, model, col, pid: int) -> dict:
    return {k or "—": v for k, v in db.execute(select(col, func.count()).where(model.project_id == pid).group_by(col)).all()}


@router.get("/projects/{project_id}/dashboard")
def dashboard(p: Project = Depends(get_project), db: Session = Depends(get_db)):
    pid = p.id
    n_nodes = db.scalar(select(func.count()).where(CategoryNode.project_id == pid)) or 0
    n_srps = db.scalar(select(func.count()).where(SRP.project_id == pid)) or 0
    mapped = db.scalar(select(func.count()).where(SRP.project_id == pid, SRP.mapped_at.is_not(None))) or 0
    comps = db.scalars(select(Competitor).where(Competitor.project_id == pid)).all()
    crawl = []
    for c in comps:
        cj = db.scalars(select(CrawlJob).where(CrawlJob.competitor_id == c.id).order_by(CrawlJob.id.desc())).first()
        cats = db.scalar(select(func.count()).where(CompetitorCategory.competitor_id == c.id)) or 0
        crawl.append({"competitor": c.name, "status": cj.status if cj else "NOT CRAWLED", "processed": cj.processed_urls if cj else 0,
                      "discovered": cj.discovered_urls if cj else 0, "errors": cj.error_count if cj else 0, "categories": cats})
    jobs = db.scalars(select(JobRun).where(JobRun.project_id == pid).order_by(JobRun.id.desc()).limit(10)).all()
    last_by_type = {}
    for j in db.scalars(select(JobRun).where(JobRun.project_id == pid).order_by(JobRun.id.desc())):
        last_by_type.setdefault(j.job_type, {"status": j.status, "completed_at": j.completed_at.isoformat() if j.completed_at else None, "id": j.id})
    steps = [
        ("Upload Current Category Taxonomy", n_nodes > 0, "upload"),
        ("Upload SRP Data", n_srps > 0, "upload"),
        ("Build Current Taxonomy Tree", n_nodes > 0, "upload"),
        ("Run Current Breadcrumb Audit", "AUDIT_BREADCRUMBS" in last_by_type and last_by_type["AUDIT_BREADCRUMBS"]["status"] == "COMPLETED", "audit"),
        ("Run SRP-to-Category Mapping", mapped > 0, "srp"),
        ("Add Competitor Start URLs", len(comps) > 0, "crawl"),
        ("Crawl Competitor Category Sections", any(c["status"] in ("COMPLETED", "CANCELLED") for c in crawl), "crawl"),
        ("Build Competitor Taxonomy Trees", any(c["categories"] for c in crawl), "competitor-taxonomy"),
        ("Compare Competitor Taxonomy with Current", last_by_type.get("COMPARE_TAXONOMY", {}).get("status") == "COMPLETED", "competitor-mapping"),
        ("Detect Parent/Child Taxonomy Gaps", last_by_type.get("DETECT_GAPS", {}).get("status") == "COMPLETED", "gaps"),
        ("Validate Gaps Using SRP Data", last_by_type.get("DETECT_GAPS", {}).get("status") == "COMPLETED" and n_srps > 0, "gaps"),
        ("Generate Recommended Breadcrumb Architecture", "AUDIT_BREADCRUMBS" in last_by_type, "audit"),
        ("Show Internal Linking Impact", "AUDIT_BREADCRUMBS" in last_by_type, "audit"),
        ("Human Review", (db.scalar(select(func.count()).where(ReviewAction.project_id == pid)) or 0) > 0, "review"),
        ("Download Excel Exports", (db.scalar(select(func.count()).where(Export.project_id == pid)) or 0) > 0, "exports"),
    ]
    review_pending = (
        (db.scalar(select(func.count()).where(SRP.project_id == pid, SRP.review_status.in_(("NEEDS_REVIEW", "LOW_CONFIDENCE", "NO_MATCH")))) or 0)
        + (db.scalar(select(func.count()).where(BreadcrumbAudit.project_id == pid, BreadcrumbAudit.review_status == "NEEDS_REVIEW")) or 0)
        + (db.scalar(select(func.count()).where(TaxonomyGap.project_id == pid, TaxonomyGap.review_status == "NEEDS_REVIEW")) or 0)
    )
    return {
        "project": to_dict(p),
        "taxonomy": {"nodes": n_nodes, "max_depth": db.scalar(select(func.max(CategoryNode.depth)).where(CategoryNode.project_id == pid)) or 0,
                     "inferred": db.scalar(select(func.count()).where(CategoryNode.project_id == pid, CategoryNode.is_inferred.is_(True))) or 0},
        "srps": {"total": n_srps, "mapped": mapped, "by_band": _counts(db, SRP, SRP.confidence_band, pid),
                 "duplicates": _counts(db, SRP, SRP.duplicate_intent, pid),
                 "volume": db.scalar(select(func.sum(SRP.search_volume)).where(SRP.project_id == pid)) or 0},
        "audit": {"by_action": _counts(db, BreadcrumbAudit, BreadcrumbAudit.action, pid),
                  "by_linking": _counts(db, BreadcrumbAudit, BreadcrumbAudit.linking_improvement, pid),
                  "avg_current": round(db.scalar(select(func.avg(BreadcrumbAudit.current_score)).where(BreadcrumbAudit.project_id == pid)) or 0, 1),
                  "avg_recommended": round(db.scalar(select(func.avg(BreadcrumbAudit.recommended_score)).where(BreadcrumbAudit.project_id == pid)) or 0, 1)},
        "competitors": crawl,
        "mappings": _counts(db, CompetitorMapping, CompetitorMapping.match_type, pid),
        "gaps": {"by_type": _counts(db, TaxonomyGap, TaxonomyGap.gap_type, pid), "by_priority": _counts(db, TaxonomyGap, TaxonomyGap.priority, pid)},
        "review_pending": review_pending,
        "steps": [{"step": i + 1, "title": t, "done": bool(d), "page": pg} for i, (t, d, pg) in enumerate(steps)],
        "recent_jobs": [to_dict(j, {"result"}) for j in jobs],
        "llm_available": settings.llm_available,
    }


# ============================================================== uploads
@router.get("/upload-fields")
def upload_fields():
    return {k: [{"field": f, "label": l, "required": r} for f, (l, r, _) in v.items()] for k, v in FIELDS.items()}


@router.post("/projects/{project_id}/uploads")
async def upload_file(kind: str = Form(...), file: UploadFile = File(...), p: Project = Depends(get_project), db: Session = Depends(get_db)):
    kind = kind.upper()
    if kind not in FIELDS:
        raise HTTPException(400, "kind must be TAXONOMY, SRP, SYNONYMS or COMPETITOR_CRAWL")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".csv", ".xlsx", ".xlsm", ".tsv", ".txt"):
        raise HTTPException(400, "Upload a CSV or XLSX file")
    dest = settings.data_dir / "uploads" / f"{uuid.uuid4().hex}{ext}"
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        cols, sample = read_table(dest, max_rows=8)
        _, all_rows = read_table(dest)
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"Could not read file: {e}")
    if not cols:
        raise HTTPException(400, "File has no header row")
    up = Upload(project_id=p.id, kind=kind, filename=file.filename or dest.name, stored_path=str(dest), columns=cols,
                row_count=len(all_rows), mapping=suggest_mapping(kind, cols))
    db.add(up)
    db.commit()
    return {**to_dict(up), "sample": [{k: (str(v) if v is not None else None) for k, v in r.items()} for r in sample],
            "fields": [{"field": f, "label": l, "required": r} for f, (l, r, _) in FIELDS[kind].items()]}


@router.get("/projects/{project_id}/uploads")
def list_uploads(p: Project = Depends(get_project), db: Session = Depends(get_db)):
    return [to_dict(u) for u in db.scalars(select(Upload).where(Upload.project_id == p.id).order_by(Upload.id.desc()))]


class CommitIn(BaseModel):
    mapping: dict[str, str | None]
    replace: bool = True
    then: list = Field(default_factory=list)
    competitor_id: int | None = None  # COMPETITOR_CRAWL uploads
    append: bool = False


@router.post("/projects/{project_id}/uploads/{upload_id}/commit")
def commit_upload(upload_id: int, body: CommitIn, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    up = db.get(Upload, upload_id)
    if up is None or up.project_id != p.id:
        raise HTTPException(404, "upload not found")
    errs = validate_mapping(up.kind, body.mapping)
    if errs:
        raise HTTPException(400, "; ".join(errs))
    up.mapping = body.mapping
    if up.kind == "SYNONYMS":
        from ..core.fileio import import_rows

        res = import_rows(db, "SYNONYMS", p.id, up.stored_path, body.mapping)
        up.status = "IMPORTED"
        db.commit()
        return {"imported": res}
    if up.kind == "COMPETITOR_CRAWL":
        comp = db.get(Competitor, body.competitor_id) if body.competitor_id else None
        if comp is None or comp.project_id != p.id:
            raise HTTPException(400, "Choose which competitor this crawl file belongs to")
        then = body.then or [{"job_type": "COMPARE_TAXONOMY"}, {"job_type": "DETECT_GAPS"}]
        job = enqueue(db, p.id, "IMPORT_COMPETITOR_CRAWL", {"upload_id": up.id, "mapping": body.mapping, "competitor_id": comp.id,
                                                            "append": body.append, "then": then})
        up.status = "QUEUED"
        db.commit()
        return to_dict(job)
    job_type = {"TAXONOMY": "IMPORT_TAXONOMY", "SRP": "IMPORT_SRP"}[up.kind]
    job = enqueue(db, p.id, job_type, {"upload_id": up.id, "mapping": body.mapping, "replace": body.replace, "then": body.then})
    up.status = "QUEUED"
    db.commit()
    return to_dict(job)


# ============================================================== jobs
class JobIn(BaseModel):
    job_type: str
    params: dict = Field(default_factory=dict)


@router.post("/projects/{project_id}/jobs")
def create_job(body: JobIn, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    if body.job_type not in JOB_TYPES:
        raise HTTPException(400, f"job_type must be one of {JOB_TYPES}")
    job = enqueue(db, p.id, body.job_type, body.params)
    db.commit()
    return to_dict(job)


@router.get("/projects/{project_id}/jobs")
def list_jobs(job_type: str | None = None, status: str | None = None, page: Page = Depends(), p: Project = Depends(get_project), db: Session = Depends(get_db)):
    q = select(JobRun).where(JobRun.project_id == p.id)
    if job_type:
        q = q.where(JobRun.job_type.in_(multi(job_type)))
    if status:
        q = q.where(JobRun.status.in_(multi(status)))
    return paginate(db, q, JobRun, page, default_sort=JobRun.id.desc())


@router.get("/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    j = db.get(JobRun, job_id)
    if j is None:
        raise HTTPException(404, "job not found")
    d = to_dict(j)
    cj = db.scalars(select(CrawlJob).where(CrawlJob.job_run_id == j.id)).first()
    if cj:
        d["crawl"] = to_dict(cj)
    return d


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, db: Session = Depends(get_db)):
    j = db.get(JobRun, job_id)
    if j is None:
        raise HTTPException(404, "job not found")
    if j.status == "QUEUED":
        j.status = "CANCELLED"
    elif j.status == "RUNNING":
        j.status = "CANCEL_REQUESTED"
    db.commit()
    return to_dict(j)


# ============================================================== taxonomy
@router.get("/projects/{project_id}/categories")
def list_categories(depth: int | None = None, inferred: bool | None = None, page: Page = Depends(), p: Project = Depends(get_project), db: Session = Depends(get_db)):
    q = select(CategoryNode).where(CategoryNode.project_id == p.id)
    if depth is not None:
        q = q.where(CategoryNode.depth == depth)
    if inferred is not None:
        q = q.where(CategoryNode.is_inferred.is_(inferred))
    return paginate(db, q, CategoryNode, page, [CategoryNode.name_cn, CategoryNode.name_en, CategoryNode.breadcrumb_cn, CategoryNode.url],
                    default_sort=CategoryNode.breadcrumb_cn)


@router.get("/projects/{project_id}/categories/tree")
def category_tree(p: Project = Depends(get_project), db: Session = Depends(get_db)):
    nodes = db.scalars(select(CategoryNode).where(CategoryNode.project_id == p.id).order_by(CategoryNode.breadcrumb_cn)).all()
    by_parent = defaultdict(list)
    for n in nodes:
        by_parent[n.parent_id].append(n)

    def build(n):
        return {"id": n.id, "name_cn": n.name_cn, "name_en": n.name_en, "url": n.url, "depth": n.depth, "is_inferred": n.is_inferred,
                "product_count": n.product_count, "breadcrumb_cn": n.breadcrumb_cn, "children": [build(c) for c in by_parent.get(n.id, [])]}
    return [build(n) for n in by_parent.get(None, [])]


# ============================================================== SRPs
@router.get("/projects/{project_id}/srps")
def list_srps(band: str | None = None, review_status: str | None = None, duplicate: str | None = None, gap: bool | None = None,
              node_id: int | None = None, page: Page = Depends(), p: Project = Depends(get_project), db: Session = Depends(get_db)):
    q = select(SRP).where(SRP.project_id == p.id)
    if band:
        q = q.where(SRP.confidence_band.in_(multi(band)))
    if review_status:
        q = q.where(SRP.review_status.in_(multi(review_status)))
    if duplicate:
        q = q.where(SRP.duplicate_intent.in_(multi(duplicate)))
    if gap is not None:
        q = q.where(SRP.potential_gap.is_(gap))
    if node_id:
        q = q.where(SRP.matched_node_id == node_id)
    nodes = {n.id: n for n in db.scalars(select(CategoryNode).where(CategoryNode.project_id == p.id))}

    def extra(rows, items):
        for r, it in zip(rows, items):
            n = nodes.get(r.matched_node_id)
            it["matched_category"] = n.name_cn if n else None
            it["matched_category_url"] = n.url if n else None
            it["matched_category_breadcrumb"] = n.breadcrumb_cn if n else None
        return items
    return paginate(db, q, SRP, page, [SRP.keyword, SRP.h1, SRP.keyword_en, SRP.core_product],
                    default_sort=[SRP.search_volume.desc().nullslast()], exclude={"raw"}, extra=extra)


# ============================================================== audit
@router.get("/projects/{project_id}/audits")
def list_audits(action: str | None = None, review_status: str | None = None, linking: str | None = None, min_conf: int | None = None,
                max_conf: int | None = None, page: Page = Depends(), p: Project = Depends(get_project), db: Session = Depends(get_db)):
    q = select(BreadcrumbAudit).where(BreadcrumbAudit.project_id == p.id)
    if action:
        q = q.where(BreadcrumbAudit.action.in_(multi(action)))
    if review_status:
        q = q.where(BreadcrumbAudit.review_status.in_(multi(review_status)))
    if linking:
        q = q.where(BreadcrumbAudit.linking_improvement.in_(multi(linking)))
    if min_conf is not None:
        q = q.where(BreadcrumbAudit.confidence >= min_conf)
    if max_conf is not None:
        q = q.where(BreadcrumbAudit.confidence <= max_conf)
    return paginate(db, q, BreadcrumbAudit, page, [BreadcrumbAudit.category_name, BreadcrumbAudit.current_breadcrumb_cn],
                    default_sort=BreadcrumbAudit.current_breadcrumb_cn)


# ============================================================== competitors
class CompetitorIn(BaseModel):
    name: str
    start_url: str
    target_category: str | None = None
    max_urls: int = Field(1000, ge=1, le=5000)
    max_depth: int = Field(5, ge=0, le=10)
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    render_js: bool = False
    crawl_delay: float | None = Field(None, ge=0.5, le=30)
    extra_seed_urls: list[str] = Field(default_factory=list)


@router.get("/projects/{project_id}/competitors")
def list_competitors(p: Project = Depends(get_project), db: Session = Depends(get_db)):
    out = []
    for c in db.scalars(select(Competitor).where(Competitor.project_id == p.id).order_by(Competitor.id)):
        d = to_dict(c)
        cj = db.scalars(select(CrawlJob).where(CrawlJob.competitor_id == c.id).order_by(CrawlJob.id.desc())).first()
        d["last_crawl"] = to_dict(cj) if cj else None
        if cj and cj.job_run_id:
            jr = db.get(JobRun, cj.job_run_id)
            d["last_job"] = to_dict(jr, {"result"}) if jr else None
        else:
            jr = db.scalars(select(JobRun).where(JobRun.project_id == p.id, JobRun.job_type == "CRAWL_COMPETITOR").order_by(JobRun.id.desc())).first()
            d["last_job"] = to_dict(jr, {"result"}) if jr and (jr.params or {}).get("competitor_id") == c.id else None
        d["categories"] = db.scalar(select(func.count()).where(CompetitorCategory.competitor_id == c.id)) or 0
        d["seed_urls"] = [s.url for s in db.scalars(select(CompetitorSeedUrl).where(CompetitorSeedUrl.competitor_id == c.id))]
        out.append(d)
    return out


@router.post("/projects/{project_id}/competitors")
def add_competitor(body: CompetitorIn, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    if not body.start_url.startswith(("http://", "https://")):
        raise HTTPException(400, "Start URL must start with http:// or https://")
    data = body.model_dump(exclude={"extra_seed_urls"})
    c = Competitor(project_id=p.id, **data)
    db.add(c)
    db.flush()
    db.add(CompetitorSeedUrl(competitor_id=c.id, url=body.start_url))
    db.commit()
    return to_dict(c)


@router.patch("/projects/{project_id}/competitors/{competitor_id}")
def update_competitor(competitor_id: int, body: dict = Body(...), p: Project = Depends(get_project), db: Session = Depends(get_db)):
    c = db.get(Competitor, competitor_id)
    if c is None or c.project_id != p.id:
        raise HTTPException(404, "competitor not found")
    for k in ("name", "start_url", "target_category", "max_urls", "max_depth", "include_patterns", "exclude_patterns", "render_js", "crawl_delay"):
        if k in body:
            setattr(c, k, body[k])
    db.commit()
    return to_dict(c)


@router.delete("/projects/{project_id}/competitors/{competitor_id}")
def delete_competitor(competitor_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    c = db.get(Competitor, competitor_id)
    if c is None or c.project_id != p.id:
        raise HTTPException(404, "competitor not found")
    db.execute(delete(CompetitorMapping).where(CompetitorMapping.competitor_id == c.id))
    db.delete(c)
    db.commit()
    return {"deleted": True}


@router.post("/projects/{project_id}/competitors/{competitor_id}/crawl")
def start_crawl(competitor_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    c = db.get(Competitor, competitor_id)
    if c is None or c.project_id != p.id:
        raise HTTPException(404, "competitor not found")
    running = db.scalars(select(JobRun).where(JobRun.project_id == p.id, JobRun.job_type == "CRAWL_COMPETITOR",
                                              JobRun.status.in_(("QUEUED", "RUNNING")))).all()
    if any((j.params or {}).get("competitor_id") == c.id for j in running):
        raise HTTPException(409, "A crawl for this competitor is already queued or running")
    job = enqueue(db, p.id, "CRAWL_COMPETITOR", {"competitor_id": c.id})
    c.status = "QUEUED"
    db.commit()
    return to_dict(job)


@router.get("/projects/{project_id}/crawl-pages")
def list_crawl_pages(competitor_id: int | None = None, page_type: str | None = None, errors: bool | None = None,
                     page: Page = Depends(), p: Project = Depends(get_project), db: Session = Depends(get_db)):
    latest = {}
    for j in db.scalars(select(CrawlJob).where(CrawlJob.project_id == p.id).order_by(CrawlJob.id.desc())):
        latest.setdefault(j.competitor_id, j.id)
    q = select(CrawlPage).where(CrawlPage.crawl_job_id.in_(list(latest.values()) or [-1]))
    if competitor_id:
        q = q.where(CrawlPage.competitor_id == competitor_id)
    if page_type:
        q = q.where(CrawlPage.page_type.in_(multi(page_type)))
    if errors:
        q = q.where(CrawlPage.error.is_not(None))
    return paginate(db, q, CrawlPage, page, [CrawlPage.url, CrawlPage.title, CrawlPage.h1, CrawlPage.breadcrumb_text], default_sort=CrawlPage.id)


@router.get("/projects/{project_id}/competitor-categories")
def list_comp_categories(competitor_id: int | None = None, page: Page = Depends(), p: Project = Depends(get_project), db: Session = Depends(get_db)):
    q = select(CompetitorCategory).where(CompetitorCategory.project_id == p.id)
    if competitor_id:
        q = q.where(CompetitorCategory.competitor_id == competitor_id)
    return paginate(db, q, CompetitorCategory, page, [CompetitorCategory.name, CompetitorCategory.breadcrumb],
                    default_sort=[CompetitorCategory.competitor_id, CompetitorCategory.breadcrumb])


@router.get("/projects/{project_id}/competitor-categories/tree")
def comp_tree(competitor_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    cats = db.scalars(select(CompetitorCategory).where(CompetitorCategory.competitor_id == competitor_id).order_by(CompetitorCategory.breadcrumb)).all()
    maps = {m.competitor_category_id: m for m in db.scalars(select(CompetitorMapping).where(CompetitorMapping.competitor_id == competitor_id))}
    by_parent = defaultdict(list)
    for c in cats:
        by_parent[c.parent_id].append(c)

    def build(c):
        m = maps.get(c.id)
        return {"id": c.id, "name": c.name, "url": c.url, "depth": c.depth, "is_inferred": c.is_inferred, "source": c.hierarchy_source,
                "match_type": m.match_type if m else None, "children": [build(k) for k in by_parent.get(c.id, [])]}
    return [build(c) for c in by_parent.get(None, [])]


@router.get("/projects/{project_id}/competitor-mappings")
def list_comp_mappings(match_type: str | None = None, competitor_id: int | None = None, review_status: str | None = None,
                       page: Page = Depends(), p: Project = Depends(get_project), db: Session = Depends(get_db)):
    q = select(CompetitorMapping).where(CompetitorMapping.project_id == p.id)
    if match_type:
        q = q.where(CompetitorMapping.match_type.in_(multi(match_type)))
    if competitor_id:
        q = q.where(CompetitorMapping.competitor_id == competitor_id)
    if review_status:
        q = q.where(CompetitorMapping.review_status.in_(multi(review_status)))
    nodes = {n.id: n for n in db.scalars(select(CategoryNode).where(CategoryNode.project_id == p.id))}
    comps = {c.id: c.name for c in db.scalars(select(Competitor).where(Competitor.project_id == p.id))}

    def extra(rows, items):
        ccs = {c.id: c for c in db.scalars(select(CompetitorCategory).where(CompetitorCategory.id.in_([r.competitor_category_id for r in rows] or [-1])))}
        for r, it in zip(rows, items):
            cc = ccs.get(r.competitor_category_id)
            n = nodes.get(r.matched_node_id)
            pn = nodes.get(r.parent_matched_node_id)
            it.update({"competitor": comps.get(r.competitor_id), "competitor_category": cc.name if cc else None,
                       "competitor_breadcrumb": cc.breadcrumb if cc else None, "competitor_url": cc.url if cc else None,
                       "my_category": n.name_cn if n else None, "my_breadcrumb": n.breadcrumb_cn if n else None, "my_url": n.url if n else None,
                       "parent_maps_to": pn.name_cn if pn else None})
        return items
    return paginate(db, q, CompetitorMapping, page, [CompetitorMapping.reason], default_sort=[CompetitorMapping.competitor_id, CompetitorMapping.id], extra=extra)


# ============================================================== gaps
@router.get("/projects/{project_id}/gaps")
def list_gaps(gap_type: str | None = None, priority: str | None = None, review_status: str | None = None, competitor: str | None = None,
              parent_child: bool | None = None, page: Page = Depends(), p: Project = Depends(get_project), db: Session = Depends(get_db)):
    q = select(TaxonomyGap).where(TaxonomyGap.project_id == p.id)
    if gap_type:
        q = q.where(TaxonomyGap.gap_type.in_(multi(gap_type)))
    if parent_child:
        q = q.where(TaxonomyGap.gap_type.in_(("MISSING PARENT", "MISSING CHILD", "BOTH MISSING", "MISPLACED EXISTING CATEGORY")))
    if priority:
        q = q.where(TaxonomyGap.priority.in_(multi(priority)))
    if review_status:
        q = q.where(TaxonomyGap.review_status.in_(multi(review_status)))

    def extra(rows, items):
        kids = defaultdict(list)
        for c in db.scalars(select(GapChild).where(GapChild.gap_id.in_([r.id for r in rows] or [-1]))):
            kids[c.gap_id].append(to_dict(c))
        for r, it in zip(rows, items):
            it["children"] = kids.get(r.id, [])
        if competitor:
            want = set(multi(competitor))
            items = [it for it in items if want & set((it.get("competitor_evidence") or {}).keys())]
        return items
    return paginate(db, q, TaxonomyGap, page, [TaxonomyGap.main_name_cn, TaxonomyGap.parent_name_cn, TaxonomyGap.suggested_breadcrumb_cn],
                    default_sort=[TaxonomyGap.score.desc()], extra=extra)


# ============================================================== synonyms
class SynonymIn(BaseModel):
    alias: str
    canonical: str
    preferred_node_id: int | None = None
    preferred_category_name: str | None = None
    notes: str | None = None
    approved_by: str | None = None


@router.get("/projects/{project_id}/synonyms")
def list_synonyms(source: str | None = None, page: Page = Depends(), p: Project = Depends(get_project), db: Session = Depends(get_db)):
    q = select(Synonym).where(Synonym.project_id == p.id)
    if source:
        q = q.where(Synonym.source.in_(multi(source)))
    return paginate(db, q, Synonym, page, [Synonym.alias, Synonym.canonical, Synonym.preferred_category_name], default_sort=Synonym.canonical)


@router.post("/projects/{project_id}/synonyms")
def add_synonym(body: SynonymIn, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    k = norm_key(body.alias)
    if not k or not norm_key(body.canonical):
        raise HTTPException(400, "alias and canonical are required")
    s = db.scalars(select(Synonym).where(Synonym.project_id == p.id, Synonym.alias_norm == k)).first()
    if s is None:
        s = Synonym(project_id=p.id, alias_norm=k)
        db.add(s)
    for f, v in body.model_dump().items():
        setattr(s, f, v)
    if s.preferred_node_id and not s.preferred_category_name:
        n = db.get(CategoryNode, s.preferred_node_id)
        s.preferred_category_name = n.name_cn if n else None
    s.source = "HUMAN"
    s.approved_by = body.approved_by or "reviewer"
    db.commit()
    return to_dict(s)


@router.put("/projects/{project_id}/synonyms/{synonym_id}")
def update_synonym(synonym_id: int, body: SynonymIn, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    s = db.get(Synonym, synonym_id)
    if s is None or s.project_id != p.id:
        raise HTTPException(404, "synonym not found")
    for f, v in body.model_dump().items():
        setattr(s, f, v)
    s.alias_norm, s.source = norm_key(body.alias), "HUMAN"
    s.approved_by = body.approved_by or s.approved_by or "reviewer"
    db.commit()
    return to_dict(s)


@router.delete("/projects/{project_id}/synonyms/{synonym_id}")
def delete_synonym(synonym_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    s = db.get(Synonym, synonym_id)
    if s is None or s.project_id != p.id:
        raise HTTPException(404, "synonym not found")
    db.delete(s)
    db.commit()
    return {"deleted": True}


@router.get("/projects/{project_id}/synonyms/export")
def export_synonyms(format: str = "xlsx", p: Project = Depends(get_project), db: Session = Depends(get_db)):
    from ..exporter import Sheet, to_csv, to_xlsx

    syns = db.scalars(select(Synonym).where(Synonym.project_id == p.id).order_by(Synonym.canonical)).all()
    sh = Sheet("Synonyms", ["Alias", "Canonical Concept", "Preferred Category ID", "Preferred Category Name", "Notes", "Approved By", "Source"],
               [[s.alias, s.canonical, s.preferred_node_id, s.preferred_category_name, s.notes, s.approved_by, s.source] for s in syns])
    data = to_xlsx([sh]) if format == "xlsx" else to_csv([sh])
    return _file(f"Synonyms - {p.name}.{format}", data, format)


# ============================================================== review
class ReviewIn(BaseModel):
    entity_type: str
    entity_ids: list[int]
    action: str
    payload: dict = Field(default_factory=dict)
    reviewer: str | None = None


@router.get("/review-actions")
def review_action_catalog():
    return ACTIONS


@router.post("/projects/{project_id}/review")
def review(body: ReviewIn, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    results = []
    try:
        for eid in body.entity_ids:
            results.append(apply_review(db, p.id, body.entity_type, eid, body.action, body.payload, body.reviewer))
    except ReviewError as e:
        db.rollback()
        raise HTTPException(400, str(e))
    db.commit()
    return {"results": results}


@router.get("/projects/{project_id}/review-queue")
def review_queue(entity_type: str | None = None, limit: int = Query(200, le=2000), p: Project = Depends(get_project), db: Session = Depends(get_db)):
    pid, items = p.id, []
    nodes = {n.id: n for n in db.scalars(select(CategoryNode).where(CategoryNode.project_id == pid))}
    types = set(multi(entity_type)) or {"srp", "audit", "gap", "competitor_mapping"}
    if "srp" in types:
        for s in db.scalars(select(SRP).where(SRP.project_id == pid, SRP.review_status.in_(("NEEDS_REVIEW", "LOW_CONFIDENCE", "NO_MATCH")))
                            .order_by(SRP.search_volume.desc().nullslast()).limit(limit)):
            n = nodes.get(s.matched_node_id)
            items.append({"entity_type": "srp", "id": s.id, "title": s.keyword, "status": s.review_status, "confidence": s.confidence,
                          "current": n.breadcrumb_cn if n else "NO_MATCH", "recommended": s.breadcrumb_cn, "reason": s.reason,
                          "search_volume": s.search_volume, "candidates": s.candidates, "kind": s.confidence_band})
    if "audit" in types:
        for a in db.scalars(select(BreadcrumbAudit).where(BreadcrumbAudit.project_id == pid, BreadcrumbAudit.review_status == "NEEDS_REVIEW").limit(limit)):
            items.append({"entity_type": "audit", "id": a.id, "title": a.category_name, "status": a.review_status, "confidence": a.confidence,
                          "current": a.current_breadcrumb_cn, "recommended": a.recommended_breadcrumb_cn, "reason": a.reason, "kind": a.action,
                          "linking": a.linking_improvement})
    if "gap" in types:
        for g in db.scalars(select(TaxonomyGap).where(TaxonomyGap.project_id == pid, TaxonomyGap.review_status == "NEEDS_REVIEW")
                            .order_by(TaxonomyGap.score.desc()).limit(limit)):
            items.append({"entity_type": "gap", "id": g.id, "title": g.main_name_cn or g.parent_name_cn, "status": g.review_status, "confidence": g.confidence,
                          "current": g.current_breadcrumb_cn, "recommended": g.suggested_breadcrumb_cn, "reason": g.reason, "kind": g.gap_type,
                          "priority": g.priority, "search_volume": g.combined_search_volume})
    if "competitor_mapping" in types:
        ccs = {c.id: c for c in db.scalars(select(CompetitorCategory).where(CompetitorCategory.project_id == pid))}
        for m in db.scalars(select(CompetitorMapping).where(CompetitorMapping.project_id == pid, CompetitorMapping.review_status == "NEEDS_REVIEW",
                                                            CompetitorMapping.match_type.in_(("AMBIGUOUS", "SEMANTIC MATCH", "EXISTING BUT MISPLACED"))).limit(limit)):
            cc = ccs.get(m.competitor_category_id)
            n = nodes.get(m.matched_node_id)
            items.append({"entity_type": "competitor_mapping", "id": m.id, "title": cc.name if cc else "?", "status": m.review_status,
                          "confidence": m.confidence, "current": cc.breadcrumb if cc else None, "recommended": n.breadcrumb_cn if n else None,
                          "reason": m.reason, "kind": m.match_type})
    return {"items": items, "total": len(items)}


@router.get("/projects/{project_id}/approved-rules")
def approved_rules(entity_type: str | None = None, page: Page = Depends(), p: Project = Depends(get_project), db: Session = Depends(get_db)):
    q = select(ApprovedMapping).where(ApprovedMapping.project_id == p.id)
    if entity_type:
        q = q.where(ApprovedMapping.entity_type.in_(multi(entity_type)))
    return paginate(db, q, ApprovedMapping, page, [ApprovedMapping.match_key], default_sort=ApprovedMapping.id.desc())


@router.delete("/projects/{project_id}/approved-rules/{rule_id}")
def delete_rule(rule_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    r = db.get(ApprovedMapping, rule_id)
    if r is None or r.project_id != p.id:
        raise HTTPException(404, "rule not found")
    db.delete(r)
    db.commit()
    return {"deleted": True}


@router.get("/projects/{project_id}/history")
def history(page: Page = Depends(), p: Project = Depends(get_project), db: Session = Depends(get_db)):
    reviews = paginate(db, select(ReviewAction).where(ReviewAction.project_id == p.id), ReviewAction, page, default_sort=ReviewAction.id.desc())
    overrides = [to_dict(o) for o in db.scalars(select(ManualOverride).where(ManualOverride.project_id == p.id).order_by(ManualOverride.id.desc()).limit(200))]
    exports = [to_dict(e) for e in db.scalars(select(Export).where(Export.project_id == p.id).order_by(Export.id.desc()).limit(200))]
    jobs = [to_dict(j, {"result"}) for j in db.scalars(select(JobRun).where(JobRun.project_id == p.id).order_by(JobRun.id.desc()).limit(200))]
    return {"reviews": reviews, "overrides": overrides, "exports": exports, "jobs": jobs}


# ============================================================== category focus
@router.get("/projects/{project_id}/category-focus")
def category_focus_ep(category: str = Query(..., min_length=1), competitor_id: str | None = None,
                      format: str = Query("json", pattern="^(json|xlsx|csv)$"), p: Project = Depends(get_project), db: Session = Depends(get_db)):
    from ..core.context import load_context
    from ..core.focus import category_focus
    from ..exporter import focus_sheets, to_csv, to_xlsx

    ctx = load_context(db, p)
    ids = [int(x) for x in multi(competitor_id)] or None
    res = category_focus(db, ctx, category.strip(), ids)
    if format == "json":
        return res
    sheets = focus_sheets(res)
    data = to_xlsx(sheets) if format == "xlsx" else to_csv(sheets)
    db.add(Export(project_id=p.id, export_key=f"category_focus:{category}", format=format,
                  filename=f"Category Focus - {category}.{format}", row_count=len(res["rows"])))
    db.commit()
    return _file(f"Category Focus - {category}.{format}", data, format)


# ============================================================== exports
def _file(name: str, data: bytes, fmt: str) -> Response:
    from urllib.parse import quote

    mt = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if fmt == "xlsx" else "text/csv; charset=utf-8"
    return Response(content=data, media_type=mt,
                    headers={"Content-Disposition": f"attachment; filename=\"export.{fmt}\"; filename*=UTF-8''{quote(name)}"})


@router.get("/exports")
def export_catalog():
    return [{"key": k, "title": t, "number": i + 1} for i, (k, (t, _)) in enumerate(EXPORTS.items())]


@router.get("/projects/{project_id}/exports/{export_key}")
def download_export(export_key: str, format: str = Query("xlsx", pattern="^(xlsx|csv)$"), p: Project = Depends(get_project), db: Session = Depends(get_db)):
    if export_key not in EXPORTS:
        raise HTTPException(404, "unknown export")
    name, data, _ = build_export(db, p.id, export_key, format)
    db.commit()
    return _file(name, data, format)
