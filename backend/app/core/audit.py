"""Current breadcrumb audit, breadcrumb quality score and internal-linking impact.

Recommendations never modify the uploaded taxonomy; they are stored as
proposals in `breadcrumb_audits` for human review.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import SRP, BreadcrumbAudit, CategoryNode, CompetitorCategory, CompetitorMapping, Competitor
from . import llm
from .context import EngineContext
from .lexicon import GENERIC_LEVEL_LABELS, GROUP_LABEL_HINTS
from .matcher import branch_conflict
from .normalize import classify_modifier, common_suffix_len, has_cjk, name_parts, norm_key, normalize
from .relations import ACCESSORY, IS_A, SAME, SIBLING, SUPERTYPE, is_a, relation
from .srp_mapping import node_en_path
from .taxonomy import path_key

Progress = Callable[[int, int], None]
_GENERIC_KEYS = {norm_key(x) for x in GENERIC_LEVEL_LABELS}


def is_group_label(name: str) -> bool:
    n = normalize(name)
    return any(h in n for h in GROUP_LABEL_HINTS)


def is_generic_level(name: str) -> bool:
    return norm_key(name) in _GENERIC_KEYS


@dataclass
class Placement:
    """Competitor evidence: where a competitor places my category."""
    competitor: str
    competitor_breadcrumb: str
    parent_name: str | None
    parent_node_id: int | None


@dataclass
class AuditContext:
    ctx: EngineContext
    srp_by_node: dict[int, list[SRP]] = field(default_factory=dict)
    placements: dict[int, list[Placement]] = field(default_factory=dict)
    competitor_parent_names: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    has_competitors: bool = False


def relevance(actx: AuditContext, child: CategoryNode, parent: CategoryNode | None) -> tuple[float, str]:
    """How well `parent` semantically contains `child` (0..1)."""
    if parent is None or parent.is_root:
        return 1.0, "top level"
    ck, pk = child.norm_key, parent.norm_key
    vocab = actx.ctx.vocab
    if is_generic_level(parent.name_cn):
        return 0.2, f"'{parent.name_cn}' is a generic level"
    if ck == pk:
        return 0.0, "duplicate label"
    for pl in actx.placements.get(child.id, []):
        if pl.parent_node_id == parent.id or (pl.parent_name and norm_key(pl.parent_name) == pk):
            return 1.0, f"{pl.competitor} uses the same parent"
    rel = relation(ck, pk, vocab)
    if rel == IS_A:
        return 1.0, f"'{child.name_cn}' is a kind of '{parent.name_cn}'"
    if rel == SAME:
        return 0.2, "same concept as its parent"
    if rel == SUPERTYPE:
        return 0.1, f"parent '{parent.name_cn}' is narrower than '{child.name_cn}'"
    # compound parent: 網路/分享器 → 無線分享器 is a kind of 分享器
    for part in name_parts(parent.name_cn):
        if is_a(ck, part, vocab):
            return 0.95, f"'{child.name_cn}' is a kind of '{part}'"
    # accessory group for the same product: 筆電充電器 under 筆電配件
    if is_group_label(parent.name_cn):
        for L in range(min(len(ck), len(pk)) - 1, 1, -1):
            if ck[:L] == pk[:L] and (vocab.canonical(ck[:L]) in vocab.terms or ck[:L] in vocab.terms):
                return 0.9, f"accessory group for '{ck[:L]}'"
    # accessory section of the product: 手機 > 手機配件, 筆電 > 筆電周邊
    if rel == ACCESSORY and ck.startswith(pk) and is_group_label(child.name_cn):
        return 0.9, f"'{child.name_cn}' is the accessory section of '{parent.name_cn}'"
    if rel == ACCESSORY:
        return 0.3, f"'{child.name_cn}' is an accessory of '{parent.name_cn}', not a kind of it"
    if rel == SIBLING:
        return 0.3, f"'{child.name_cn}' and '{parent.name_cn}' are sibling types, not parent and child"
    if child.name_en and parent.name_en:
        ce, pe = normalize(child.name_en), normalize(parent.name_en)
        if ce.endswith(" " + pe) or ce.endswith(" " + pe.rstrip("s")):
            return 1.0, "English name is a kind of the parent"
        if ce.split()[-1].rstrip("s") == pe.split()[-1].rstrip("s"):
            return 0.6, "same English product head"
    if not has_cjk(child.name_cn):
        # Latin brand / model line names (PS5, Nintendo Switch) can't be judged lexically.
        return 0.6, "brand / model line name"
    if is_group_label(parent.name_cn):
        # grouping node; check the child isn't obviously from a different sense
        if branch_conflict(normalize(child.name_cn), parent):
            return 0.2, "branch conflict"
        return 0.7, "grouping parent"
    return 0.25, f"'{child.name_cn}' is not a type of '{parent.name_cn}'"


def _depth_quality(levels: int) -> int:
    if 2 <= levels <= 5:
        return 10
    if levels == 1:
        return 6
    if levels == 6:
        return 7
    return 4


def quality_score(actx: AuditContext, node: CategoryNode, ancestors: list, parent_rel: float, *,
                  more_specific_exists: bool, in_missing_parent_group: bool, dup_levels: int) -> tuple[int, dict]:
    """ancestors: list of (label, relevance 0..1) excluding root."""
    srps = actx.srp_by_node.get(node.id, [])
    vol = sum(s.search_volume or 0 for s in srps)
    srp_pts = 5 if not srps else (10 if len(srps) >= 3 or vol >= 1000 else 7)
    pls = actx.placements.get(node.id, [])
    if not actx.has_competitors:
        comp_pts = 5
    elif not pls:
        comp_pts = 5
    else:
        parent_label = ancestors[-1][0] if ancestors else None
        agree = any(pl.parent_name and parent_label and norm_key(pl.parent_name) == norm_key(parent_label) for pl in pls)
        comp_pts = 10 if agree else 3
    link_rel = (sum(1 for _, r in ancestors if r >= 0.5) / len(ancestors)) if ancestors else 1.0
    b = {
        "parent_semantic_relevance": round(25 * parent_rel),
        "hierarchy_specificity": 5 if more_specific_exists else 15,
        "duplicate_level_penalty": max(0, 10 - 10 * dup_levels),
        "missing_parent_penalty": 3 if in_missing_parent_group else 10,
        "depth_quality": _depth_quality(len(ancestors) + 1),
        "srp_support": srp_pts,
        "competitor_support": comp_pts,
        "internal_linking_relevance": round(10 * link_rel),
    }
    return int(sum(b.values())), b


def _load_audit_context(db: Session, ctx: EngineContext) -> AuditContext:
    actx = AuditContext(ctx)
    srps = db.scalars(select(SRP).where(SRP.project_id == ctx.project.id, SRP.matched_node_id.is_not(None))).all()
    by_node: dict[int, list[SRP]] = defaultdict(list)
    for s in srps:
        by_node[s.matched_node_id].append(s)
    actx.srp_by_node = by_node

    comps = {c.id: c.name for c in db.scalars(select(Competitor).where(Competitor.project_id == ctx.project.id))}
    maps = db.scalars(select(CompetitorMapping).where(CompetitorMapping.project_id == ctx.project.id)).all()
    if maps:
        actx.has_competitors = True
        cats = {c.id: c for c in db.scalars(select(CompetitorCategory).where(CompetitorCategory.project_id == ctx.project.id))}
        for m in maps:
            if m.matched_node_id is None or m.match_type not in ("EXACT MATCH", "SEMANTIC MATCH", "EXISTING BUT MISPLACED"):
                continue
            cc = cats.get(m.competitor_category_id)
            if not cc:
                continue
            actx.placements.setdefault(m.matched_node_id, []).append(
                Placement(comps.get(m.competitor_id, "?"), cc.breadcrumb, cc.parent_name, m.parent_matched_node_id)
            )
    return actx


def _missing_parent_groups(actx: AuditContext) -> dict[int, dict]:
    """Siblings sharing a leading product concept with no common parent page,
    e.g. 筆電充電器 + 筆電電池 + 筆電包 directly under 電腦/平板周邊 → suggest 筆電配件."""
    idx, vocab = actx.ctx.index, actx.ctx.vocab
    out: dict[int, dict] = {}
    for parent_id, kids in idx.children.items():
        groups: dict[str, list[CategoryNode]] = defaultdict(list)
        for k in kids:
            key = k.norm_key
            for L in range(len(key) - 1, 1, -1):
                pre = key[:L]
                # the shared prefix must be a product concept that is itself a category
                # (筆電 → 筆記型電腦), not a generic word (網路 in 網路攝影機)
                canon = vocab.canonical(pre)
                if idx.by_key.get(pre) or (canon != pre and idx.by_key.get(canon)):
                    groups[pre].append(k)
                    break
        parent = idx.nodes[parent_id]
        for pre, members in groups.items():
            if len(members) < 2 or pre == parent.norm_key or parent.norm_key.startswith(pre):
                continue
            label = members[0].name_cn[: len(pre)] if members[0].norm_key.startswith(pre) else pre
            new_name = f"{label}配件"
            existing = idx.by_key.get(norm_key(new_name), [])
            for m in members:
                out[m.id] = {
                    "concept": label,
                    "suggested_parent": new_name,
                    "existing_parent": existing[0] if existing else None,
                    "under": parent,
                    "siblings": [x.name_cn for x in members],
                }
    return out


def _more_specific_parent(actx: AuditContext, node: CategoryNode) -> CategoryNode | None:
    """An existing category that `node` is a sub-type of (無線滑鼠 → 滑鼠)."""
    idx, vocab = actx.ctx.index, actx.ctx.vocab
    key = node.norm_key
    best = None
    for L in range(len(key) - 1, 1, -1):
        suffix = key[-L:]
        for cand in idx.by_key.get(suffix, []):
            if cand.id == node.id or cand.is_root or cand.id == node.parent_id:
                continue
            if idx.is_ancestor(node, cand) or idx.is_ancestor(cand, node):
                continue
            prefix = key[: len(key) - L]
            # 筆電充電器: prefix 筆電 is itself a product concept → "accessory for X", not a sub-type of 充電器
            if prefix and any(t.kind in ("CATEGORY", "SYNONYM", "CANONICAL") for t in vocab.terms.get(prefix, [])):
                continue
            if branch_conflict(normalize(node.name_cn + " " + (node.breadcrumb_cn or "")), cand):
                continue
            parent = idx.nodes.get(node.parent_id)
            if parent and parent.depth > cand.depth and not idx.is_ancestor(cand, parent):
                continue
            best = cand
            break
        if best:
            break
    return best


def _srp_child_demand(actx: AuditContext, node: CategoryNode) -> list[dict]:
    idx = actx.ctx.index
    existing = {k.norm_key for k in idx.children.get(node.id, [])}
    groups: dict[str, list[SRP]] = defaultdict(list)
    for s in actx.srp_by_node.get(node.id, []):
        context = "".join(a.norm_key for a in idx.ancestors(node)) + node.norm_key
        attrs = [m for m in (s.modifiers or []) if m and norm_key(m) not in context]
        attrs = [m for m in attrs if classify_modifier(m) == "ATTRIBUTE"]
        if s.core_product and attrs:
            kw, a, core = normalize(s.keyword), attrs[0], s.core_product
            if kw.find(a) <= kw.find(normalize(core)):
                name = f"{a}{core}"
            else:
                name = f"{core}{a}" if has_cjk(core) else f"{core} {a}"
            groups[name].append(s)
    out = []
    for name, srps in groups.items():
        vol = sum(s.search_volume or 0 for s in srps)
        if norm_key(name) in existing or norm_key(name) in idx.by_key:
            continue
        if len(srps) >= 2 or vol >= 500:
            out.append({"name": name, "srps": [s.keyword for s in srps], "volume": vol})
    return sorted(out, key=lambda x: -x["volume"])


def _labels(idx, node: CategoryNode) -> list[CategoryNode]:
    return idx.ancestors(node)  # excludes root


def run_audit(db: Session, ctx: EngineContext, progress: Progress | None = None) -> dict:
    idx = ctx.index
    actx = _load_audit_context(db, ctx)
    budget = llm.LLMBudget()
    tr = ctx.translator(budget)
    db.execute(delete(BreadcrumbAudit).where(BreadcrumbAudit.project_id == ctx.project.id))
    db.flush()

    missing_groups = _missing_parent_groups(actx)
    dup_names: dict[str, list[CategoryNode]] = defaultdict(list)
    for n in idx.real_nodes():
        if not n.is_inferred:
            dup_names[ctx.vocab.canonical(n.norm_key) or n.norm_key].append(n)

    nodes = sorted([n for n in idx.real_nodes() if not n.is_inferred], key=lambda n: n.breadcrumb_cn)
    root = idx.root
    rows: list[BreadcrumbAudit] = []
    stats = defaultdict(int)

    for i, node in enumerate(nodes):
        anc = _labels(idx, node)
        parent = idx.nodes.get(node.parent_id) if node.parent_id else None
        issues: list[str] = []
        evidence: dict = {}
        action = "KEEP"
        conf = 90
        new_parent: CategoryNode | None = parent
        new_parent_name: str | None = parent.name_cn if parent else None
        new_parent_status = "EXISTING"
        new_anc_labels: list[str] = [a.name_cn for a in anc]
        reason = ""

        rel, rel_why = relevance(actx, node, parent)
        anc_rel = [(a.name_cn, rel if a is parent else relevance(actx, node, a)[0]) for a in anc]

        # 3) duplicate labels
        keys = [a.norm_key for a in anc] + [node.norm_key]
        dup_levels = sum(1 for a, b in zip(keys, keys[1:]) if a == b)
        nonconsec = len(keys) - len(set(keys)) - dup_levels
        # 4) generic levels
        generic = [a for a in anc if is_generic_level(a.name_cn)]
        # specificity / missing parent / duplicates elsewhere
        specific = _more_specific_parent(actx, node)
        mp = missing_groups.get(node.id)
        dups = [d for d in dup_names.get(ctx.vocab.canonical(node.norm_key) or node.norm_key, []) if d.id != node.id]
        child_demand = _srp_child_demand(actx, node)

        if dup_levels or nonconsec:
            issues.append(f"Hierarchy contains duplicate label(s): {' > '.join(a.name_cn for a in anc + [node])}")
            # collapse consecutive duplicates
            dedup: list[str] = []
            for l in [a.name_cn for a in anc] + [node.name_cn]:
                if not dedup or norm_key(dedup[-1]) != norm_key(l):
                    dedup.append(l)
            new_anc_labels = dedup[:-1] if norm_key(dedup[-1]) == node.norm_key else dedup
            action, conf = "FLATTEN", 95
            twin_labels = ([root.name_cn] if root else []) + new_anc_labels + [node.name_cn]
            twin = idx.by_path.get(path_key(twin_labels))
            twin = twin if twin is not None and twin.id != node.id else None
            if node.norm_key == (parent.norm_key if parent else None):
                new_parent = idx.nodes.get(parent.parent_id) if parent and parent.parent_id else None
                new_parent_name = new_parent.name_cn if new_parent else None
                reason = f"'{node.name_cn}' repeats its parent level; remove the duplicate level."
                if twin:
                    reason += f" The flattened path already exists ({twin.url or twin.breadcrumb_cn}) — consolidate into it."
                    evidence["consolidate_into"] = twin.url or twin.breadcrumb_cn
            else:
                reason = "Remove duplicate level from the breadcrumb."
        if generic:
            issues.append("Unnecessary generic level(s): " + ", ".join(a.name_cn for a in generic))
            new_anc_labels = [l for l in new_anc_labels if not is_generic_level(l)]
            if parent in generic:
                new_parent = idx.nodes.get(parent.parent_id) if parent.parent_id else None
                new_parent_name = new_parent.name_cn if new_parent else None
            if action == "KEEP":
                action, conf, reason = "FLATTEN", 85, "Remove generic level(s) that add no taxonomy meaning."

        if action == "KEEP" and specific is not None:
            issues.append(f"More specific existing parent available: '{specific.name_cn}'")
            new_parent, new_parent_name = specific, specific.name_cn
            new_anc_labels = [a.name_cn for a in _labels(idx, specific)] + [specific.name_cn]
            action, conf = "MOVE", 85
            reason = f"'{node.name_cn}' is a type of '{specific.name_cn}', which already exists at {specific.breadcrumb_cn}."

        if action == "KEEP" and rel < 0.5:
            issues.append(f"Parent not semantically relevant: {rel_why}")
            # competitor evidence
            votes: dict[int, list[str]] = defaultdict(list)
            new_by_comp: dict[str, list[str]] = defaultdict(list)
            for pl in actx.placements.get(node.id, []):
                if pl.parent_node_id and pl.parent_node_id != (parent.id if parent else None):
                    votes[pl.parent_node_id].append(pl.competitor)
                elif pl.parent_name and not pl.parent_node_id:
                    new_by_comp[pl.parent_name].append(pl.competitor)
            if votes:
                pid, who = max(votes.items(), key=lambda kv: len(set(kv[1])))
                tgt = idx.nodes[pid]
                new_parent, new_parent_name = tgt, tgt.name_cn
                new_anc_labels = [a.name_cn for a in _labels(idx, tgt)] + [tgt.name_cn]
                action, conf = "MOVE", min(95, 70 + 10 * len(set(who)))
                reason = f"'{node.name_cn}' is not a type of '{parent.name_cn if parent else ''}'. {', '.join(sorted(set(who)))} place it under '{tgt.name_cn}', which exists in your taxonomy."
                evidence["competitors"] = sorted(set(who))
            elif new_by_comp:
                pname, who = max(new_by_comp.items(), key=lambda kv: len(kv[1]))
                grand = idx.nodes.get(parent.parent_id) if parent and parent.parent_id else root
                new_parent, new_parent_name, new_parent_status = None, pname, "NEW"
                new_anc_labels = ([a.name_cn for a in _labels(idx, grand)] + [grand.name_cn] if grand and not grand.is_root else []) + [pname]
                action, conf = "MOVE + CREATE PARENT", min(85, 60 + 10 * len(set(who)))
                reason = f"'{node.name_cn}' is not a type of '{parent.name_cn}'. {', '.join(sorted(set(who)))} use parent '{pname}', which does not exist yet."
                evidence["competitors"] = sorted(set(who))
            else:
                cands = [n for n in idx.real_nodes() if is_group_label(n.name_cn) and not n.is_inferred and n.id not in {node.id, parent.id if parent else -1}
                         and not idx.is_ancestor(node, n)]
                cands.sort(key=lambda n: (abs(n.depth - (parent.depth if parent else 1)), n.breadcrumb_cn))
                judged = llm.judge_parent(node.name_cn, node.breadcrumb_cn, parent.name_cn if parent else "",
                                          [{"id": c.id, "name": c.name_cn, "breadcrumb": c.breadcrumb_cn} for c in cands[:8]], budget)
                if judged and not judged["parent_is_valid"] and judged["best_parent_id"]:
                    tgt = idx.nodes[judged["best_parent_id"]]
                    new_parent, new_parent_name = tgt, tgt.name_cn
                    new_anc_labels = [a.name_cn for a in _labels(idx, tgt)] + [tgt.name_cn]
                    action, conf = "MOVE", min(85, judged["confidence"])
                    reason = f"AI: {judged['reason']}"
                    evidence["ai"] = True
                elif judged and judged["parent_is_valid"]:
                    action, conf, reason = "KEEP", 70, f"AI judged parent acceptable: {judged['reason']}"
                else:
                    action, conf = "REVIEW", 50
                    reason = f"'{node.name_cn}' does not look like a type of '{parent.name_cn if parent else ''}' and no better existing parent was found automatically. Re-run after competitor comparison or choose a parent manually."

        if action == "KEEP" and mp is not None:
            sp = mp["existing_parent"]
            issues.append(f"Missing logical parent: siblings {', '.join(mp['siblings'])} share concept '{mp['concept']}' without a common parent")
            under = mp["under"]
            base = ([a.name_cn for a in _labels(idx, under)] + [under.name_cn]) if not under.is_root else []
            if sp is not None:
                new_parent, new_parent_name = sp, sp.name_cn
                new_anc_labels = [a.name_cn for a in _labels(idx, sp)] + [sp.name_cn]
                action, conf = "MOVE", 80
                reason = f"Group with siblings under existing '{sp.name_cn}'."
            else:
                new_parent, new_parent_name, new_parent_status = None, mp["suggested_parent"], "NEW"
                new_anc_labels = base + [mp["suggested_parent"]]
                action, conf = "MOVE + CREATE PARENT", 75
                reason = f"Create parent '{mp['suggested_parent']}' under '{under.name_cn}' and reconnect {', '.join(mp['siblings'])}."
            comp_has = [pl.competitor for pl in actx.placements.get(node.id, []) if pl.parent_name and norm_key(pl.parent_name) == norm_key(new_parent_name or "")]
            if comp_has:
                conf = min(95, conf + 10)
                evidence["competitors"] = sorted(set(comp_has))

        if action == "KEEP" and dups:
            keep = max([node] + dups, key=lambda d: ((d.product_count or 0), -d.depth))
            if keep.id != node.id:
                issues.append(f"Duplicate category: same concept exists at {keep.breadcrumb_cn}")
                action, conf = "CONSOLIDATE", 80
                reason = f"Consolidate into existing '{keep.name_cn}' ({keep.url or keep.breadcrumb_cn}); do not keep two pages for one concept."
                evidence["consolidate_into"] = keep.url or keep.breadcrumb_cn
                new_parent = None
                new_anc_labels = [a.name_cn for a in _labels(idx, keep)]
                new_parent_name = keep.parent_name
            else:
                issues.append("Duplicate concept exists elsewhere: " + "; ".join(d.breadcrumb_cn for d in dups))

        if action == "KEEP" and child_demand:
            top = child_demand[0]
            issues.append(f"SRP demand for missing child '{top['name']}' ({len(top['srps'])} SRPs, volume {top['volume']})")
            action, conf = "CREATE CHILD", 70
            reason = f"Create child '{top['name']}' under '{node.name_cn}' — supported by SRPs: {', '.join(top['srps'][:5])}."
            evidence["child_demand"] = child_demand[:5]

        # Human decisions override
        appr = ctx.approval("AUDIT", node.path_key)
        review_status = "NEEDS_REVIEW" if action != "KEEP" else "AUTO_APPROVED"
        if appr:
            if appr.decision == "KEEP_EXISTING":
                action, reason, conf = "KEEP", "Human approved keeping the existing breadcrumb.", 100
                new_parent, new_parent_name, new_anc_labels, new_parent_status = parent, parent.name_cn if parent else None, [a.name_cn for a in anc], "EXISTING"
                review_status = "APPROVED"
            elif appr.decision in ("CHANGE_PARENT", "MOVE_EXISTING"):
                tid = ctx.resolve_target(appr)
                if tid:
                    tgt = idx.nodes[tid]
                    new_parent, new_parent_name, new_parent_status = tgt, tgt.name_cn, "EXISTING"
                    new_anc_labels = [a.name_cn for a in _labels(idx, tgt)] + [tgt.name_cn]
                    action, conf, reason = "MOVE", 100, f"Human set parent to '{tgt.name_cn}'."
                review_status = "APPROVED"
            elif appr.decision == "CREATE_PARENT":
                pname = (appr.payload or {}).get("parent_name")
                if pname:
                    new_parent, new_parent_name, new_parent_status = None, pname, "NEW"
                    new_anc_labels = new_anc_labels[:-1] + [pname] if new_anc_labels else [pname]
                    action, conf, reason = "MOVE + CREATE PARENT", 100, f"Human requested new parent '{pname}'."
                review_status = "APPROVED"
            elif appr.decision == "APPROVE":
                pl = appr.payload or {}
                if pl.get("consolidate_into"):
                    action, conf, reason = "CONSOLIDATE", 100, f"Human marked as duplicate; consolidate into {pl['consolidate_into']}."
                    evidence["consolidate_into"] = pl["consolidate_into"]
                elif pl.get("child_name"):
                    action, conf, reason = "CREATE CHILD", 100, f"Human requested child '{pl['child_name']}'."
                    evidence["child_demand"] = [{"name": pl["child_name"], "srps": [], "volume": 0}]
                review_status = "APPROVED"
            elif appr.decision == "REJECT":
                review_status = "REJECTED"

        # Recommended breadcrumb (CN/EN). Existing ancestors keep their existing labels.
        home = [root.name_cn] if root else []
        rec_cn = " > ".join(home + new_anc_labels + [node.name_cn])
        if appr and appr.decision == "APPROVE" and (appr.payload or {}).get("recommended_breadcrumb") not in (None, rec_cn):
            review_status = "NEEDS_REVIEW"
            reason += " (Recommendation changed since it was approved — please re-review.)"
        cur_en, _ = node_en_path(ctx, node, tr)
        rows.append(BreadcrumbAudit(
            project_id=ctx.project.id, node_id=node.id, category_name=node.name_cn, category_url=node.url,
            current_breadcrumb_cn=node.breadcrumb_cn, current_breadcrumb_en=cur_en,
            current_parent=parent.name_cn if parent and not parent.is_root else None,
            issues=issues, action=action,
            recommended_parent_node_id=new_parent.id if new_parent else None,
            recommended_parent=new_parent_name, recommended_parent_status=new_parent_status if action != "KEEP" else "EXISTING",
            recommended_breadcrumb_cn=rec_cn, reason=reason or "Breadcrumb is consistent.", confidence=conf,
            evidence=evidence, review_status=review_status,
        ))
        a = rows[-1]
        a._calc = {  # transient, used below
            "anc_rel": anc_rel, "rel": rel, "specific": specific is not None, "mp": mp is not None, "dup": dup_levels + max(0, nonconsec),
            "new_anc_labels": new_anc_labels, "new_parent": new_parent, "node": node,
        }
        stats[action] += 1
        if progress and (i % 25 == 0 or i == len(nodes) - 1):
            progress(i + 1, len(nodes))

    # English for recommended breadcrumbs (deterministic first, one AI batch)
    for a in rows:
        for l in a._calc["new_anc_labels"]:
            tr.want(l)
        tr.want(a.category_name)
    tr.flush()
    for a in rows:
        c = a._calc
        node: CategoryNode = c["node"]
        labels = ([idx.root.name_cn] if idx.root else []) + c["new_anc_labels"] + [node.name_cn]
        en_parts = []
        for l in labels:
            hit = next((x.name_en for x in idx.by_key.get(norm_key(l), []) if x.name_en), None)
            if hit is None and idx.root and norm_key(l) == idx.root.norm_key:
                hit = idx.root.name_en
            en_parts.append(hit or tr.lookup(l)[0])
        a.recommended_breadcrumb_en = " > ".join(en_parts) if all(en_parts) else None

        cur_score, cur_b = quality_score(actx, node, c["anc_rel"], c["rel"], more_specific_exists=c["specific"],
                                         in_missing_parent_group=c["mp"], dup_levels=c["dup"])
        if a.action == "KEEP":
            rec_score, rec_b = cur_score, cur_b
            new_rel = c["anc_rel"]
        else:
            new_rel = []
            for l in c["new_anc_labels"]:
                n2 = next(iter(idx.by_key.get(norm_key(l), [])), None)
                if n2 is not None:
                    r = relevance(actx, node, n2)[0]
                    r = max(r, 0.6) if is_group_label(l) and not is_generic_level(l) else r
                else:
                    r = 0.9  # new, purpose-built parent
                new_rel.append((l, r))
            p_rel = new_rel[-1][1] if new_rel else 1.0
            if a.action in ("MOVE", "MOVE + CREATE PARENT") and a.recommended_parent_status == "NEW":
                p_rel = 0.9
            rec_score, rec_b = quality_score(actx, node, new_rel, p_rel, more_specific_exists=False,
                                             in_missing_parent_group=False, dup_levels=0)
            if a.action == "CREATE CHILD":
                rec_score, rec_b = cur_score, cur_b
        a.current_score, a.recommended_score = cur_score, max(rec_score, cur_score if a.action in ("KEEP", "REVIEW", "CREATE CHILD") else rec_score)
        a.score_breakdown = {"current": cur_b, "recommended": rec_b}

        cur_anc = [l for l, _ in c["anc_rel"]]
        rec_anc = [l for l, _ in new_rel] if a.action != "KEEP" else cur_anc
        a.current_ancestors, a.recommended_ancestors = cur_anc, rec_anc
        cur_set, rec_set = {norm_key(x) for x in cur_anc}, {norm_key(x) for x in rec_anc}
        removed = [{"label": l, "relevance": round(r, 2), "irrelevant": r < 0.5} for l, r in c["anc_rel"] if norm_key(l) not in rec_set]
        added = [{"label": l, "relevance": round(r, 2), "relevant": r >= 0.5, "new_page": not idx.by_key.get(norm_key(l))} for l, r in new_rel if norm_key(l) not in cur_set]
        if a.action in ("KEEP",):
            removed, added = [], []
        a.links_removed, a.links_added = removed, added
        rem_irrel = [x["label"] for x in removed if x["irrelevant"]]
        add_rel = [x["label"] for x in added if x["relevant"]]
        if rem_irrel and add_rel:
            imp = "HIGH"
        elif rem_irrel or add_rel:
            imp = "MEDIUM"
        elif removed or added or a.action in ("FLATTEN", "CONSOLIDATE"):
            imp = "LOW"
        else:
            imp = "NONE"
        a.linking_improvement = imp
        parts = []
        if rem_irrel:
            parts.append("Removed irrelevant ancestor link(s): " + ", ".join(rem_irrel))
        other_removed = [x["label"] for x in removed if not x["irrelevant"]]
        if other_removed:
            parts.append("Removed redundant/duplicate level(s): " + ", ".join(other_removed))
        if add_rel:
            parts.append("Added relevant ancestor link(s): " + ", ".join(add_rel))
        if a.action == "FLATTEN" and not removed:
            parts.append("Removes the self-referencing duplicate breadcrumb link")
        if a.action == "CREATE CHILD":
            parts.append("New child page adds a contextual link from this category to a high-demand subtype")
        a.linking_explanation = "; ".join(parts) or "No change to breadcrumb links."
        del a._calc
        db.add(a)
    db.flush()
    return {"audited": len(rows), "by_action": dict(stats), "competitor_evidence_used": actx.has_competitors}
