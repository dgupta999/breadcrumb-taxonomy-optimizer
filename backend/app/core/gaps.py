"""Parent/child taxonomy gap detection, SRP validation and gap scoring.

Gap types:
  MISSING CHILD               parent exists, child missing
  MISSING PARENT              children exist, logical parent missing
  BOTH MISSING                parent and child missing
  MISPLACED EXISTING CATEGORY exists under an unrelated parent → MOVE (never duplicate)
  DUPLICATE                   equivalent category already exists elsewhere → CONSOLIDATE / KEEP EXISTING
  SRP-ONLY GAP                demand in SRP data without any category / competitor evidence

Competitor taxonomy is evidence only: a competitor-only gap without SRP
demand is never recommended for creation (it is scored LOW / MONITOR).
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import SRP, CategoryNode, Competitor, CompetitorCategory, CompetitorMapping, GapChild, TaxonomyGap
from . import llm
from .context import EngineContext
from .lexicon import TEMPORARY_INTENT
from .normalize import classify_modifier, has_cjk, norm_key, normalize
from .srp_mapping import node_en_path

Progress = Callable[[int, int], None]
MATCHED = ("EXACT MATCH", "SEMANTIC MATCH", "EXISTING BUT MISPLACED")
MISSING = ("MISSING FROM MY TAXONOMY", "COMPETITOR MORE SPECIFIC", "COMPETITOR MORE GENERAL")


@dataclass
class ChildDraft:
    name: str
    status: str
    node: CategoryNode | None = None
    competitors: set[str] = field(default_factory=set)


@dataclass
class GapDraft:
    gap_type: str
    key: str
    parent_name: str | None = None
    parent_status: str | None = None
    parent_node: CategoryNode | None = None
    main_name: str | None = None
    main_status: str | None = None
    main_node: CategoryNode | None = None
    place_under: CategoryNode | None = None  # existing anchor for new nodes
    children: dict[str, ChildDraft] = field(default_factory=dict)
    competitor_evidence: dict[str, list[dict]] = field(default_factory=lambda: defaultdict(list))
    product_signal: int = 0
    reason: str = ""
    current_breadcrumb: str | None = None
    extra_srps: list[SRP] = field(default_factory=list)

    def evid(self, comp: str, cc: CompetitorCategory) -> None:
        if not any(e["url"] == cc.url and e["breadcrumb"] == cc.breadcrumb for e in self.competitor_evidence[comp]):
            self.competitor_evidence[comp].append({"name": cc.name, "breadcrumb": cc.breadcrumb, "url": cc.url})
        self.product_signal = max(self.product_signal, cc.product_link_count or 0)


class SrpIndex:
    def __init__(self, srps: list[SRP], ctx: EngineContext):
        self.srps = srps
        self.ctx = ctx
        self.canon = {s.id: ctx.vocab.canonical(norm_key(s.canonical_concept or s.core_product or s.keyword)) for s in srps}
        self.aliases: dict[str, set[str]] = defaultdict(set)
        for ak, t in ctx.vocab.alias.items():
            self.aliases[t.canonical_key].add(ak)

    def support(self, names: list[str]) -> list[tuple[SRP, str]]:
        keys: set[str] = set()
        for n in names:
            if not n:
                continue
            k = norm_key(n)
            if len(k) < 2:
                continue
            c = self.ctx.vocab.canonical(k)
            keys |= {k, c} | self.aliases.get(c, set()) | self.aliases.get(k, set())
        out: list[tuple[SRP, str]] = []
        for s in self.srps:
            sk = s.keyword_norm
            if sk in keys:
                out.append((s, "exact keyword"))
            elif self.canon.get(s.id) in keys:
                out.append((s, "synonym / concept"))
            elif any(len(k) >= 2 and k in sk for k in keys):
                kind = "brand/spec + product"
                if s.modifiers and all(not has_cjk(m) for m in s.modifiers):
                    kind = "brand/spec + product"
                elif s.modifiers:
                    kind = "related product term"
                out.append((s, kind))
        return out


def _is_temporary(name: str) -> bool:
    n = normalize(name)
    return any(w in n for w in TEMPORARY_INTENT)


def detect_gaps(db: Session, ctx: EngineContext, progress: Progress | None = None) -> dict:
    pid = ctx.project.id
    idx = ctx.index
    settings = ctx.project.settings or {}
    strong_volume = int(settings.get("strong_search_volume", 1000))
    strong_inventory = int(settings.get("strong_product_count", 20))
    db.execute(delete(TaxonomyGap).where(TaxonomyGap.project_id == pid))
    db.flush()

    comps = {c.id: c.name for c in db.scalars(select(Competitor).where(Competitor.project_id == pid))}
    cats = {c.id: c for c in db.scalars(select(CompetitorCategory).where(CompetitorCategory.project_id == pid))}
    maps = {m.competitor_category_id: m for m in db.scalars(select(CompetitorMapping).where(CompetitorMapping.project_id == pid))}
    kids: dict[int, list[CompetitorCategory]] = defaultdict(list)
    for c in cats.values():
        if c.parent_id:
            kids[c.parent_id].append(c)
    srps = db.scalars(select(SRP).where(SRP.project_id == pid)).all()
    sidx = SrpIndex(srps, ctx)

    def mapped(cc: CompetitorCategory | None, as_anchor: bool = False) -> CategoryNode | None:
        """Existing node equivalent to a competitor category. As a placement anchor a
        broader match (competitor more general, e.g. '3C' → 電腦3C) is good enough."""
        if cc is None:
            return None
        m = maps.get(cc.id)
        ok = MATCHED + (("COMPETITOR MORE GENERAL",) if as_anchor else ())
        if m and m.match_type in ok and m.matched_node_id in idx.nodes and m.review_status != "REJECTED":
            return idx.nodes[m.matched_node_id]
        return None

    def missing(cc: CompetitorCategory | None) -> bool:
        m = maps.get(cc.id) if cc else None
        if m and m.match_type == "COMPETITOR MORE GENERAL" and m.matched_node_id:
            return False  # broader section that already maps to an existing node
        return bool(m and m.match_type in MISSING and m.review_status != "REJECTED")

    def existing_equivalent(name: str) -> CategoryNode | None:
        k = norm_key(name)
        for key in {k, ctx.vocab.canonical(k)}:
            hit = idx.by_key.get(key)
            if hit:
                return next((n for n in hit if not n.is_inferred), hit[0])
        return None

    def anchor_for_top(cc: CompetitorCategory) -> CategoryNode | None:
        # walk up competitor ancestors until one maps to my taxonomy
        cur = cats.get(cc.parent_id) if cc.parent_id else None
        while cur is not None:
            n = mapped(cur, as_anchor=True)
            if n:
                return n
            cur = cats.get(cur.parent_id) if cur.parent_id else None
        return None

    drafts: dict[str, GapDraft] = {}

    def draft(key: str, **kw) -> GapDraft:
        if key not in drafts:
            drafts[key] = GapDraft(key=key, **kw)
        return drafts[key]

    for cc in sorted(cats.values(), key=lambda c: c.depth):
        comp = comps.get(cc.competitor_id, "?")
        m = maps.get(cc.id)
        if m is None:
            continue
        if m.match_type == "EXISTING BUT MISPLACED" and m.matched_node_id in idx.nodes and m.parent_matched_node_id in idx.nodes:
            node, sp = idx.nodes[m.matched_node_id], idx.nodes[m.parent_matched_node_id]
            g = draft(f"MISPLACED:{node.path_key}", gap_type="MISPLACED EXISTING CATEGORY", parent_name=sp.name_cn, parent_status="EXISTING",
                      parent_node=sp, main_name=node.name_cn, main_status="EXISTING BUT MISPLACED", main_node=node, place_under=sp)
            g.current_breadcrumb = node.breadcrumb_cn
            g.evid(comp, cc)
            g.reason = f"'{node.name_cn}' exists under '{node.parent_name}', but competitors place it under '{sp.name_cn}'. Move it — never create a duplicate page."
            continue
        if not missing(cc):
            continue
        eq = existing_equivalent(cc.name)
        if eq is not None:
            g = draft(f"DUPLICATE:{eq.path_key}", gap_type="DUPLICATE", main_name=eq.name_cn, main_status="DUPLICATE", main_node=eq,
                      parent_name=eq.parent_name, parent_status="EXISTING", parent_node=idx.nodes.get(eq.parent_id))
            g.current_breadcrumb = eq.breadcrumb_cn
            g.evid(comp, cc)
            g.reason = f"Competitor category '{cc.name}' is equivalent to existing '{eq.name_cn}' ({eq.breadcrumb_cn}). Keep the existing page."
            continue
        parent_cc = cats.get(cc.parent_id) if cc.parent_id else None
        pnode = mapped(parent_cc, as_anchor=True)
        if m.match_type == "COMPETITOR MORE SPECIFIC" and m.matched_node_id in idx.nodes:
            pnode = idx.nodes[m.matched_node_id]  # 筆電散熱墊 is a sub-type of my 散熱墊
        mapped_children = [(k, mapped(k)) for k in kids.get(cc.id, [])]
        existing_children = [(k, n) for k, n in mapped_children if n is not None]
        if existing_children:
            # TYPE 2: children exist, logical parent missing
            ex_nodes = [n for _, n in existing_children]
            lca = idx.lca(ex_nodes)
            if lca is not None and lca.id in {n.id for n in ex_nodes}:
                lca = idx.nodes.get(lca.parent_id)
            if lca is not None and lca.is_root:
                lca = None
            # place the new parent where its existing children live, unless the competitor's
            # (mapped) parent is more specific than that
            if pnode is not None and lca is not None and idx.is_ancestor(pnode, lca):
                anchor = lca
            else:
                anchor = pnode or lca or anchor_for_top(cc)
            g = draft(f"MISSING_PARENT:{cc.norm_key}", gap_type="MISSING PARENT", parent_name=cc.name, parent_status="NEW",
                      place_under=anchor, main_name=cc.name, main_status="NEW")
            g.evid(comp, cc)
            for k, n in mapped_children:
                ch = g.children.setdefault(norm_key(n.name_cn if n else k.name), ChildDraft(n.name_cn if n else k.name, "EXISTING" if n else "NEW", n))
                ch.competitors.add(comp)
            g.reason = f"Existing children ({', '.join(n.name_cn for n in ex_nodes[:5])}) have no common '{cc.name}' parent; competitors group them under it."
        elif pnode is not None:
            # TYPE 1: parent exists, child missing
            g = draft(f"MISSING_CHILD:{pnode.path_key}:{cc.norm_key}", gap_type="MISSING CHILD", parent_name=pnode.name_cn, parent_status="EXISTING",
                      parent_node=pnode, main_name=cc.name, main_status="NEW", place_under=pnode)
            g.evid(comp, cc)
            g.reason = f"'{pnode.name_cn}' exists but has no '{cc.name}' child; {comp} has {cc.breadcrumb}."
        elif parent_cc is not None and missing(parent_cc) and f"MISSING_PARENT:{parent_cc.norm_key}" in drafts:
            # sibling of existing children under a missing parent → NEW child of that parent gap
            g = drafts[f"MISSING_PARENT:{parent_cc.norm_key}"]
            ch = g.children.setdefault(cc.norm_key, ChildDraft(cc.name, "NEW"))
            ch.competitors.add(comp)
        elif parent_cc is not None and missing(parent_cc):
            # TYPE 3: both missing → group children under the missing parent
            anchor = anchor_for_top(parent_cc)
            g = draft(f"BOTH_MISSING:{parent_cc.norm_key}", gap_type="BOTH MISSING", parent_name=parent_cc.name, parent_status="NEW",
                      main_name=parent_cc.name, main_status="NEW", place_under=anchor)
            g.evid(comp, parent_cc)
            ch = g.children.setdefault(cc.norm_key, ChildDraft(cc.name, "NEW"))
            ch.competitors.add(comp)
            g.competitor_evidence[comp].append({"name": cc.name, "breadcrumb": cc.breadcrumb, "url": cc.url, "child": True})
            g.reason = f"Neither '{parent_cc.name}' nor its child '{cc.name}' exists in the current taxonomy."
        elif cc.parent_id is None or not kids.get(cc.id):
            anchor = anchor_for_top(cc) or idx.root
            if anchor is None:
                continue
            g = draft(f"MISSING_CHILD:{anchor.path_key}:{cc.norm_key}", gap_type="MISSING CHILD", parent_name=anchor.name_cn,
                      parent_status="EXISTING", parent_node=anchor, main_name=cc.name, main_status="NEW", place_under=anchor)
            g.evid(comp, cc)
            g.reason = f"No '{cc.name}' category exists; {comp} has {cc.breadcrumb}."
        # a missing node whose parent is missing and that has children is handled when its children are visited

    # BOTH MISSING parents that were also picked up as standalone MISSING CHILD → keep the richer one
    for key in [k for k, g in drafts.items() if g.gap_type == "BOTH MISSING"]:
        g = drafts[key]
        for k2 in [k for k, d in drafts.items() if d.gap_type == "MISSING CHILD" and norm_key(d.main_name or "") == norm_key(g.parent_name or "")]:
            other = drafts.pop(k2)
            g.place_under = g.place_under or other.place_under
            for c, ev in other.competitor_evidence.items():
                g.competitor_evidence[c].extend(ev)

    # Taxonomy-internal duplicates (same concept on several existing pages)
    groups: dict[str, list[CategoryNode]] = defaultdict(list)
    for n in idx.real_nodes():
        if not n.is_inferred:
            groups[ctx.vocab.canonical(n.norm_key) or n.norm_key].append(n)
    for concept, nodes in groups.items():
        if len(nodes) < 2:
            continue
        keep = max(nodes, key=lambda d: ((d.product_count or 0), -d.depth))
        g = draft(f"DUPLICATE:{keep.path_key}", gap_type="DUPLICATE", main_name=keep.name_cn, main_status="EXISTING", main_node=keep,
                  parent_name=keep.parent_name, parent_status="EXISTING", parent_node=idx.nodes.get(keep.parent_id))
        g.current_breadcrumb = keep.breadcrumb_cn
        for n in nodes:
            if n.id != keep.id:
                g.children.setdefault(f"dup:{n.id}", ChildDraft(n.name_cn, "DUPLICATE", n))
        g.reason = (g.reason + " " if g.reason else "") + f"Same concept exists on {len(nodes)} pages; keep '{keep.breadcrumb_cn}' and consolidate the others."

    # SRP-only gaps: unmatched SRP demand without any competitor gap
    covered = {norm_key(g.main_name or "") for g in drafts.values()}
    covered |= {norm_key(g.parent_name or "") for g in drafts.values() if g.parent_status == "NEW"}
    covered |= {norm_key(c.name) for g in drafts.values() for c in g.children.values()}
    covered |= {ctx.vocab.canonical(k) for k in list(covered)}
    covered.discard("")

    def srp_label(s: SRP) -> str:
        mods = s.modifiers or []
        if s.core_product and all(classify_modifier(m) in ("BRAND", "SPEC", "GENERIC") for m in mods):
            return s.canonical_concept or s.core_product
        kw = s.keyword
        for m in mods:
            if classify_modifier(m) in ("BRAND", "SPEC", "GENERIC"):
                kw = re.sub(re.escape(m), "", kw, flags=re.I)
        return re.sub(r"\s+", " ", kw).strip() or s.keyword

    clusters: dict[str, list[SRP]] = defaultdict(list)
    for s in srps:
        if s.matched_node_id is None and s.review_status != "REJECTED":
            if any(k in s.keyword_norm for k in covered if len(k) >= 2):
                continue  # demand already attached to a competitor-evidenced gap
            ck = ctx.vocab.canonical(norm_key(srp_label(s)))
            if ck:
                clusters[ck].append(s)
    for ck, members in clusters.items():
        members.sort(key=lambda s: -(s.search_volume or 0))
        label = srp_label(members[0])
        if ck in covered or _is_temporary(" ".join(m.keyword for m in members)):
            # covered gaps get these SRPs through validation; temporary demand is ignored
            if not ck in covered:
                g = draft(f"SRP_ONLY:{ck}", gap_type="SRP-ONLY GAP", main_name=label, main_status="SRP ONLY", parent_status="MISSING")
                g.extra_srps = members
                g.reason = "Unmatched SRP demand with temporary / campaign intent."
            continue
        anchor = None
        for s in members:
            for c in s.candidates or []:
                n = idx.nodes.get(c.get("node_id"))
                if n is not None and c.get("score", 0) >= 25:
                    anchor = n if anchor is None or n.depth < anchor.depth else anchor
        g = draft(f"SRP_ONLY:{ck}", gap_type="SRP-ONLY GAP", main_name=label, main_status="SRP ONLY",
                  parent_name=anchor.name_cn if anchor else None, parent_status="EXISTING" if anchor else "MISSING",
                  parent_node=anchor, place_under=anchor)
        g.extra_srps = members
        g.reason = f"{len(members)} SRP(s) have no matching category" + (f"; closest existing branch '{anchor.name_cn}' (verify parent)." if anchor else "; parent must be chosen.")

    # ---------------------------------------------------------------- validate, score, persist
    budget = llm.LLMBudget()
    tr = ctx.translator(budget)
    for g in drafts.values():
        for l in (g.parent_name, g.main_name, *[c.name for c in g.children.values()]):
            if l:
                tr.want(l)
    tr.flush()

    def en(label: str | None) -> tuple[str | None, str]:
        if not label:
            return None, "MISSING"
        n = existing_equivalent(label)
        if n is not None and n.name_en:
            return n.name_en, "TAXONOMY"
        return tr.lookup(label)

    def path_cn(anchor: CategoryNode | None, extra: list[str]) -> str | None:
        base = anchor.breadcrumb_cn if anchor else (idx.root.name_cn if idx.root else None)
        return " > ".join([x for x in [base, *extra] if x]) if (base or extra) else None

    def path_en(anchor: CategoryNode | None, extra: list[str]) -> tuple[str | None, str]:
        src = "TAXONOMY"
        if anchor is not None:
            base, bsrc = node_en_path(ctx, anchor, tr)
            if base is None:
                return None, "MISSING"
            if bsrc == "AI":
                src = "AI"
        else:
            base = idx.root.name_en if idx.root else None
        parts = [base] if base else []
        for e in extra:
            t, s = en(e)
            if t is None:
                return None, "MISSING"
            if s == "AI":
                src = "AI"
            parts.append(t)
        return " > ".join(parts), src

    stats: dict[str, int] = defaultdict(int)
    ordered = sorted(drafts.values(), key=lambda g: g.gap_type)
    for i, g in enumerate(ordered):
        appr = ctx.approval("GAP", g.key)
        if appr and appr.decision == "CHANGE_PARENT":
            tid = ctx.resolve_target(appr)
            if tid:
                g.place_under = idx.nodes[tid]
                if g.gap_type in ("MISSING CHILD", "SRP-ONLY GAP", "MISPLACED EXISTING CATEGORY"):
                    g.parent_node, g.parent_name, g.parent_status = g.place_under, g.place_under.name_cn, "EXISTING"

        # suggested breadcrumbs (existing ancestors keep their existing labels)
        if g.gap_type in ("MISSING PARENT", "BOTH MISSING"):
            main_extra = [g.parent_name]
        elif g.gap_type in ("MISSING CHILD", "SRP-ONLY GAP"):
            main_extra = [g.main_name]
        elif g.gap_type == "MISPLACED EXISTING CATEGORY":
            main_extra = [g.main_name]
        else:
            main_extra = []
        anchor = g.place_under
        if g.gap_type == "DUPLICATE":
            sug_cn, (sug_en, en_src) = (g.main_node.breadcrumb_cn if g.main_node else None), node_en_path(ctx, g.main_node, tr) if g.main_node else (None, "MISSING")
        else:
            sug_cn = path_cn(anchor, main_extra)
            sug_en, en_src = path_en(anchor, main_extra)

        # SRP validation
        names = [g.main_name, g.parent_name if g.parent_status != "EXISTING" else None]
        names += [en(g.main_name)[0]]
        child_names = [c.name for c in g.children.values() if c.status != "DUPLICATE"]
        sup = sidx.support([n for n in names if n] + child_names) if g.gap_type != "DUPLICATE" else sidx.support([g.main_name])
        sup_ids = {s.id for s, _ in sup}
        for s in g.extra_srps:
            if s.id not in sup_ids:
                sup.append((s, "unmatched SRP (same concept)"))
                sup_ids.add(s.id)
        sup.sort(key=lambda x: -(x[0].search_volume or 0))
        vol = sum(s.search_volume or 0 for s, _ in sup)
        prod = max([s.product_count or 0 for s, _ in sup] + [0])
        ncomp = len(g.competitor_evidence)

        temp = _is_temporary(g.main_name or "") or _is_temporary(g.parent_name or "")
        b = {
            "competitor_category_exists": 20 if ncomp >= 1 else 0,
            "multiple_competitors": 20 if ncomp >= 2 else 0,
            "relevant_srps": 25 if sup else 0,
            "strong_search_volume": 20 if vol >= strong_volume else 0,
            "stable_product_type": 0 if temp else 20,
            "strong_inventory": 15 if max(prod, g.product_signal) >= strong_inventory else 0,
            "existing_equivalent": -100 if (g.gap_type in ("MISSING CHILD", "BOTH MISSING", "SRP-ONLY GAP") and existing_equivalent(g.main_name or "")) else 0,
            "weak_temporary_intent": -40 if temp else 0,
        }
        score = sum(b.values())
        if g.gap_type == "MISPLACED EXISTING CATEGORY":
            score = max(score, 60 + 10 * ncomp)
        if g.gap_type == "DUPLICATE":
            score = max(score, 50 + (20 if ncomp else 0))
        priority = "HIGH" if score >= 70 else ("MEDIUM" if score >= 40 else "LOW")
        competitor_only = ncomp >= 1 and not sup and g.gap_type in ("MISSING CHILD", "MISSING PARENT", "BOTH MISSING")
        if competitor_only:
            priority = "LOW"

        action = {
            "MISSING CHILD": "CREATE CHILD",
            "MISSING PARENT": "CREATE PARENT + RECONNECT EXISTING CHILDREN",
            "BOTH MISSING": "CREATE PARENT + CREATE CHILD",
            "MISPLACED EXISTING CATEGORY": "MOVE",
            "DUPLICATE": "CONSOLIDATE / KEEP EXISTING",
            "SRP-ONLY GAP": "CREATE CATEGORY (confirm parent)",
        }[g.gap_type]
        reason = g.reason
        if competitor_only:
            action = "MONITOR — competitor-only, not validated by SRP demand"
            reason += " Competitor-only gap: no supporting SRP demand, so it is not recommended yet."
        elif temp:
            action = "DO NOT CREATE — temporary / campaign intent"
        elif g.gap_type == "SRP-ONLY GAP" and g.parent_status == "MISSING":
            action = "CREATE CATEGORY (choose parent)"
        if g.gap_type in ("MISSING CHILD", "BOTH MISSING", "SRP-ONLY GAP") and priority == "LOW" and not competitor_only and not temp:
            action = "MONITOR — weak evidence"

        conf = min(95, 35 + 15 * min(ncomp, 3) + 8 * min(len(sup), 4) + (10 if vol >= strong_volume else 0))
        if g.gap_type in ("MISPLACED EXISTING CATEGORY", "DUPLICATE"):
            conf = max(conf, 75)

        links_added, links_removed, imp = [], [], "LOW"
        if g.gap_type == "MISSING CHILD":
            links_added = [f"'{g.parent_name}' gains a contextual child link to '{g.main_name}'",
                           f"SRPs for {g.main_name} inherit a more specific ancestor link"]
            imp = "MEDIUM"
        elif g.gap_type in ("MISSING PARENT", "BOTH MISSING"):
            links_added = [f"'{c.name}' gains ancestor link '{g.parent_name}'" for c in g.children.values()][:8]
            links_added.append(f"New hub '{g.parent_name}' links to its {len(g.children)} children (sibling context)")
            imp = "HIGH" if len(g.children) >= 2 else "MEDIUM"
        elif g.gap_type == "MISPLACED EXISTING CATEGORY" and g.main_node:
            old_parent = g.main_node.parent_name
            links_removed = [f"Irrelevant ancestor link '{old_parent}'"]
            links_added = [f"Relevant ancestor link '{g.parent_name}'"]
            imp = "HIGH"
        elif g.gap_type == "DUPLICATE":
            links_removed = [f"Duplicate page '{c.name}' ({c.node.breadcrumb_cn if c.node else ''})" for c in g.children.values()][:5]
            links_added = [f"All breadcrumb/internal links point to '{g.main_name}'"]
            imp = "MEDIUM"
        elif g.gap_type == "SRP-ONLY GAP":
            links_added = [f"New category page gives {len(sup)} SRP(s) a relevant parent breadcrumb link"]
            imp = "MEDIUM" if sup else "LOW"

        review = "NEEDS_REVIEW"
        if appr:
            review = "REJECTED" if appr.decision == "REJECT" else "APPROVED"

        pn_en, _ = en(g.parent_name)
        mn_en, mn_src = en(g.main_name)
        gap = TaxonomyGap(
            project_id=pid, gap_type=g.gap_type, gap_key=g.key,
            parent_name_cn=g.parent_name, parent_name_en=pn_en, parent_status=g.parent_status,
            parent_node_id=g.parent_node.id if g.parent_node else None,
            main_name_cn=g.main_name, main_name_en=mn_en, main_status=g.main_status,
            main_node_id=g.main_node.id if g.main_node else None,
            anchor_node_id=anchor.id if anchor else None,
            existing_url=g.main_node.url if g.main_node else None,
            current_breadcrumb_cn=g.current_breadcrumb,
            suggested_breadcrumb_cn=sug_cn, suggested_breadcrumb_en=sug_en,
            supporting_srps=[{"keyword": s.keyword, "search_volume": s.search_volume, "product_count": s.product_count, "match": why, "url": s.url} for s, why in sup[:50]],
            srp_count=len(sup), combined_search_volume=vol, product_count=max(prod, g.product_signal) or None,
            competitor_evidence={k: v for k, v in g.competitor_evidence.items()}, competitor_count=ncomp,
            score=score, score_breakdown=b, priority=priority, confidence=conf, reason=reason.strip(),
            recommended_action=action, links_added=links_added, links_removed=links_removed, linking_improvement=imp,
            en_source=en_src if sug_en else "MISSING", review_status=review,
        )
        db.add(gap)
        db.flush()
        parent_path_cn = sug_cn
        for c in g.children.values():
            if g.gap_type == "DUPLICATE":
                s_cn, s_en = (g.main_node.breadcrumb_cn if g.main_node else None), None
            else:
                s_cn = f"{parent_path_cn} > {c.name}" if parent_path_cn else c.name
                cen = en(c.name)[0]
                s_en = f"{sug_en} > {cen}" if sug_en and cen else None
            csup = sidx.support([c.name])
            db.add(GapChild(
                gap_id=gap.id, name_cn=c.name, name_en=en(c.name)[0], status=c.status,
                existing_node_id=c.node.id if c.node else None, existing_url=c.node.url if c.node else None,
                existing_breadcrumb=c.node.breadcrumb_cn if c.node else None,
                suggested_breadcrumb_cn=s_cn, suggested_breadcrumb_en=s_en,
                supporting_srps=[{"keyword": s.keyword, "search_volume": s.search_volume} for s, _ in csup[:20]],
                search_volume=sum(s.search_volume or 0 for s, _ in csup),
            ))
        stats[g.gap_type] += 1
        if progress and (i % 10 == 0 or i == len(ordered) - 1):
            progress(i + 1, len(ordered))
    db.flush()
    return {"gaps": len(drafts), "by_type": dict(stats)}
