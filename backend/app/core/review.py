"""Human review actions. Every decision is logged (review_actions) and, where it
should influence future runs, stored as an approved rule (approved_mappings)
that overrides rule/AI decisions on the next run."""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import (
    SRP, ApprovedMapping, BreadcrumbAudit, CategoryNode, CompetitorCategory, CompetitorMapping, ManualOverride,
    ReviewAction, TaxonomyGap,
)
from .normalize import norm_key

ACTIONS = {
    "srp": ["APPROVE", "REJECT", "CHANGE_CATEGORY", "MARK_DUPLICATE", "MARK_TAXONOMY_GAP", "CREATE_CHILD", "KEEP_EXISTING"],
    "audit": ["APPROVE", "REJECT", "CHANGE_PARENT", "CREATE_PARENT", "CREATE_CHILD", "MOVE_EXISTING", "KEEP_EXISTING", "MARK_DUPLICATE"],
    "gap": ["APPROVE", "REJECT", "CHANGE_PARENT", "MARK_DUPLICATE", "CREATE_PARENT", "CREATE_CHILD", "MOVE_EXISTING", "KEEP_EXISTING"],
    "competitor_mapping": ["APPROVE", "REJECT", "CHANGE_CATEGORY", "MARK_TAXONOMY_GAP", "MARK_DUPLICATE"],
}


class ReviewError(ValueError):
    pass


def _rule(db: Session, pid: int, etype: str, key: str, decision: str, node: CategoryNode | None, reviewer: str | None, payload: dict | None = None) -> None:
    db.execute(delete(ApprovedMapping).where(ApprovedMapping.project_id == pid, ApprovedMapping.entity_type == etype, ApprovedMapping.match_key == key))
    p = dict(payload or {})
    if node is not None:
        p["target_path_key"] = node.path_key
        p["target_name"] = node.name_cn
        p["target_breadcrumb"] = node.breadcrumb_cn
    db.add(ApprovedMapping(project_id=pid, entity_type=etype, match_key=key, target_node_id=node.id if node else None,
                           decision=decision, payload=p, approved_by=reviewer))


def _override(db, pid, etype, eid, field, old, new, who):
    db.add(ManualOverride(project_id=pid, entity_type=etype, entity_id=eid, field=field,
                          old_value=None if old is None else str(old), new_value=None if new is None else str(new), created_by=who))


def _node(db: Session, pid: int, node_id) -> CategoryNode:
    n = db.get(CategoryNode, int(node_id)) if node_id is not None else None
    if n is None or n.project_id != pid:
        raise ReviewError("category node not found")
    return n


