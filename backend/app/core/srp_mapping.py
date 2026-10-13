"""SRP → category mapping + SRP breadcrumb generation.

Order of operations (safeguard #4): select category first, inherit the
category's EXISTING breadcrumb, then append the SRP H1. The LLM may only pick
among the top candidates; the application builds the breadcrumb.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SRP, CategoryNode
from . import llm
from .context import EngineContext
from .matcher import band, candidate_payload
import re

from .lexicon import BRAND_CASE, MODIFIER_EN
from .normalize import has_cjk, norm_key

Progress = Callable[[int, int], None]


def node_en_path(ctx: EngineContext, node: CategoryNode, tr) -> tuple[str | None, str]:
    """English breadcrumb for an existing node: uploaded EN breadcrumb first,
    otherwise each label resolved via taxonomy/glossary/AI."""
    if node.breadcrumb_en:
        return node.breadcrumb_en, "INPUT"
    labels = [a.name_cn for a in ctx.index.ancestors(node, include_root=True)] + [node.name_cn]
    out, src = [], "RULE"
    for l in labels:
        en, s = tr.lookup(l)
        if not en:
            return None, "MISSING"
        if s == "AI":
            src = "AI"
        out.append(en)
    return " > ".join(out), src


def _srp_english(srp: SRP, ext, node: CategoryNode | None, tr) -> tuple[str | None, str]:
    if srp.keyword_en:
        return srp.keyword_en, "INPUT"
    if not has_cjk(srp.keyword):
        return srp.keyword, "INPUT"
    if node and node.name_en:
        mods = [m for m in ext.modifiers if ext.modifier_types.get(m) != "GENERIC"]
        en_mods = [_modifier_en(m, srp.h1 or srp.keyword) for m in mods]
        if all(en_mods):
            return (" ".join(en_mods + [node.name_en])).strip(), "RULE"
    en, src = tr.lookup(srp.h1 or srp.keyword)
    return (en, "AI") if en else (None, "MISSING")


def _modifier_en(mod: str, display: str) -> str | None:
    if mod in MODIFIER_EN:
        return MODIFIER_EN[mod]
    if re.fullmatch(r"\d+(?:\.\d+)?[吋寸]", mod):
        return mod[:-1] + '"'
    if has_cjk(mod):
        return None
    if mod in BRAND_CASE:
        return BRAND_CASE[mod]
    m = re.search(re.escape(mod), display or "", re.I)
    if m and m.group(0) != m.group(0).lower():
        return m.group(0)
    if re.fullmatch(r"\d+(?:\.\d+)?(gb|tb|mb|g|t)", mod):
        return re.sub(r"(gb|tb|mb|g|t)$", lambda x: {"g": "GB", "t": "TB"}.get(x.group(1), x.group(1).upper()), mod)
    if re.fullmatch(r"\d+吋", mod):
        return mod.replace("吋", '"')
    return mod.upper() if len(mod) <= 3 else mod.capitalize()


def _duplicate(ext, cand, node) -> tuple[str, str | None]:
    if cand is None:
        return "NO", None
    if any(s.startswith("exact normalized") for s in cand.signals):
        return "YES", "Do not maintain a separate indexable SEO SRP page — canonicalize / redirect to the existing category."
    if ext.alias_exact is not None and cand.exact:
        if ext.alias_exact.synonym_source == "HUMAN":
            return "YES", "Do not maintain a separate indexable SEO SRP page — the keyword is an approved synonym of the category."
        return "POTENTIAL", "Likely the same intent as the existing category (synonym). Review: consider canonical to the category."
    core_hit = any(s.startswith(("core product exact", "canonical concept")) for s in cand.signals)
    if core_hit and ext.only_generic_modifiers:
        return "POTENTIAL", "Keyword only adds generic modifiers to the category concept. Review: consider canonical to the category."
    return "NO", None


def map_srps(db: Session, ctx: EngineContext, progress: Progress | None = None, only_ids: list[int] | None = None) -> dict:
    q = select(SRP).where(SRP.project_id == ctx.project.id)
    if only_ids:
        q = q.where(SRP.id.in_(only_ids))
    srps = db.scalars(q).all()
    budget = llm.LLMBudget()
    tr = ctx.translator(budget)
    stats = {"total": len(srps), "auto": 0, "review": 0, "low": 0, "no_match": 0, "llm_calls": 0, "human": 0, "duplicates": 0}
    pending_en: list[tuple[SRP, object, CategoryNode | None]] = []

    for i, srp in enumerate(srps):
        key = norm_key(srp.keyword)
        approval = ctx.approval("SRP", key)
        approved_node = ctx.resolve_target(approval) if approval and approval.decision in ("APPROVE", "CHANGE_CATEGORY", "MARK_DUPLICATE") else None
        res = ctx.matcher.match(srp.keyword, extra_text=srp.keyword_en, approved_node_id=approved_node)
        ext = res.extraction
        top, conf, method = res.top, res.confidence, res.method
        reason_bits: list[str] = []
        rejected = approval is not None and approval.decision == "REJECT"
        rejected_id = ctx.resolve_target(approval) if rejected else None
        if rejected and top is not None and top.node.id == rejected_id:
            alt = next((c for c in res.candidates if c.node.id != rejected_id and not c.conflict and c.score >= 45), None)
            reason_bits.append(f"human rejected mapping to '{top.node.name_cn}'")
            top, conf, method = alt, (min(int(alt.score), 89) if alt else 0), ("RULE" if alt else "NONE")
            res.candidates = [c for c in res.candidates if c.node.id != rejected_id]

        # LLM fallback for ambiguous / medium-confidence decisions only.
        if method == "RULE" and conf < 90 and res.candidates or (method == "NONE" and res.candidates and res.candidates[0].score >= 25):
            pool = [c for c in res.candidates if not c.conflict][:5]
            pick = llm.choose_category(
                srp.keyword, ext.core_label, ext.modifiers,
                [{"category_id": c.node.id, "name": c.node.name_cn, "breadcrumb": c.node.breadcrumb_cn, "parent": c.node.parent_name} for c in pool],
                budget,
            )
            if pick is not None:
                stats["llm_calls"] += 1
                if pick["category_id"] is None:
                    if conf < 70:
                        top, method, conf = None, "NONE", 0
                    reason_bits.append(f"AI: NO_MATCH — {pick['reason']}")
                else:
                    chosen = next(c for c in pool if c.node.id == pick["category_id"])
                    if top is not None and chosen.node.id == top.node.id:
                        conf = max(conf, min(95, (conf + pick["confidence"]) // 2 + 10))
                        method = "RULE+LLM"
                    else:
                        top, conf, method = chosen, min(pick["confidence"], 85), "LLM"
                    reason_bits.append(f"AI: {pick['reason']}")

        if approval and approval.decision == "MARK_TAXONOMY_GAP":
            top, method, conf = None, "HUMAN", 100

        node = top.node if top else None
        srp.core_product = ext.core_label
        srp.modifiers = ext.modifiers
        srp.canonical_concept = ext.canonical_label
        srp.candidates = [candidate_payload(c) for c in res.candidates[:5]]
        srp.matched_node_id = node.id if node else None
        srp.match_method = method
        srp.score = round(top.score, 1) if top else (round(res.candidates[0].score, 1) if res.candidates else 0)
        srp.confidence = conf if node else 0
        srp.confidence_band = band(conf, node is not None)
        srp.potential_gap = node is None
        srp.mapped_at = datetime.now(timezone.utc)

        if node:
            srp.breadcrumb_cn = f"{node.breadcrumb_cn} > {srp.h1 or srp.keyword}"
            dup, action = _duplicate(ext, top, node)
            srp.duplicate_intent, srp.duplicate_node_id = dup, (node.id if dup != "NO" else None)
            if approval and approval.decision == "MARK_DUPLICATE":
                srp.duplicate_intent, srp.duplicate_node_id = "YES", node.id
                action = "Human marked as duplicate of the category — do not maintain a separate indexable SRP page."
            srp.recommended_action = action or "Keep SRP; use generated breadcrumb."
            reason_bits.insert(0, "; ".join(top.signals[:5]))
            pending_en.append((srp, ext, node))
            stats["duplicates"] += dup != "NO"
        else:
            srp.breadcrumb_cn = None
            srp.breadcrumb_en = None
            srp.duplicate_intent = "NO"
            srp.duplicate_node_id = None
            srp.recommended_action = "No valid existing category — potential taxonomy gap. Validate in Taxonomy Gaps."
            if res.candidates:
                reason_bits.insert(0, f"best candidate '{res.candidates[0].node.name_cn}' scored {res.candidates[0].score:.0f} (< threshold)")
            else:
                reason_bits.insert(0, "no candidate categories found")
        srp.reason = " | ".join(b for b in reason_bits if b)

        if approval and approval.decision != "REJECT":
            srp.review_status = "APPROVED"
        elif rejected:
            srp.review_status = "REJECTED" if node is None else ("NEEDS_REVIEW" if srp.confidence_band == "AUTO_APPROVED" else srp.confidence_band)
        else:
            srp.review_status = srp.confidence_band
        stats["human"] += method == "HUMAN"
        stats[{"AUTO_APPROVED": "auto", "NEEDS_REVIEW": "review", "LOW_CONFIDENCE": "low", "NO_MATCH": "no_match"}[srp.confidence_band]] += 1
        if progress and (i % 25 == 0 or i == len(srps) - 1):
            progress(i + 1, len(srps))

    # English: deterministic first, then one batched AI call for the rest.
    for srp, ext, node in pending_en:
        en, src = _srp_english(srp, ext, node, tr)
        if en is None:
            tr.want(srp.h1 or srp.keyword)
        path, _ = node_en_path(ctx, node, tr)
        if path is None:
            for a in ctx.index.ancestors(node, include_root=True) + [node]:
                tr.want(a.name_cn)
    tr.flush()
    for srp, ext, node in pending_en:
        en, src = _srp_english(srp, ext, node, tr)
        path, psrc = node_en_path(ctx, node, tr)
        srp.keyword_en_generated = en if not srp.keyword_en else None
        srp.en_source = "AI" if "AI" in (src, psrc) else src
        srp.breadcrumb_en = f"{path} > {en}" if path and en else None
    db.flush()
    return stats
