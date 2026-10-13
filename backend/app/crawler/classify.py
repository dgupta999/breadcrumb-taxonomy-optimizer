"""Page-type classification for crawled competitor pages.

Only CATEGORY and SUBCATEGORY pages feed the competitor taxonomy.
"""
from __future__ import annotations

from ..core.lexicon import HOME_LABEL_HINTS, TEMPORARY_INTENT
from ..core.normalize import normalize
from .extract import PageData
from .urls import is_campaign_url, is_content_url, is_product_url, looks_like_category_url, query_kind


def strip_home(crumbs: list[dict]) -> list[dict]:
    out = list(crumbs)
    while out and any(h in normalize(out[0]["name"]) for h in HOME_LABEL_HINTS):
        out = out[1:]
    return out


def classify(url: str, pd: PageData, child_category_links: int) -> tuple[str, float, list[str]]:
    """Return (page_type, category_confidence 0..1, signals)."""
    signals: list[str] = []
    crumbs = strip_home(pd.breadcrumb)
    title = normalize(f"{pd.title or ''} {pd.h1 or ''}")

    if is_product_url(url) or pd.has_product_schema or pd.og_type == "product":
        return "PRODUCT", 0.0, ["product url/schema"]
    qk = query_kind(url)
    if qk == "SEARCH":
        return "SRP", 0.05, ["search parameters"]
    if qk == "FILTER":
        return "FILTER", 0.1, ["filter/sort parameters"]
    if is_content_url(url):
        return "CONTENT", 0.05, ["content url"]
    if is_campaign_url(url) or (any(w in title for w in TEMPORARY_INTENT) and not crumbs):
        return "CAMPAIGN", 0.1, ["campaign url/wording"]

    score = 0.0
    if crumbs:
        score += 0.35
        signals.append(f"breadcrumb ({len(crumbs)} levels)")
    if looks_like_category_url(url):
        score += 0.25
        signals.append("category url pattern")
    if child_category_links >= 3:
        score += 0.2
        signals.append(f"{child_category_links} child category links")
    if pd.product_link_count >= 8 or pd.item_list_count >= 8:
        score += 0.2
        signals.append(f"product grid ({max(pd.product_link_count, pd.item_list_count)} products)")
    if pd.h1:
        score += 0.05
    score = min(1.0, score)
    if score < 0.35:
        return "UNKNOWN", score, signals or ["weak category signals"]
    # CATEGORY = top / branch level; SUBCATEGORY = deeper or leaf with product grid
    depth = len(crumbs)
    if depth <= 1 or (child_category_links >= 3 and depth <= 2):
        return "CATEGORY", score, signals
    return "SUBCATEGORY", score, signals
