"""Category Focus: for one category name, list every competitor category / URL in that
category, its breadcrumb, whether it exists in the current (Coupang) taxonomy, and —
when missing — where it fits based on the current taxonomy."""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..crawler.classify import strip_home
from ..models import (
    SRP, CategoryNode, Competitor, CompetitorCategory, CompetitorMapping, CrawlJob, CrawlPage, GapChild, TaxonomyGap,
)
from .context import EngineContext
from .gaps import SrpIndex
from .matcher import group_profile
from .normalize import norm_key
from .srp_mapping import node_en_path

PRESENT_TYPES = {"EXACT MATCH": "PRESENT", "SEMANTIC MATCH": "PRESENT", "EXISTING BUT MISPLACED": "PRESENT (MISPLACED)",
                 "COMPETITOR MORE GENERAL": "PRESENT (BROADER)", "COMPETITOR MORE SPECIFIC": "MISSING",
                 "MISSING FROM MY TAXONOMY": "MISSING", "AMBIGUOUS": "REVIEW"}
ANCHOR_TYPES = ("EXACT MATCH", "SEMANTIC MATCH", "EXISTING BUT MISPLACED", "COMPETITOR MORE GENERAL")


class FocusMatcher:
    def __init__(self, ctx: EngineContext, term: str):
        self.ctx = ctx
        v = ctx.vocab
        k = norm_key(term)
        canon = v.canonical(k) or k
        keys = {k, canon}
        for ak, t in v.alias.items():
            if t.canonical_key in keys:
                keys.add(ak)
        # English input ("mouse") → Chinese category names via the taxonomy's EN names
        for n in ctx.index.nodes.values():
            if n.name_en and norm_key(n.name_en) in keys:
                keys.add(n.norm_key)
        self.keys = {x for x in keys if x}
        self.group, self.stems, _ = group_profile(term, v)

    def label(self, label: str) -> bool:
        k = norm_key(label)
        if not k:
            return False
        if k in self.keys or (self.ctx.vocab.canonical(k) in self.keys):
            return True
        if any(len(x) >= 2 and x in k for x in self.keys):
            return True
        if self.group and self.stems:
            g, stems, _ = group_profile(label, self.ctx.vocab)
            return g and bool(stems & self.stems)
        return False

    def path(self, labels: list[str]) -> bool:
        return any(self.label(l) for l in labels)


def _latest_jobs(db: Session, pid: int) -> dict[int, int]:
    latest: dict[int, int] = {}
    for j in db.scalars(select(CrawlJob).where(CrawlJob.project_id == pid).order_by(CrawlJob.id.desc())):
        latest.setdefault(j.competitor_id, j.id)
    return latest


