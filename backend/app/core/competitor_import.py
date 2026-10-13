"""Import a competitor crawl you ran yourself (Screaming Frog, Sitebulb, a scraper…)
instead of crawling from the server. Each row becomes a crawl_pages row and is
classified from its URL pattern + breadcrumb, exactly like server-side crawls."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..crawler.classify import strip_home
from ..crawler.urls import is_campaign_url, is_content_url, is_product_url, looks_like_category_url, normalize_url, query_kind
from ..models import Competitor, CrawlJob, CrawlPage
from .fileio import _i, _s, read_table
from .normalize import norm_key, split_breadcrumb

TYPES = {"CATEGORY", "SUBCATEGORY", "PRODUCT", "SRP", "FILTER", "CAMPAIGN", "CONTENT", "UNKNOWN"}
_TYPE_ALIASES = {"category": "CATEGORY", "cat": "CATEGORY", "plp": "CATEGORY", "listing": "CATEGORY", "subcategory": "SUBCATEGORY",
                 "product": "PRODUCT", "pdp": "PRODUCT", "goods": "PRODUCT", "search": "SRP", "srp": "SRP"}


def _classify(url: str, crumbs: list[dict], h1: str | None, given: str | None) -> tuple[str, float]:
    if given:
        g = _TYPE_ALIASES.get(given.strip().lower(), given.strip().upper())
        if g in TYPES:
            if g == "CATEGORY" and len(strip_home(crumbs)) > 1:
                g = "SUBCATEGORY"
            return g, 0.9
    if is_product_url(url):
        return "PRODUCT", 0.0
    qk = query_kind(url)
    if qk == "SEARCH":
        return "SRP", 0.05
    if qk == "FILTER":
        return "FILTER", 0.1
    if is_content_url(url):
        return "CONTENT", 0.05
    if is_campaign_url(url) and not crumbs:
        return "CAMPAIGN", 0.1
    levels = len(strip_home(crumbs))
    score = (0.5 if levels else 0) + (0.3 if looks_like_category_url(url) else 0) + (0.1 if h1 else 0)
    if score < 0.35:
        return "UNKNOWN", score
    return ("CATEGORY" if levels <= 1 else "SUBCATEGORY"), min(1.0, score)


def import_competitor_crawl(db: Session, competitor: Competitor, path: str, mapping: dict[str, str | None],
                            job_run_id: int | None = None, append: bool = False) -> dict:
    _, rows = read_table(path)
    bc_cols = [c for c in (mapping.get("_breadcrumb_columns") or "").split("|") if c]
    get = lambda r, f: r.get(mapping[f]) if mapping.get(f) else None  # noqa: E731
    cj = None
    if append:  # add this file to the competitor's latest crawl (e.g. a crawl split over several exports)
        cj = db.scalars(select(CrawlJob).where(CrawlJob.competitor_id == competitor.id).order_by(CrawlJob.id.desc())).first()
    if cj is None:
        cj = CrawlJob(project_id=competitor.project_id, competitor_id=competitor.id, job_run_id=job_run_id, status="COMPLETED",
                      started_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc))
        db.add(cj)
        db.flush()
    seen: set[str] = set(db.scalars(select(CrawlPage.url).where(CrawlPage.crawl_job_id == cj.id))) if append else set()
    counts: dict[str, int] = {}
    skipped = 0
    for r in rows:
        url = normalize_url(_s(get(r, "url")) or "")
        if not url or url in seen:
            skipped += 1
            continue
        seen.add(url)
        if mapping.get("breadcrumb"):
            labels = split_breadcrumb(_s(get(r, "breadcrumb")))
        else:
            labels = [x for x in (_s(r.get(c)) for c in bc_cols) if x]
        crumbs = [{"name": l, "url": None} for l in labels]
        h1, title = _s(get(r, "h1")), _s(get(r, "title"))
        ptype, conf = _classify(url, crumbs, h1, _s(get(r, "page_type")))
        stripped = strip_home(crumbs)
        # Category pages: make sure the page itself is the last breadcrumb level.
        if ptype in ("CATEGORY", "SUBCATEGORY") and h1 and (not stripped or norm_key(stripped[-1]["name"]) != norm_key(h1)):
            if stripped and not any(norm_key(c["name"]) == norm_key(h1) for c in stripped):
                crumbs.append({"name": h1, "url": url})
                stripped = strip_home(crumbs)
        if stripped and ptype in ("CATEGORY", "SUBCATEGORY"):
            stripped[-1]["url"] = url
        status = _i(get(r, "status_code"))
        page = CrawlPage(
            project_id=competitor.project_id, crawl_job_id=cj.id, competitor_id=competitor.id, url=url,
            status_code=status, canonical=normalize_url(_s(get(r, "canonical")) or "") or None,
            indexability=_s(get(r, "indexability")), title=title, h1=h1, breadcrumb=crumbs,
            breadcrumb_text=" > ".join(c["name"] for c in crumbs) or None, depth=_i(get(r, "depth")) or 0,
            parent_url=normalize_url(_s(get(r, "parent_url")) or "") or None, anchor_text=_s(get(r, "anchor_text")),
            product_link_count=_i(get(r, "product_count")) or 0, page_type=ptype, category_confidence=round(conf, 2),
            category_name=(stripped[-1]["name"] if stripped else None) or h1 or title,
            error=f"HTTP {status}" if status and status >= 400 else None,
        )
        db.add(page)
        counts[ptype] = counts.get(ptype, 0) + 1
    cj.processed_urls = cj.discovered_urls = len(seen)
    cj.status = "COMPLETED"
    competitor.status = "IMPORTED"
    db.flush()
    return {"competitor": competitor.name, "rows": len(rows), "pages": len(seen), "skipped": skipped, "by_type": counts, "crawl_job_id": cj.id}
