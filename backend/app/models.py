"""ORM models. Mirrors supabase/migrations/0001_init.sql."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _id() -> Mapped[int]:
    return mapped_column(Integer, primary_key=True, autoincrement=True)


def _project_fk() -> Mapped[int]:
    return mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = _id()
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_category: Mapped[str | None] = mapped_column(String(200), nullable=True)
    home_label_cn: Mapped[str | None] = mapped_column(String(100), nullable=True)
    home_label_en: Mapped[str | None] = mapped_column(String(100), nullable=True)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Upload(Base):
    """An uploaded CSV/XLSX awaiting column mapping."""
    __tablename__ = "uploads"
    id: Mapped[int] = _id()
    project_id: Mapped[int] = _project_fk()
    kind: Mapped[str] = mapped_column(String(30))  # TAXONOMY | SRP | SYNONYMS
    filename: Mapped[str] = mapped_column(String(300))
    stored_path: Mapped[str] = mapped_column(String(500))
    columns: Mapped[list] = mapped_column(JSON, default=list)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    mapping: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="UPLOADED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Category(Base):
    """Raw imported category row (source of truth for CURRENT state)."""
    __tablename__ = "categories"
    id: Mapped[int] = _id()
    project_id: Mapped[int] = _project_fk()
    external_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    name_cn: Mapped[str | None] = mapped_column(String(300), nullable=True)
    name_en: Mapped[str | None] = mapped_column(String(300), nullable=True)
    h1_cn: Mapped[str | None] = mapped_column(String(300), nullable=True)
    h1_en: Mapped[str | None] = mapped_column(String(300), nullable=True)
    breadcrumb_cn: Mapped[str | None] = mapped_column(Text, nullable=True)
    breadcrumb_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)
    parent_external_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    product_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CategoryNode(Base):
    """Node of the reconstructed current taxonomy tree."""
    __tablename__ = "category_nodes"
    id: Mapped[int] = _id()
    project_id: Mapped[int] = _project_fk()
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    name_cn: Mapped[str] = mapped_column(String(300))
    name_en: Mapped[str | None] = mapped_column(String(300), nullable=True)
    norm_key: Mapped[str] = mapped_column(String(300), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("category_nodes.id", ondelete="CASCADE"), nullable=True, index=True)
    parent_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    breadcrumb_cn: Mapped[str] = mapped_column(Text)
    breadcrumb_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    path_key: Mapped[str] = mapped_column(Text)
    children_count: Mapped[int] = mapped_column(Integer, default=0)
    descendant_count: Mapped[int] = mapped_column(Integer, default=0)
    product_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_root: Mapped[bool] = mapped_column(Boolean, default=False)
    is_inferred: Mapped[bool] = mapped_column(Boolean, default=False)  # ancestor present only in breadcrumbs


class SRP(Base):
    __tablename__ = "srps"
    id: Mapped[int] = _id()
    project_id: Mapped[int] = _project_fk()
    keyword: Mapped[str] = mapped_column(String(300))
    keyword_norm: Mapped[str] = mapped_column(String(300), index=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    h1: Mapped[str | None] = mapped_column(String(300), nullable=True)
    keyword_en: Mapped[str | None] = mapped_column(String(300), nullable=True)
    en_source: Mapped[str | None] = mapped_column(String(20), nullable=True)  # INPUT | RULE | AI | MISSING
    keyword_en_generated: Mapped[str | None] = mapped_column(String(300), nullable=True)
    search_volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    # --- mapping results ---
    core_product: Mapped[str | None] = mapped_column(String(200), nullable=True)
    modifiers: Mapped[list] = mapped_column(JSON, default=list)
    canonical_concept: Mapped[str | None] = mapped_column(String(200), nullable=True)
    matched_node_id: Mapped[int | None] = mapped_column(ForeignKey("category_nodes.id", ondelete="SET NULL"), nullable=True)
    match_method: Mapped[str | None] = mapped_column(String(30), nullable=True)  # HUMAN | RULE | LLM | NONE
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence_band: Mapped[str | None] = mapped_column(String(30), nullable=True)
    candidates: Mapped[list] = mapped_column(JSON, default=list)
    breadcrumb_cn: Mapped[str | None] = mapped_column(Text, nullable=True)
    breadcrumb_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    duplicate_intent: Mapped[str | None] = mapped_column(String(20), nullable=True)  # YES | POTENTIAL | NO
    duplicate_node_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    potential_gap: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    mapped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Synonym(Base):
    __tablename__ = "synonyms"
    id: Mapped[int] = _id()
    project_id: Mapped[int] = _project_fk()
    alias: Mapped[str] = mapped_column(String(200))
    alias_norm: Mapped[str] = mapped_column(String(200), index=True)
    canonical: Mapped[str] = mapped_column(String(200))
    preferred_node_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preferred_category_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="HUMAN")  # HUMAN | DEFAULT
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApprovedMapping(Base):
    """Human decisions that override future rule/AI decisions."""
    __tablename__ = "approved_mappings"
    id: Mapped[int] = _id()
    project_id: Mapped[int] = _project_fk()
    entity_type: Mapped[str] = mapped_column(String(40))  # SRP | AUDIT | GAP | COMPETITOR_CATEGORY
    match_key: Mapped[str] = mapped_column(String(400), index=True)
    target_node_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decision: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ManualOverride(Base):
    __tablename__ = "manual_overrides"
    id: Mapped[int] = _id()
    project_id: Mapped[int] = _project_fk()
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int] = mapped_column(Integer)
    field: Mapped[str] = mapped_column(String(80))
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Competitor(Base):
    __tablename__ = "competitors"
    id: Mapped[int] = _id()
    project_id: Mapped[int] = _project_fk()
    name: Mapped[str] = mapped_column(String(100))
    start_url: Mapped[str] = mapped_column(Text)
    target_category: Mapped[str | None] = mapped_column(String(200), nullable=True)
    max_urls: Mapped[int] = mapped_column(Integer, default=1000)
    max_depth: Mapped[int] = mapped_column(Integer, default=5)
    include_patterns: Mapped[list] = mapped_column(JSON, default=list)
    exclude_patterns: Mapped[list] = mapped_column(JSON, default=list)
    render_js: Mapped[bool] = mapped_column(Boolean, default=False)
    crawl_delay: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="NEW")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CompetitorSeedUrl(Base):
    __tablename__ = "competitor_seed_urls"
    id: Mapped[int] = _id()
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)


class CrawlJob(Base):
    __tablename__ = "crawl_jobs"
    id: Mapped[int] = _id()
    project_id: Mapped[int] = _project_fk()
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id", ondelete="CASCADE"), index=True)
    job_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="QUEUED")
    processed_urls: Mapped[int] = mapped_column(Integer, default=0)
    discovered_urls: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_robots: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CrawlPage(Base):
    __tablename__ = "crawl_pages"
    id: Mapped[int] = _id()
    project_id: Mapped[int] = _project_fk()
    crawl_job_id: Mapped[int] = mapped_column(ForeignKey("crawl_jobs.id", ondelete="CASCADE"), index=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    canonical: Mapped[str | None] = mapped_column(Text, nullable=True)
    indexability: Mapped[str | None] = mapped_column(String(60), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    h1: Mapped[str | None] = mapped_column(Text, nullable=True)
    breadcrumb: Mapped[list] = mapped_column(JSON, default=list)
    breadcrumb_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    parent_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    anchor_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    internal_links_count: Mapped[int] = mapped_column(Integer, default=0)
    child_category_links: Mapped[list] = mapped_column(JSON, default=list)
    product_link_count: Mapped[int] = mapped_column(Integer, default=0)
    page_type: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    category_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    category_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    crawled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CompetitorCategory(Base):
    __tablename__ = "competitor_categories"
    id: Mapped[int] = _id()
    project_id: Mapped[int] = _project_fk()
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id", ondelete="CASCADE"), index=True)
    page_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String(300))
    norm_key: Mapped[str] = mapped_column(String(300), index=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("competitor_categories.id", ondelete="CASCADE"), nullable=True)
    parent_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    breadcrumb: Mapped[str] = mapped_column(Text)
    path_key: Mapped[str] = mapped_column(Text)
    children_names: Mapped[list] = mapped_column(JSON, default=list)
    hierarchy_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_inferred: Mapped[bool] = mapped_column(Boolean, default=False)
    product_link_count: Mapped[int] = mapped_column(Integer, default=0)


class CompetitorMapping(Base):
    __tablename__ = "competitor_mappings"
    id: Mapped[int] = _id()
    project_id: Mapped[int] = _project_fk()
    competitor_id: Mapped[int] = mapped_column(Integer, index=True)
    competitor_category_id: Mapped[int] = mapped_column(ForeignKey("competitor_categories.id", ondelete="CASCADE"), index=True)
    matched_node_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_matched_node_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    match_type: Mapped[str] = mapped_column(String(40))
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    review_status: Mapped[str | None] = mapped_column(String(30), nullable=True)


class BreadcrumbAudit(Base):
    __tablename__ = "breadcrumb_audits"
    id: Mapped[int] = _id()
    project_id: Mapped[int] = _project_fk()
    node_id: Mapped[int] = mapped_column(ForeignKey("category_nodes.id", ondelete="CASCADE"), index=True)
    category_name: Mapped[str] = mapped_column(String(300))
    category_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_breadcrumb_cn: Mapped[str] = mapped_column(Text)
    current_breadcrumb_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_parent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    issues: Mapped[list] = mapped_column(JSON, default=list)
    action: Mapped[str] = mapped_column(String(40), index=True)
    recommended_parent_node_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recommended_parent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    recommended_parent_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    recommended_breadcrumb_cn: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_breadcrumb_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_score: Mapped[int] = mapped_column(Integer, default=0)
    recommended_score: Mapped[int] = mapped_column(Integer, default=0)
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    current_ancestors: Mapped[list] = mapped_column(JSON, default=list)
    recommended_ancestors: Mapped[list] = mapped_column(JSON, default=list)
    links_removed: Mapped[list] = mapped_column(JSON, default=list)
    links_added: Mapped[list] = mapped_column(JSON, default=list)
    linking_improvement: Mapped[str | None] = mapped_column(String(20), nullable=True)
    linking_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    review_status: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)


class TaxonomyGap(Base):
    __tablename__ = "taxonomy_gaps"
    id: Mapped[int] = _id()
    project_id: Mapped[int] = _project_fk()
    gap_type: Mapped[str] = mapped_column(String(40), index=True)
    gap_key: Mapped[str] = mapped_column(String(400))
    parent_name_cn: Mapped[str | None] = mapped_column(String(300), nullable=True)
    parent_name_en: Mapped[str | None] = mapped_column(String(300), nullable=True)
    parent_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    parent_node_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    main_name_cn: Mapped[str | None] = mapped_column(String(300), nullable=True)
    main_name_en: Mapped[str | None] = mapped_column(String(300), nullable=True)
    main_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    main_node_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    anchor_node_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # existing node new pages hang under
    existing_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_breadcrumb_cn: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_breadcrumb_cn: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_breadcrumb_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    supporting_srps: Mapped[list] = mapped_column(JSON, default=list)
    srp_count: Mapped[int] = mapped_column(Integer, default=0)
    combined_search_volume: Mapped[int] = mapped_column(Integer, default=0)
    product_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    competitor_evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    competitor_count: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[int] = mapped_column(Integer, default=0)
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    priority: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(String(80), nullable=True)
    links_added: Mapped[list] = mapped_column(JSON, default=list)
    links_removed: Mapped[list] = mapped_column(JSON, default=list)
    linking_improvement: Mapped[str | None] = mapped_column(String(20), nullable=True)
    en_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    review_status: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)


class GapChild(Base):
    __tablename__ = "gap_children"
    id: Mapped[int] = _id()
    gap_id: Mapped[int] = mapped_column(ForeignKey("taxonomy_gaps.id", ondelete="CASCADE"), index=True)
    name_cn: Mapped[str] = mapped_column(String(300))
    name_en: Mapped[str | None] = mapped_column(String(300), nullable=True)
    status: Mapped[str] = mapped_column(String(40))  # EXISTING | NEW | EXISTING BUT MISPLACED | SRP ONLY | DUPLICATE
    existing_node_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    existing_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    existing_breadcrumb: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_breadcrumb_cn: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_breadcrumb_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    supporting_srps: Mapped[list] = mapped_column(JSON, default=list)
    search_volume: Mapped[int] = mapped_column(Integer, default=0)


class ReviewAction(Base):
    __tablename__ = "review_actions"
    id: Mapped[int] = _id()
    project_id: Mapped[int] = _project_fk()
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    previous_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reviewer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Export(Base):
    __tablename__ = "exports"
    id: Mapped[int] = _id()
    project_id: Mapped[int] = _project_fk()
    export_key: Mapped[str] = mapped_column(String(80))
    format: Mapped[str] = mapped_column(String(10))
    filename: Mapped[str] = mapped_column(String(300))
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JobRun(Base):
    __tablename__ = "job_runs"
    id: Mapped[int] = _id()  # job_id
    project_id: Mapped[int] = _project_fk()
    job_type: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", index=True)
    progress: Mapped[float] = mapped_column(Float, default=0)
    total_items: Mapped[int] = mapped_column(Integer, default=0)
    processed_items: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Embedding(Base):
    """Cached text embeddings (float16, base64) so re-runs never re-embed the same text."""
    __tablename__ = "embeddings"
    id: Mapped[int] = _id()
    text_hash: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    text: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(60))
    dims: Mapped[int] = mapped_column(Integer)
    vector: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