def category_focus(db: Session, ctx: EngineContext, term: str, competitor_ids: list[int] | None = None) -> dict:
    pid, idx = ctx.project.id, ctx.index
    fm = FocusMatcher(ctx, term)
    tr = ctx.translator()

    # Coupang side: matching nodes + their descendants
    focus_nodes: dict[int, CategoryNode] = {}
    for n in idx.real_nodes():
        if fm.label(n.name_cn) or (n.name_en and fm.label(n.name_en)):
            focus_nodes[n.id] = n
            for d in idx.descendants(n):
                focus_nodes[d.id] = d
    top_focus = sorted((n for n in focus_nodes.values() if fm.label(n.name_cn) or (n.name_en and fm.label(n.name_en))), key=lambda n: (n.depth, n.breadcrumb_cn))

    comps = {c.id: c.name for c in db.scalars(select(Competitor).where(Competitor.project_id == pid))}
    if competitor_ids:
        comps = {k: v for k, v in comps.items() if k in competitor_ids}
    cats = {c.id: c for c in db.scalars(select(CompetitorCategory).where(CompetitorCategory.project_id == pid, CompetitorCategory.competitor_id.in_(list(comps) or [-1])))}
    maps = {m.competitor_category_id: m for m in db.scalars(select(CompetitorMapping).where(CompetitorMapping.project_id == pid))}
    gaps = db.scalars(select(TaxonomyGap).where(TaxonomyGap.project_id == pid)).all()
    gap_children = defaultdict(list)
    if gaps:
        for c in db.scalars(select(GapChild).where(GapChild.gap_id.in_([g.id for g in gaps]))):
            gap_children[c.gap_id].append(c)
    srps = db.scalars(select(SRP).where(SRP.project_id == pid)).all()
    sidx = SrpIndex(srps, ctx)

    def labels_of(cc: CompetitorCategory) -> list[str]:
        return cc.breadcrumb.split(" > ")

    def anchor_for(cc: CompetitorCategory) -> tuple[CategoryNode | None, list[str]]:
        """Nearest competitor ancestor that maps to an existing node; labels to add below it."""
        chain = [cc]
        cur = cats.get(cc.parent_id) if cc.parent_id else None
        while cur is not None:
            m = maps.get(cur.id)
            if m and m.match_type in ANCHOR_TYPES and m.matched_node_id in idx.nodes:
                return idx.nodes[m.matched_node_id], [c.name for c in reversed(chain)]
            chain.append(cur)
            cur = cats.get(cur.parent_id) if cur.parent_id else None
        return None, [c.name for c in reversed(chain)]

    def gap_suggestion(name: str) -> tuple[str | None, str | None, str | None, str | None]:
        k = norm_key(name)
        for g in gaps:
            if g.review_status == "REJECTED":
                continue
            if norm_key(g.main_name_cn or "") == k and g.gap_type not in ("MISSING PARENT", "BOTH MISSING"):
                return g.suggested_breadcrumb_cn, g.suggested_breadcrumb_en, g.gap_type, g.recommended_action
            if norm_key(g.parent_name_cn or "") == k and g.gap_type in ("MISSING PARENT", "BOTH MISSING"):
                return g.suggested_breadcrumb_cn, g.suggested_breadcrumb_en, g.gap_type, g.recommended_action
            for c in gap_children[g.id]:
                if norm_key(c.name_cn) == k and c.status in ("NEW", "SRP ONLY"):
                    return c.suggested_breadcrumb_cn, c.suggested_breadcrumb_en, g.gap_type, g.recommended_action
        return None, None, None, None

    def en_label(label: str) -> str | None:
        return tr.lookup(label)[0]

    rows = []
    unmapped = 0
    for cc in sorted(cats.values(), key=lambda c: (c.competitor_id, c.breadcrumb)):
        m = maps.get(cc.id)
        in_focus = fm.path(labels_of(cc)) or (m is not None and m.matched_node_id in focus_nodes)
        if not in_focus:
            continue
        if m is None:
            unmapped += 1
        status = PRESENT_TYPES.get(m.match_type, "REVIEW") if m else "NOT COMPARED"
        node = idx.nodes.get(m.matched_node_id) if m and m.matched_node_id else None
        row = {
            "competitor": comps.get(cc.competitor_id), "competitor_category": cc.name, "competitor_breadcrumb": cc.breadcrumb,
            "competitor_url": cc.url, "depth": cc.depth, "hierarchy_source": cc.hierarchy_source,
            "products_seen": cc.product_link_count, "classification": m.match_type if m else None, "status": status,
            "coupang_category": None, "coupang_url": None, "coupang_breadcrumb_cn": None, "coupang_breadcrumb_en": None,
            "suggested_parent": None, "suggested_parent_status": None, "suggested_breadcrumb_cn": None, "suggested_breadcrumb_en": None,
            "gap_type": None, "recommended_action": None, "reason": m.reason if m else "Run 'Compare taxonomies' first.",
            "confidence": m.confidence if m else None,
        }
        if node is not None and status.startswith("PRESENT"):
            row.update(coupang_category=node.name_cn, coupang_url=node.url, coupang_breadcrumb_cn=node.breadcrumb_cn,
                       coupang_breadcrumb_en=node_en_path(ctx, node, tr)[0])
            if status == "PRESENT (MISPLACED)" and m.parent_matched_node_id in idx.nodes:
                p = idx.nodes[m.parent_matched_node_id]
                row.update(suggested_parent=p.name_cn, suggested_parent_status="EXISTING",
                           suggested_breadcrumb_cn=f"{p.breadcrumb_cn} > {node.name_cn}", gap_type="MISPLACED EXISTING CATEGORY",
                           recommended_action="MOVE (do not create a duplicate page)")
                pen = node_en_path(ctx, p, tr)[0]
                row["suggested_breadcrumb_en"] = f"{pen} > {node.name_en}" if pen and node.name_en else None
        elif status in ("MISSING", "REVIEW"):
            g_cn, g_en, g_type, g_action = gap_suggestion(cc.name)
            if status == "MISSING" and m and m.match_type == "COMPETITOR MORE SPECIFIC" and node is not None:
                anchor, extra = node, [cc.name]
            else:
                anchor, extra = anchor_for(cc)
                if anchor is None and top_focus:
                    anchor = top_focus[0]
                    extra = [l for l in labels_of(cc) if not fm.label(l)] or [cc.name]
            base_cn = anchor.breadcrumb_cn if anchor else (idx.root.name_cn if idx.root else "")
            calc_cn = " > ".join([x for x in [base_cn, *extra] if x])
            base_en = node_en_path(ctx, anchor, tr)[0] if anchor else (idx.root.name_en if idx.root else None)
            en_parts = [en_label(x) for x in extra]
            calc_en = " > ".join([base_en, *en_parts]) if base_en and all(en_parts) else None
            row.update(
                coupang_category=node.name_cn if node is not None else None,
                coupang_breadcrumb_cn=node.breadcrumb_cn if node is not None else None,
                suggested_parent=(extra[-2] if len(extra) > 1 else (anchor.name_cn if anchor else None)),
                suggested_parent_status=("NEW" if len(extra) > 1 else ("EXISTING" if anchor else "MISSING")),
                suggested_breadcrumb_cn=g_cn or calc_cn, suggested_breadcrumb_en=g_en or calc_en,
                gap_type=g_type or ("MISSING CHILD" if len(extra) == 1 else "BOTH MISSING"),
                recommended_action=g_action or ("CREATE CHILD" if len(extra) == 1 else "CREATE PARENT + CREATE CHILD"),
            )
        sup = sidx.support([cc.name])
        row["supporting_srps"] = [{"keyword": s.keyword, "search_volume": s.search_volume} for s, _ in sorted(sup, key=lambda x: -(x[0].search_volume or 0))[:15]]
        row["srp_count"] = len(sup)
        row["search_volume"] = sum(s.search_volume or 0 for s, _ in sup)
        rows.append(row)

    # Competitor URLs in this category (category + product pages whose breadcrumb is in focus)
    latest = _latest_jobs(db, pid)
    job_ids = [latest[c] for c in comps if c in latest]
    urls = []
    counts: dict[str, int] = defaultdict(int)
    if job_ids:
        for p in db.scalars(select(CrawlPage).where(CrawlPage.crawl_job_id.in_(job_ids))):
            labels = [c["name"] for c in strip_home(p.breadcrumb or []) if c.get("name")]
            if not (fm.path(labels) or fm.label(p.category_name or "") or fm.label(p.h1 or "")):
                continue
            counts[p.page_type or "UNKNOWN"] += 1
            urls.append({"competitor": comps.get(p.competitor_id), "url": p.url, "page_type": p.page_type, "breadcrumb": p.breadcrumb_text,
                         "h1": p.h1, "title": p.title, "status_code": p.status_code})
    urls.sort(key=lambda u: (u["competitor"] or "", 0 if u["page_type"] in ("CATEGORY", "SUBCATEGORY") else 1, u["breadcrumb"] or ""))

    # Coupang categories in focus and whether any competitor has them
    matched_nodes = defaultdict(set)
    for cc in cats.values():
        m = maps.get(cc.id)
        if m and m.matched_node_id and m.match_type in ANCHOR_TYPES:
            matched_nodes[m.matched_node_id].add(comps.get(cc.competitor_id))
    coupang = [{"category": n.name_cn, "name_en": n.name_en, "breadcrumb_cn": n.breadcrumb_cn, "url": n.url,
                "competitors_with_it": sorted(x for x in matched_nodes.get(n.id, set()) if x)}
               for n in sorted(focus_nodes.values(), key=lambda n: n.breadcrumb_cn) if not n.is_inferred]

    summary = defaultdict(int)
    for r in rows:
        summary[r["status"]] += 1
    return {
        "category": term, "match_keys": sorted(fm.keys),
        "coupang_focus": [{"id": n.id, "name": n.name_cn, "breadcrumb_cn": n.breadcrumb_cn} for n in top_focus[:10]],
        "summary": dict(summary), "url_counts": dict(counts), "unmapped": unmapped,
        "rows": rows, "urls": urls, "coupang_categories": coupang,
    }
