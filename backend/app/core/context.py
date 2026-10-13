"""Shared loaders for engine runs."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ApprovedMapping, Project, Synonym
from .concepts import Vocabulary
from .lexicon import DEFAULT_SYNONYMS
from .matcher import Matcher
from .normalize import norm_key
from .taxonomy import TaxonomyIndex
from .translate import Translator


@dataclass
class EngineContext:
    project: Project
    index: TaxonomyIndex
    vocab: Vocabulary
    matcher: Matcher
    approved: dict[tuple[str, str], ApprovedMapping]

    def approval(self, entity_type: str, key: str) -> ApprovedMapping | None:
        return self.approved.get((entity_type, key))

    def resolve_target(self, approval: ApprovedMapping | None) -> int | None:
        """Node ids change when the taxonomy is re-imported; approvals store the
        target's path key so they survive rebuilds."""
        if approval is None:
            return None
        pk = (approval.payload or {}).get("target_path_key")
        if pk and pk in self.index.by_path:
            return self.index.by_path[pk].id
        if approval.target_node_id in self.index.nodes:
            return approval.target_node_id
        return None

    def translator(self, budget=None) -> Translator:
        known = {}
        for n in self.index.nodes.values():
            if n.name_en:
                known[n.name_cn] = n.name_en
        return Translator(known, budget)


def ensure_default_synonyms(db: Session, project_id: int) -> int:
    existing = {s.alias_norm for s in db.scalars(select(Synonym).where(Synonym.project_id == project_id))}
    added = 0
    for alias, canonical in DEFAULT_SYNONYMS:
        k = norm_key(alias)
        if k in existing:
            continue
        db.add(Synonym(project_id=project_id, alias=alias, alias_norm=k, canonical=canonical, source="DEFAULT", approved_by="system default"))
        existing.add(k)
        added += 1
    db.flush()
    return added


def load_context(db: Session, project: Project) -> EngineContext:
    index = TaxonomyIndex.load(db, project.id)
    syns = db.scalars(select(Synonym).where(Synonym.project_id == project.id)).all()
    vocab = Vocabulary(list(index.nodes.values()), list(syns))
    approved = {(a.entity_type, a.match_key): a for a in db.scalars(select(ApprovedMapping).where(ApprovedMapping.project_id == project.id))}
    return EngineContext(project, index, vocab, Matcher(index, vocab), approved)
