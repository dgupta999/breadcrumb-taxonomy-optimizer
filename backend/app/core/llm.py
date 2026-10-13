"""LLM fallback — used ONLY for ambiguous semantic decisions and missing translations.

The LLM never builds breadcrumbs, never invents categories (its answer is
validated against the candidate list) and never overrides human approvals.
"""
from __future__ import annotations

import json
import logging
import threading

from ..config import settings

log = logging.getLogger(__name__)

_client = None
_lock = threading.Lock()

CHOOSE_SYSTEM = (
    "You are an ecommerce taxonomy specialist for a Traditional Chinese (Taiwan) marketplace. "
    "You choose between EXISTING categories; you never invent one."
)

CHOOSE_PROMPT = """Choose the category that best represents the core ecommerce product type.

Prefer the most specific valid existing category.
Use parent and breadcrumb context.
Do not invent an existing category.
If no category is suitable, return NO_MATCH (category_id = "NO_MATCH").

Return:
category_id
confidence (0-100)
reason

Input:
{payload}"""

PARENT_PROMPT = """You are auditing an ecommerce category breadcrumb.

Category: {name}
Current breadcrumb: {breadcrumb}

Is the current parent "{parent}" a semantically valid parent (i.e. is "{name}" a kind of / belongs under "{parent}")?
If not, choose the best parent from the candidate list below. Never invent a parent that is not in the list; use "NONE" if none fits.

Candidates:
{candidates}

Return parent_is_valid, best_parent_id, confidence (0-100), reason."""

TRANSLATE_PROMPT = """Translate these Traditional Chinese ecommerce category / search labels into concise, natural US-English ecommerce category names (Title Case, plural nouns for product types, keep brand names and specs as-is).

Return one entry per input with the same id.

{payload}"""


class LLMBudget:
    """Per-job call cap so a large run cannot run away with spend."""

    def __init__(self, max_calls: int | None = None):
        self.max_calls = settings.llm_max_calls_per_job if max_calls is None else max_calls
        self.calls = 0

    def take(self) -> bool:
        if self.calls >= self.max_calls:
            return False
        self.calls += 1
        return True


def available() -> bool:
    return settings.llm_available


def _get_client():
    global _client
    with _lock:
        if _client is None:
            import anthropic

            _client = anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=3)
    return _client


def _call_json(system: str, prompt: str, schema: dict, max_tokens: int = 2000) -> dict | None:
    import anthropic

    try:
        resp = _get_client().beta.messages.create(
            model=settings.llm_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": settings.llm_effort, "format": {"type": "json_schema", "schema": schema}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.RateLimitError as e:
        log.warning("LLM rate limited: %s", e)
        return None
    except anthropic.APIStatusError as e:
        log.warning("LLM API error %s: %s", e.status_code, e.message)
        return None
    except anthropic.APIConnectionError as e:
        log.warning("LLM connection error: %s", e)
        return None
    if resp.stop_reason == "refusal":
        log.warning("LLM refused request")
        return None
    text = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), None)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.warning("LLM returned invalid JSON")
        return None


def choose_category(keyword: str, core: str | None, modifiers: list[str], candidates: list[dict], budget: LLMBudget | None = None) -> dict | None:
    """candidates: [{category_id, name, breadcrumb, parent}] (max 5).
    Returns {category_id:int|None, confidence:int, reason:str} or None if unavailable."""
    if not available() or not candidates or (budget and not budget.take()):
        return None
    payload = {
        "keyword": keyword,
        "core_product_term": core,
        "modifiers": modifiers,
        "candidates": [
            {"category_id": str(c["category_id"]), "name": c["name"], "breadcrumb": c["breadcrumb"], "parent": c.get("parent")}
            for c in candidates[:5]
        ],
    }
    schema = {
        "type": "object",
        "properties": {
            "category_id": {"type": "string"},
            "confidence": {"type": "integer"},
            "reason": {"type": "string"},
        },
        "required": ["category_id", "confidence", "reason"],
        "additionalProperties": False,
    }
    data = _call_json(CHOOSE_SYSTEM, CHOOSE_PROMPT.format(payload=json.dumps(payload, ensure_ascii=False, indent=1)), schema, 1500)
    if not data:
        return None
    valid_ids = {str(c["category_id"]) for c in candidates[:5]}
    cid = str(data.get("category_id", "")).strip()
    conf = max(0, min(100, int(data.get("confidence") or 0)))
    if cid not in valid_ids:  # NO_MATCH or a hallucinated id
        return {"category_id": None, "confidence": conf, "reason": data.get("reason", "")}
    return {"category_id": int(cid), "confidence": conf, "reason": data.get("reason", "")}


def judge_parent(name: str, breadcrumb: str, parent: str, candidates: list[dict], budget: LLMBudget | None = None) -> dict | None:
    """candidates: [{id, name, breadcrumb}]. Returns {parent_is_valid, best_parent_id, confidence, reason}."""
    if not available() or (budget and not budget.take()):
        return None
    cand_txt = "\n".join(f'- id={c["id"]}: {c["breadcrumb"]}' for c in candidates[:8]) or "(none)"
    schema = {
        "type": "object",
        "properties": {
            "parent_is_valid": {"type": "boolean"},
            "best_parent_id": {"type": "string"},
            "confidence": {"type": "integer"},
            "reason": {"type": "string"},
        },
        "required": ["parent_is_valid", "best_parent_id", "confidence", "reason"],
        "additionalProperties": False,
    }
    data = _call_json(CHOOSE_SYSTEM, PARENT_PROMPT.format(name=name, breadcrumb=breadcrumb, parent=parent, candidates=cand_txt), schema, 1500)
    if not data:
        return None
    valid = {str(c["id"]) for c in candidates[:8]}
    bid = str(data.get("best_parent_id", "")).strip()
    return {
        "parent_is_valid": bool(data.get("parent_is_valid")),
        "best_parent_id": int(bid) if bid in valid else None,
        "confidence": max(0, min(100, int(data.get("confidence") or 0))),
        "reason": data.get("reason", ""),
    }


def translate_batch(labels: list[str], budget: LLMBudget | None = None) -> dict[str, str]:
    """Translate CN labels to EN. Returns {label: english}."""
    if not available() or not labels:
        return {}
    out: dict[str, str] = {}
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "en": {"type": "string"}},
                    "required": ["id", "en"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    }
    for start in range(0, len(labels), 80):
        chunk = labels[start : start + 80]
        if budget and not budget.take():
            break
        payload = "\n".join(f"{i}: {l}" for i, l in enumerate(chunk))
        data = _call_json(CHOOSE_SYSTEM, TRANSLATE_PROMPT.format(payload=payload), schema, 8000)
        for item in (data or {}).get("items", []):
            idx = item.get("id")
            if isinstance(idx, int) and 0 <= idx < len(chunk) and item.get("en"):
                out[chunk[idx]] = item["en"].strip()
    return out
