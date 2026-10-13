"""Reconstruct each competitor's category tree from crawled pages.

Hierarchy priority: 1) breadcrumb 2) parent→child crawl relationship
3) parent anchor text 4) H1 5) URL structure.
"""
from __future__ import annotations

from collections import defaultdict
from urllib.parse import urlsplit

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..crawler.classify import strip_home
from ..models import Competitor, CompetitorCategory, CrawlJob, CrawlPage
from .normalize import join_breadcrumb, norm_key
from .taxonomy import path_key

TAXONOMY_TYPES = ("CATEGORY", "SUBCATEGORY")


def latest_pages(db: Session, competitor: Competitor) -> list[CrawlPage]:
    job = db.scalars(
        select(CrawlJob).where(CrawlJob.competitor_id == competitor.id, CrawlJob.status.in_(("COMPLETED", "CANCELLED", "RUNNING")))
        .order_by(CrawlJob.id.desc())
    ).first()
    if not job:
        return []
    return db.scalars(select(CrawlPage).where(CrawlPage.crawl_job_id == job.id)).all()


def _clean(name: str | None) -> str | None:
    if not name:
        return None
    n = name.strip()
    for sep in (" - ", " | ", "｜", "－"):
        if sep in n:
            n = n.split(sep)[0].strip()
    return n[:120] or None


def build_competitor_tree(db: Session, competitor: Competitor) -> dict:
    db.execute(delete(CompetitorCategory).where(CompetitorCategory.competitor_id == competitor.id))
    db.flush()
    pages = [p for p in latest_pages(db, competitor) if p.page_type in TAXONOMY_TYPES]
    by_url = {p.url: p for p in pages}
    paths: dict[int, tuple[list[str], str]] = {}

    def page_name(p: CrawlPage) -> str | None:
        crumbs = strip_home(p.breadcrumb or [])
        return _clean((crumbs[-1]["name"] if crumbs else None) or p.anchor_text or p.h1 or p.title)

    def resolve(p: CrawlPage, guard: set[int]) -> tuple[list[str], str]:
        if p.id in paths:
            return paths[p.id]
        crumbs = strip_home(p.breadcrumb or [])
        name = page_name(p)
        if crumbs:
            labels = [c["name"].strip() for c in crumbs if c.get("name")]
            last = crumbs[-1]
            self_name = _clean(p.h1 or p.anchor_text)
            if self_name and norm_key(labels[-1]) != norm_key(self_name) and last.get("url") and last["url"] != p.url:
                labels.append(self_name)  # breadcrumb stops at the parent
            out = (labels, "breadcrumb")
        elif p.parent_url and p.parent_url in by_url and p.id not in guard:
            guard.add(p.id)
            parent_labels, _ = resolve(by_url[p.parent_url], guard)
            label = _clean(p.anchor_text) or name
            out = (parent_labels + [label] if label else parent_labels, "crawl parent + anchor text" if p.anchor_text else "crawl parent + H1")
        else:
            # URL structure: nearest category page whose path is a prefix
            path = urlsplit(p.url).path.rstrip("/")
            parent = None
            for other in pages:
                op = urlsplit(other.url).path.rstrip("/")
                if other.id != p.id and op and path.startswith(op + "/") and (parent is None or len(op) > len(urlsplit(parent.url).path)):
                    parent = other
            if parent is not None and p.id not in guard:
                guard.add(p.id)
                parent_labels, _ = resolve(parent, guard)
                out = (parent_labels + [name] if name else parent_labels, "url structure")
            else:
                out = ([name] if name else [], "h1" if p.h1 else "title")
        paths[p.id] = out
        return out

    drafts: dict[str, dict] = {}
    for p in pages:
        labels, source = resolve(p, set())
        labels = [l for l in labels if l]
        if not labels:
            continue
        crumb_urls = {norm_key(c["name"]): c.get("url") for c in strip_home(p.breadcrumb or []) if c.get("name")}
        for i in range(1, len(labels) + 1):
            pk = path_key(labels[:i])
            d = drafts.setdefault(pk, {"labels": labels[:i], "page": None, "source": None, "url": None})
            if i == len(labels):
                if d["page"] is None or (p.category_confidence or 0) > (d["page"].category_confidence or 0):
                    d["page"], d["source"], d["url"] = p, source, p.url
            elif not d["url"]:
                d["url"] = crumb_urls.get(norm_key(labels[i - 1]))

    nodes: dict[str, CompetitorCategory] = {}
    kids: dict[str, list[str]] = defaultdict(list)
    for pk, d in sorted(drafts.items(), key=lambda kv: len(kv[1]["labels"])):
        labels = d["labels"]
        parent = nodes.get(path_key(labels[:-1])) if len(labels) > 1 else None
        page: CrawlPage | None = d["page"]
        cc = CompetitorCategory(
            project_id=competitor.project_id, competitor_id=competitor.id, page_id=page.id if page else None,
            name=labels[-1], norm_key=norm_key(labels[-1]), url=d["url"],
            parent_id=parent.id if parent else None, parent_name=parent.name if parent else None,
            depth=len(labels) - 1, breadcrumb=join_breadcrumb(labels), path_key=pk,
            hierarchy_source=d["source"] or "breadcrumb ancestor", is_inferred=page is None,
            product_link_count=page.product_link_count if page else 0,
        )
        db.add(cc)
        db.flush()
        nodes[pk] = cc
        if parent:
            kids[parent.path_key].append(cc.name)
    for pk, cc in nodes.items():
        cc.children_names = kids.get(pk, [])
    db.flush()
    by_source: dict[str, int] = defaultdict(int)
    for cc in nodes.values():
        by_source[cc.hierarchy_source] += 1
    return {"competitor": competitor.name, "taxonomy_pages": len(pages), "categories": len(nodes),
            "max_depth": max((c.depth for c in nodes.values()), default=0), "hierarchy_sources": dict(by_source)}