def apply_review(db: Session, pid: int, etype: str, eid: int, action: str, payload: dict, reviewer: str | None) -> dict:
    if etype not in ACTIONS or action not in ACTIONS[etype]:
        raise ReviewError(f"action {action} not allowed for {etype}")
    who = reviewer or "reviewer"
    note = payload.get("note")
    if etype == "srp":
        obj = db.get(SRP, eid)
        prev = obj.review_status if obj else None
        if obj is None or obj.project_id != pid:
            raise ReviewError("SRP not found")
        key = norm_key(obj.keyword)
        cur = db.get(CategoryNode, obj.matched_node_id) if obj.matched_node_id else None
        if action in ("APPROVE", "KEEP_EXISTING"):
            if cur is None:
                raise ReviewError("No category to approve — use Change Category or Mark Taxonomy Gap")
            _rule(db, pid, "SRP", key, "APPROVE", cur, who)
            obj.review_status = "APPROVED"
        elif action == "REJECT":
            _rule(db, pid, "SRP", key, "REJECT", cur, who)
            obj.review_status = "REJECTED"
        elif action == "CHANGE_CATEGORY":
            n = _node(db, pid, payload.get("node_id"))
            _override(db, pid, "srp", eid, "matched_node_id", cur.name_cn if cur else None, n.name_cn, who)
            obj.matched_node_id = n.id
            obj.breadcrumb_cn = f"{n.breadcrumb_cn} > {obj.h1 or obj.keyword}"
            en = obj.keyword_en or obj.keyword_en_generated
            obj.breadcrumb_en = f"{n.breadcrumb_en} > {en}" if n.breadcrumb_en and en else None
            obj.match_method, obj.confidence, obj.confidence_band, obj.potential_gap = "HUMAN", 100, "AUTO_APPROVED", False
            obj.reason = f"Human set category to '{n.name_cn}'" + (f" — {note}" if note else "")
            _rule(db, pid, "SRP", key, "CHANGE_CATEGORY", n, who)
            obj.review_status = "APPROVED"
        elif action == "MARK_DUPLICATE":
            target = _node(db, pid, payload["node_id"]) if payload.get("node_id") else cur
            if target is None:
                raise ReviewError("Choose the category this SRP duplicates")
            obj.duplicate_intent, obj.duplicate_node_id, obj.matched_node_id = "YES", target.id, target.id
            obj.recommended_action = "Human marked as duplicate of the category — do not maintain a separate indexable SRP page."
            _rule(db, pid, "SRP", key, "MARK_DUPLICATE", target, who)
            obj.review_status = "APPROVED"
        elif action == "MARK_TAXONOMY_GAP":
            _override(db, pid, "srp", eid, "matched_node_id", cur.name_cn if cur else None, None, who)
            obj.matched_node_id, obj.potential_gap, obj.breadcrumb_cn, obj.breadcrumb_en = None, True, None, None
            obj.confidence_band = "NO_MATCH"
            obj.recommended_action = "Human marked as taxonomy gap — validate in Taxonomy Gaps."
            _rule(db, pid, "SRP", key, "MARK_TAXONOMY_GAP", None, who)
            obj.review_status = "APPROVED"
        elif action == "CREATE_CHILD":
            parent = _node(db, pid, payload["node_id"]) if payload.get("node_id") else cur
            if parent is None:
                raise ReviewError("Choose the parent category for the new child")
            name = (payload.get("child_name") or obj.h1 or obj.keyword).strip()
            gap = TaxonomyGap(project_id=pid, gap_type="MISSING CHILD", gap_key=f"MANUAL_CHILD:{parent.path_key}:{norm_key(name)}",
                              parent_name_cn=parent.name_cn, parent_name_en=parent.name_en, parent_status="EXISTING", parent_node_id=parent.id,
                              anchor_node_id=parent.id, main_name_cn=name, main_status="NEW",
                              suggested_breadcrumb_cn=f"{parent.breadcrumb_cn} > {name}",
                              suggested_breadcrumb_en=f"{parent.breadcrumb_en} > {obj.keyword_en or obj.keyword_en_generated}" if parent.breadcrumb_en and (obj.keyword_en or obj.keyword_en_generated) else None,
                              supporting_srps=[{"keyword": obj.keyword, "search_volume": obj.search_volume, "match": "reviewer"}],
                              srp_count=1, combined_search_volume=obj.search_volume or 0, priority="MEDIUM", confidence=100, score=0,
                              reason=f"Created by reviewer from SRP '{obj.keyword}'", recommended_action="CREATE CHILD",
                              links_added=[f"'{parent.name_cn}' gains a child link to '{name}'"], linking_improvement="MEDIUM",
                              review_status="APPROVED")
            db.add(gap)
            db.flush()
            _rule(db, pid, "GAP", gap.gap_key, "APPROVE", parent, who, {"manual_gap": True, "name": name})
            obj.review_status = "APPROVED"
        new = obj.review_status
    elif etype == "audit":
        obj = db.get(BreadcrumbAudit, eid)
        if obj is None or obj.project_id != pid:
            raise ReviewError("audit row not found")
        prev = obj.review_status
        node = db.get(CategoryNode, obj.node_id)
        key = node.path_key
        if action == "APPROVE":
            _rule(db, pid, "AUDIT", key, "APPROVE", db.get(CategoryNode, obj.recommended_parent_node_id) if obj.recommended_parent_node_id else None, who,
                  {"recommended_breadcrumb": obj.recommended_breadcrumb_cn, "action": obj.action})
            obj.review_status = "APPROVED"
        elif action == "REJECT":
            _rule(db, pid, "AUDIT", key, "REJECT", None, who)
            obj.review_status = "REJECTED"
        elif action == "KEEP_EXISTING":
            _rule(db, pid, "AUDIT", key, "KEEP_EXISTING", None, who)
            _override(db, pid, "audit", eid, "action", obj.action, "KEEP", who)
            obj.action, obj.recommended_breadcrumb_cn, obj.recommended_breadcrumb_en = "KEEP", obj.current_breadcrumb_cn, obj.current_breadcrumb_en
            obj.recommended_parent, obj.recommended_parent_node_id, obj.recommended_parent_status = obj.current_parent, node.parent_id, "EXISTING"
            obj.links_added, obj.links_removed, obj.linking_improvement = [], [], "NONE"
            obj.reason = "Human approved keeping the existing breadcrumb."
            obj.review_status = "APPROVED"
        elif action in ("CHANGE_PARENT", "MOVE_EXISTING"):
            n = _node(db, pid, payload.get("node_id"))
            if n.id == node.id:
                raise ReviewError("A category cannot be its own parent")
            _override(db, pid, "audit", eid, "recommended_parent", obj.recommended_parent, n.name_cn, who)
            obj.action, obj.recommended_parent, obj.recommended_parent_node_id, obj.recommended_parent_status = "MOVE", n.name_cn, n.id, "EXISTING"
            obj.recommended_breadcrumb_cn = f"{n.breadcrumb_cn} > {node.name_cn}"
            obj.recommended_breadcrumb_en = f"{n.breadcrumb_en} > {node.name_en}" if n.breadcrumb_en and node.name_en else None
            obj.reason = f"Human moved '{node.name_cn}' under '{n.name_cn}'." + (f" {note}" if note else "")
            _rule(db, pid, "AUDIT", key, "CHANGE_PARENT", n, who)
            obj.review_status = "APPROVED"
        elif action == "CREATE_PARENT":
            name = (payload.get("parent_name") or "").strip()
            if not name:
                raise ReviewError("parent_name is required")
            under = db.get(CategoryNode, payload["node_id"]) if payload.get("node_id") else db.get(CategoryNode, node.parent_id)
            base = under.breadcrumb_cn if under else ""
            obj.action, obj.recommended_parent, obj.recommended_parent_node_id, obj.recommended_parent_status = "MOVE + CREATE PARENT", name, None, "NEW"
            obj.recommended_breadcrumb_cn = " > ".join(x for x in [base, name, node.name_cn] if x)
            obj.recommended_breadcrumb_en = None
            obj.recommended_ancestors = ([a for a in base.split(" > ")[1:]] if base else []) + [name]
            obj.reason = f"Human requested new parent '{name}'." + (f" {note}" if note else "")
            _rule(db, pid, "AUDIT", key, "CREATE_PARENT", None, who, {"parent_name": name})
            obj.review_status = "APPROVED"
        elif action == "CREATE_CHILD":
            name = (payload.get("child_name") or "").strip()
            if not name:
                raise ReviewError("child_name is required")
            obj.action = "CREATE CHILD"
            obj.evidence = {**(obj.evidence or {}), "child_demand": [{"name": name, "srps": [], "volume": 0}]}
            obj.reason = f"Human requested child '{name}'."
            _rule(db, pid, "AUDIT", key, "APPROVE", None, who, {"child_name": name})
            obj.review_status = "APPROVED"
        elif action == "MARK_DUPLICATE":
            n = _node(db, pid, payload.get("node_id"))
            obj.action, obj.evidence = "CONSOLIDATE", {**(obj.evidence or {}), "consolidate_into": n.url or n.breadcrumb_cn}
            obj.reason = f"Human marked as duplicate of '{n.breadcrumb_cn}'."
            _rule(db, pid, "AUDIT", key, "APPROVE", n, who, {"consolidate_into": n.url or n.breadcrumb_cn})
            obj.review_status = "APPROVED"
        new = obj.review_status
    elif etype == "gap":
        obj = db.get(TaxonomyGap, eid)
        if obj is None or obj.project_id != pid:
            raise ReviewError("gap not found")
        prev = obj.review_status
        if action in ("APPROVE",):
            _rule(db, pid, "GAP", obj.gap_key, "APPROVE", None, who)
            obj.review_status = "APPROVED"
        elif action in ("REJECT", "KEEP_EXISTING"):
            _rule(db, pid, "GAP", obj.gap_key, "REJECT", None, who)
            obj.review_status = "REJECTED"
        elif action in ("CHANGE_PARENT", "MOVE_EXISTING"):
            n = _node(db, pid, payload.get("node_id"))
            _override(db, pid, "gap", eid, "parent", obj.parent_name_cn, n.name_cn, who)
            obj.anchor_node_id = n.id
            if obj.gap_type in ("MISSING PARENT", "BOTH MISSING"):
                obj.suggested_breadcrumb_cn = f"{n.breadcrumb_cn} > {obj.parent_name_cn}"
                obj.suggested_breadcrumb_en = f"{n.breadcrumb_en} > {obj.parent_name_en}" if n.breadcrumb_en and obj.parent_name_en else None
            else:
                obj.parent_name_cn, obj.parent_name_en, obj.parent_status, obj.parent_node_id = n.name_cn, n.name_en, "EXISTING", n.id
                obj.suggested_breadcrumb_cn = f"{n.breadcrumb_cn} > {obj.main_name_cn}"
                obj.suggested_breadcrumb_en = f"{n.breadcrumb_en} > {obj.main_name_en}" if n.breadcrumb_en and obj.main_name_en else None
            if action == "MOVE_EXISTING":
                obj.recommended_action = "MOVE"
            _rule(db, pid, "GAP", obj.gap_key, "CHANGE_PARENT", n, who)
            obj.review_status = "APPROVED"
        elif action == "MARK_DUPLICATE":
            n = _node(db, pid, payload.get("node_id"))
            obj.recommended_action = "CONSOLIDATE / KEEP EXISTING"
            obj.reason = f"Human marked as duplicate of existing '{n.breadcrumb_cn}'. Do not create a new page."
            obj.existing_url = n.url
            _rule(db, pid, "GAP", obj.gap_key, "REJECT", n, who, {"duplicate_of": n.breadcrumb_cn})
            obj.review_status = "REJECTED"
        elif action == "CREATE_PARENT":
            name = (payload.get("parent_name") or "").strip() or obj.parent_name_cn
            obj.parent_name_cn, obj.parent_status, obj.recommended_action = name, "NEW", "CREATE PARENT + RECONNECT EXISTING CHILDREN"
            _rule(db, pid, "GAP", obj.gap_key, "APPROVE", None, who, {"parent_name": name})
            obj.review_status = "APPROVED"
        elif action == "CREATE_CHILD":
            obj.recommended_action = "CREATE CHILD"
            _rule(db, pid, "GAP", obj.gap_key, "APPROVE", None, who)
            obj.review_status = "APPROVED"
        new = obj.review_status
    else:  # competitor_mapping
        obj = db.get(CompetitorMapping, eid)
        if obj is None or obj.project_id != pid:
            raise ReviewError("mapping not found")
        prev = obj.review_status
        cc = db.get(CompetitorCategory, obj.competitor_category_id)
        key = cc.norm_key
        cur = db.get(CategoryNode, obj.matched_node_id) if obj.matched_node_id else None
        if action == "APPROVE":
            _rule(db, pid, "COMPETITOR_CATEGORY", key, "APPROVE", cur, who)
            obj.review_status = "APPROVED"
        elif action == "REJECT":
            _rule(db, pid, "COMPETITOR_CATEGORY", key, "REJECT", cur, who)
            obj.review_status = "REJECTED"
        elif action in ("CHANGE_CATEGORY", "MARK_DUPLICATE"):
            n = _node(db, pid, payload.get("node_id"))
            obj.matched_node_id, obj.match_type, obj.method, obj.confidence = n.id, "SEMANTIC MATCH", "HUMAN", 100
            obj.reason = f"Human mapped to '{n.name_cn}'."
            _rule(db, pid, "COMPETITOR_CATEGORY", key, "CHANGE_CATEGORY", n, who)
            obj.review_status = "APPROVED"
        elif action == "MARK_TAXONOMY_GAP":
            obj.matched_node_id, obj.match_type, obj.method = None, "MISSING FROM MY TAXONOMY", "HUMAN"
            obj.reason = "Human marked as missing from my taxonomy."
            _rule(db, pid, "COMPETITOR_CATEGORY", key, "MARK_TAXONOMY_GAP", None, who)
            obj.review_status = "APPROVED"
        new = obj.review_status

    db.add(ReviewAction(project_id=pid, entity_type=etype, entity_id=eid, action=action, payload=payload,
                        previous_status=prev, new_status=new, reviewer=who, note=note))
    db.flush()
    return {"entity_type": etype, "id": eid, "action": action, "review_status": new}
