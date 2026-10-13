"""One master workbook: for a category (or the whole taxonomy) every existing category
page, every new page to create, and every SRP page — each with EXISTING / NEW / MOVE /
MERGE / DUPLICATE status, current vs final breadcrumb, competitor coverage, demand and
the action. Rows are ordered by final breadcrumb so the sheet reads like the final tree."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SRP, BreadcrumbAudit, Competitor, CompetitorCategory, CompetitorMapping, GapChild, TaxonomyGap
from .context import EngineContext
from .focus import ANCHOR_TYPES, FocusMatcher
from .normalize import norm_key
from .srp_mapping import node_en_path, same_entity

AUDIT_STATUS = {"KEEP": "EXISTING", "MOVE": "EXISTING → MOVE", "MOVE + CREATE PARENT": "EXISTING → MOVE (new parent)",
                "FLATTEN": "EXISTING → FIX BREADCRUMB", "CONSOLIDATE": "EXISTING → MERGE", "REVIEW": "EXISTING (review)",
                "CREATE CHILD": "EXISTING", "CREATE PARENT": "EXISTING"}


def build_master(db: Session, ctx: EngineContext, term: str | None = None) -> dict:
    pid, idx, vocab = ctx.project.id, ctx.index, ctx.vocab
    tr = ctx.translator()
    fm = FocusMatcher(ctx, term) if term else None

    # ---- scope: focus nodes (+ all descendants), or the whole taxonomy
    if fm:
        scope = {}
        for n in idx.real_nodes():
            if fm.label(n.name_cn, parts=True) or (n.name_en and fm.label(n.name_en)):
                scope[n.id] = n
                for d in idx.descendants(n):
                    scope[d.id] = d
    else:
        scope = {n.id: n for n in idx.real_nodes()}
    scope_paths = [n.breadcrumb_cn for n in scope.values()]

    def path_in_scope(path: str | None) -> bool:
        if not path:
            return False
        if not fm:
            return True
        if any(path == p or path.startswith(p + " > ") for p in scope_paths):
            return True
        return fm.path(path.split(" > "))

    # ---- recommendations
    audits = {a.node_id: a for a in db.scalars(select(BreadcrumbAudit).where(BreadcrumbAudit.project_id == pid))}
    gaps = [g for g in db.scalars(select(TaxonomyGap).where(TaxonomyGap.project_id == pid)) if g.review_status != "REJECTED"]
    kids = defaultdict(list)
    if gaps:
        for c in db.scalars(select(GapChild).where(GapChild.gap_id.in_([g.id for g in gaps]))):
            kids[c.gap_id].append(c)

    # final position of existing nodes (recommended moves), descendants follow their parent
    override: dict[int, tuple[str, str, str]] = {}  # node_id -> (final_path, status, action/reason)
    for nid, a in audits.items():
        if a.action != "KEEP" and a.review_status != "REJECTED" and a.recommended_breadcrumb_cn and a.recommended_breadcrumb_cn != a.current_breadcrumb_cn:
            override[nid] = (a.recommended_breadcrumb_cn, AUDIT_STATUS.get(a.action, "EXISTING → MOVE"), f"{a.action}: {a.reason}")
    for g in gaps:
        if g.gap_type == "MISPLACED EXISTING CATEGORY" and g.main_node_id in idx.nodes and g.suggested_breadcrumb_cn:
            override[g.main_node_id] = (g.suggested_breadcrumb_cn, "EXISTING → MOVE", f"MOVE: {g.reason}")
        if g.gap_type in ("MISSING PARENT", "BOTH MISSING"):
            for c in kids[g.id]:
                if c.status == "EXISTING" and c.existing_node_id in idx.nodes and c.suggested_breadcrumb_cn:
                    override[c.existing_node_id] = (c.suggested_breadcrumb_cn, "EXISTING → MOVE (new parent)",
                                                    f"Reconnect under new parent '{g.parent_name_cn}'")
    memo: dict[int, str] = {}

    def final_path(n) -> str:
        if n.id in memo:
            return memo[n.id]
        if n.id in override:
            p = override[n.id][0]
        elif n.parent_id and n.parent_id in idx.nodes and not idx.nodes[n.parent_id].is_root:
            p = f"{final_path(idx.nodes[n.parent_id])} > {n.name_cn}"
        else:
            p = n.breadcrumb_cn
        memo[n.id] = p
        return p

    def en_path(cn_path: str) -> str | None:
        out = []
        for label in cn_path.split(" > "):
            hit = next((x.name_en for x in idx.by_key.get(norm_key(label), []) if x.name_en), None)
            if hit is None and idx.root and label == idx.root.name_cn:
                hit = idx.root.name_en
            hit = hit or tr.lookup(label)[0]
            if not hit:
                return None
            out.append(hit)
        return " > ".join(out)

    # ---- coverage: competitors per existing node
    comps = {c.id: c.name for c in db.scalars(select(Competitor).where(Competitor.project_id == pid))}
    ccs = {c.id: c for c in db.scalars(select(CompetitorCategory).where(CompetitorCategory.project_id == pid))}
    covered = defaultdict(dict)
    for m in db.scalars(select(CompetitorMapping).where(CompetitorMapping.project_id == pid)):
        if m.matched_node_id and m.match_type in ANCHOR_TYPES and m.competitor_category_id in ccs:
            covered[m.matched_node_id].setdefault(comps.get(m.competitor_id, "?"), ccs[m.competitor_category_id].breadcrumb)

    srps = db.scalars(select(SRP).where(SRP.project_id == pid)).all()
    srp_by_node = defaultdict(list)
    for s in srps:
        if s.matched_node_id:
            srp_by_node[s.matched_node_id].append(s)

    rows: list[dict] = []

    def add(**r):
        r.setdefault("final_en", en_path(r["final_cn"]) if r.get("final_cn") else None)
        rows.append(r)

    # A) existing categories
    for n in scope.values():
        fp = final_path(n)
        ov = override.get(n.id)
        a = audits.get(n.id)
        if ov:
            status, action = ov[1], ov[2]
        elif fp != n.breadcrumb_cn:
            status, action = "EXISTING → PATH CHANGES (ancestor moves)", "Breadcrumb updates because an ancestor moves"
        else:
            status = "EXISTING (breadcrumb only, no page)" if n.is_inferred else "EXISTING"
            action = "KEEP" if a is None or a.action == "KEEP" else f"{a.action}: {a.reason}"
        s_list = srp_by_node.get(n.id, [])
        add(row_type="Category", status=status, name_cn=n.name_cn, name_en=n.name_en, current_cn=n.breadcrumb_cn, final_cn=fp,
            url=n.url, volume=sum(s.search_volume or 0 for s in s_list), srp_count=len(s_list), products=n.product_count,
            competitors=", ".join(covered.get(n.id, {}).keys()), competitor_crumbs="; ".join(f"{k}: {v}" for k, v in covered.get(n.id, {}).items()),
            confidence=audits[n.id].confidence if n.id in audits else None, priority=None, action=action,
            review=audits[n.id].review_status if n.id in audits else None)

    # B) new pages (competitor gaps + SRP-only demand)
    new_paths: dict[str, str] = {}
    for g in gaps:
        def comp_info(g=g):
            ev = g.competitor_evidence or {}
            return ", ".join(ev.keys()), "; ".join(f"{c}: {e['breadcrumb']}" for c, lst in ev.items() for e in lst[:2])
        cs, cc = comp_info()
        if g.gap_type in ("MISSING PARENT", "BOTH MISSING") and path_in_scope(g.suggested_breadcrumb_cn):
            new_paths[g.parent_name_cn] = g.suggested_breadcrumb_cn
            add(row_type="Category", status="NEW", name_cn=g.parent_name_cn, name_en=g.parent_name_en, current_cn=None,
                final_cn=g.suggested_breadcrumb_cn, final_en=g.suggested_breadcrumb_en, url=None, volume=g.combined_search_volume,
                srp_count=g.srp_count, products=g.product_count, competitors=cs, competitor_crumbs=cc, confidence=g.confidence,
                priority=g.priority, action=g.recommended_action, review=g.review_status)
            for c in kids[g.id]:
                if c.status == "NEW" and path_in_scope(c.suggested_breadcrumb_cn):
                    new_paths[c.name_cn] = c.suggested_breadcrumb_cn
                    add(row_type="Category", status="NEW", name_cn=c.name_cn, name_en=c.name_en, current_cn=None,
                        final_cn=c.suggested_breadcrumb_cn, final_en=c.suggested_breadcrumb_en, url=None, volume=c.search_volume,
                        srp_count=len(c.supporting_srps or []), products=None, competitors=cs, competitor_crumbs=cc,
                        confidence=g.confidence, priority=g.priority, action=f"Create under '{g.parent_name_cn}'", review=g.review_status)
        elif g.gap_type in ("MISSING CHILD", "SRP-ONLY GAP") and g.suggested_breadcrumb_cn and path_in_scope(g.suggested_breadcrumb_cn) \
                and not g.recommended_action.startswith("DO NOT"):
            new_paths[g.main_name_cn] = g.suggested_breadcrumb_cn
            add(row_type="Category", status="NEW" if g.gap_type == "MISSING CHILD" else "NEW (SRP demand only)",
                name_cn=g.main_name_cn, name_en=g.main_name_en, current_cn=None, final_cn=g.suggested_breadcrumb_cn,
                final_en=g.suggested_breadcrumb_en, url=None, volume=g.combined_search_volume, srp_count=g.srp_count,
                products=g.product_count, competitors=cs, competitor_crumbs=cc, confidence=g.confidence, priority=g.priority,
                action=g.recommended_action, review=g.review_status)

    # C) SRP pages
    from .gaps import SrpIndex

    sidx = SrpIndex([s for s in srps if not s.matched_node_id], ctx)
    claimed: set[int] = set()
    for name, path in new_paths.items():
        for s, _ in sidx.support([name]):
            if s.id in claimed:
                continue
            claimed.add(s.id)
            leaf = s.h1 or s.keyword
            add(row_type="SRP", status="SRP → NEW CATEGORY", name_cn=s.keyword, name_en=s.keyword_en or s.keyword_en_generated,
                current_cn=None, final_cn=f"{path} > {leaf}", url=s.url, volume=s.search_volume, srp_count=None, products=s.product_count,
                competitors="", competitor_crumbs="", confidence=None, priority=None,
                action=f"Map to new category '{name}' once created", review=s.review_status)
    for nid, s_list in srp_by_node.items():
        n = idx.nodes.get(nid)
        if n is None or nid not in scope:
            continue
        cat_final = final_path(n)
        for s in s_list:
            leaf = s.h1 or s.keyword
            dup = same_entity(vocab, leaf, n)
            final = cat_final if dup else f"{cat_final} > {leaf}"
            if s.duplicate_intent == "YES":
                status, action = "SRP DUPLICATE OF CATEGORY", "Do not index separately — canonical to the category"
            elif s.duplicate_intent == "POTENTIAL":
                status, action = "SRP (possible duplicate)", "Review: likely same intent as the category"
            elif s.review_status in ("NEEDS_REVIEW", "LOW_CONFIDENCE"):
                status, action = "SRP (review mapping)", s.reason or ""
            else:
                status, action = "SRP", "Use final breadcrumb"
            if cat_final != n.breadcrumb_cn and status == "SRP":
                status = "SRP → BREADCRUMB CHANGES"
            add(row_type="SRP", status=status, name_cn=s.keyword, name_en=s.keyword_en or s.keyword_en_generated,
                current_cn=s.breadcrumb_cn, final_cn=final, url=s.url, volume=s.search_volume, srp_count=None, products=s.product_count,
                competitors="", competitor_crumbs="", confidence=s.confidence, priority=None, action=action, review=s.review_status)

    order = {"Category": 0, "SRP": 1}
    rows.sort(key=lambda r: (r["final_cn"] or "", order[r["row_type"]]))
    summary = defaultdict(int)
    for r in rows:
        summary[(r["row_type"], r["status"])] += 1
    return {"scope": term or "All categories", "rows": rows, "summary": dict(summary),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
