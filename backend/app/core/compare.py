"""Map competitor categories onto the current taxonomy.

Classification:
  EXACT MATCH | SEMANTIC MATCH | COMPETITOR MORE SPECIFIC | COMPETITOR MORE GENERAL
  MISSING FROM MY TAXONOMY | EXISTING BUT MISPLACED | AMBIGUOUS

Matching uses name + breadcrumb/parent context + child overlap + synonyms; the
branch-conflict guard prevents e.g. "poe switch" → "Nintendo Switch".
"""
from __future__ import annotations

from collections import defaultdict
from typing import Callable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import Competitor, CompetitorCategory, CompetitorMapping
from . import llm
from .audit import AuditContext, relevance
from .context import EngineContext
from .matcher import candidate_payload
from .normalize import norm_key
from .relations import is_a

Progress = Callable[[int, int], None]
MATCHED_TYPES = ("EXACT MATCH", "SEMANTIC MATCH", "EXISTING BUT MISPLACED")


def compare_taxonomy(db: Session, ctx: EngineContext, progress: Progress | None = None) -> dict:
    pid = ctx.project.id
    db.execute(delete(CompetitorMapping).where(CompetitorMapping.project_id == pid))
    db.flush()
    comps = {c.id: c for c in db.scalars(select(Competitor).where(Competitor.project_id == pid))}
    cats = db.scalars(select(CompetitorCategory).where(CompetitorCategory.project_id == pid)).all()
    cats = sorted(cats, key=lambda c: (c.competitor_id, c.depth))
    by_id = {c.id: c for c in cats}
    children: dict[int, list[CompetitorCategory]] = defaultdict(list)
    for c in cats:
        if c.parent_id:
            children[c.parent_id].append(c)
    idx = ctx.index
    actx = AuditContext(ctx)
    budget = llm.LLMBudget()
    mapping_of: dict[int, CompetitorMapping] = {}
    stats: dict[str, int] = defaultdict(int)

    for i, cc in enumerate(cats):
        parent_map = mapping_of.get(cc.parent_id) if cc.parent_id else None
        parent_node_id = parent_map.matched_node_id if parent_map and parent_map.match_type in MATCHED_TYPES else None
        ctx_parents = {parent_node_id} if parent_node_id else set()
        if parent_node_id:
            ctx_parents |= {a.id for a in idx.ancestors(idx.nodes[parent_node_id])}
        child_keys = {k.norm_key for k in children.get(cc.id, [])}
        appr = ctx.approval("COMPETITOR_CATEGORY", cc.norm_key)
        approved_node = ctx.resolve_target(appr) if appr and appr.decision in ("APPROVE", "CHANGE_CATEGORY") else None
        res = ctx.matcher.match(cc.name, approved_node_id=approved_node, context_parent_ids=ctx_parents, context_child_keys=child_keys)
        top, conf, ext = res.top, res.confidence, res.extraction
        method = res.method
        reason = ""
        evidence: dict = {"competitor_breadcrumb": cc.breadcrumb, "competitor_url": cc.url, "candidates": [candidate_payload(c) for c in res.candidates[:3]]}

        if appr and appr.decision == "MARK_TAXONOMY_GAP":
            top, conf, method = None, 100, "HUMAN"

        if top and method == "RULE" and (res.ambiguous or 45 <= conf < 70):
            pool = [c for c in res.candidates if not c.conflict][:5]
            pick = llm.choose_category(cc.name, ext.core_label, ext.modifiers,
                                       [{"category_id": c.node.id, "name": c.node.name_cn, "breadcrumb": c.node.breadcrumb_cn, "parent": c.node.parent_name} for c in pool], budget)
            if pick is not None:
                if pick["category_id"] is None:
                    top, conf, method = None, pick["confidence"], "LLM"
                    reason = f"AI: no equivalent category — {pick['reason']}"
                else:
                    top = next(c for c in pool if c.node.id == pick["category_id"])
                    conf, method = max(conf, min(90, pick["confidence"])), "LLM"
                    reason = f"AI: {pick['reason']}"

        match_type: str
        node = top.node if top else None
        if node is None:
            mapped_kids = [mapping_of[k.id] for k in children.get(cc.id, []) if k.id in mapping_of and mapping_of[k.id].match_type in MATCHED_TYPES]
            if len(mapped_kids) >= 2 or (mapped_kids and not children.get(cc.id, [])[1:]):
                match_type = "COMPETITOR MORE GENERAL"
                reason = reason or f"No equivalent page; its children map to existing categories ({', '.join(idx.nodes[m.matched_node_id].name_cn for m in mapped_kids[:4])})."
            elif res.candidates and 35 <= res.candidates[0].score < 45 and not res.candidates[0].conflict:
                match_type = "AMBIGUOUS"
                reason = reason or f"Weak candidate '{res.candidates[0].node.name_cn}' ({res.candidates[0].score:.0f}); needs review."
            else:
                match_type = "MISSING FROM MY TAXONOMY"
                reason = reason or "No equivalent category in current taxonomy."
                if any(c.conflict for c in res.candidates):
                    reason += " (lexically similar categories rejected as wrong branch: " + ", ".join(c.node.name_cn for c in res.candidates if c.conflict)[:120] + ")"
        else:
            nk = node.norm_key
            exact_name = cc.norm_key == nk or (node.name_en and cc.norm_key == norm_key(node.name_en))
            attrs = ext.attribute_modifiers
            core_is_node = ext.core_key in (nk, norm_key(node.name_en or "")) or ctx.vocab.canonical(ext.core_key) == ctx.vocab.canonical(nk)
            group_eq = any(sig.startswith(("equivalent group category", "short form of group")) for sig in top.signals)
            if res.ambiguous and method == "RULE" and conf < 70:
                match_type = "AMBIGUOUS"
            elif exact_name:
                match_type = "EXACT MATCH"
            elif group_eq:
                match_type = "SEMANTIC MATCH"
            elif core_is_node and attrs:
                match_type = "COMPETITOR MORE SPECIFIC"
            elif cc.norm_key != nk and is_a(nk, cc.norm_key, ctx.vocab):
                match_type = "COMPETITOR MORE GENERAL"
            else:
                match_type = "SEMANTIC MATCH"
            if match_type in ("EXACT MATCH", "SEMANTIC MATCH") and parent_node_id and parent_node_id != node.id:
                pnode = idx.nodes[parent_node_id]
                cur_parent = idx.nodes.get(node.parent_id) if node.parent_id else None
                if not idx.is_ancestor(pnode, node) and not idx.is_ancestor(node, pnode):
                    cur_rel = relevance(actx, node, cur_parent)[0]
                    new_rel = relevance(actx, node, pnode)[0]
                    if cur_rel < 0.5 and new_rel >= 0.5:
                        match_type = "EXISTING BUT MISPLACED"
                        evidence["current_parent"] = cur_parent.name_cn if cur_parent else None
                        evidence["suggested_parent"] = pnode.name_cn
                        reason = f"Exists at {node.breadcrumb_cn}; competitor places it under '{pnode.name_cn}', which is more relevant than '{cur_parent.name_cn if cur_parent else ''}'."
            if not reason:
                reason = "; ".join(top.signals[:4])

        m = CompetitorMapping(
            project_id=pid, competitor_id=cc.competitor_id, competitor_category_id=cc.id,
            matched_node_id=node.id if node else None, parent_matched_node_id=parent_node_id,
            match_type=match_type, score=round(top.score, 1) if top else (round(res.candidates[0].score, 1) if res.candidates else 0),
            confidence=conf if node else (conf or (90 if match_type == "MISSING FROM MY TAXONOMY" and not res.candidates else 70)),
            method=method, reason=reason, evidence=evidence,
            review_status="APPROVED" if appr and appr.decision != "REJECT" else ("REJECTED" if appr else ("AUTO_APPROVED" if (conf >= 90 and node) else "NEEDS_REVIEW")),
        )
        db.add(m)
        mapping_of[cc.id] = m
        stats[match_type] += 1
        if progress and (i % 25 == 0 or i == len(cats) - 1):
            progress(i + 1, len(cats))
    db.flush()
    return {"competitor_categories": len(cats), "by_type": dict(stats), "competitors": [c.name for c in comps.values()]}
