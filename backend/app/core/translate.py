"""English label resolution: input → existing taxonomy → glossary/rule → AI → MISSING."""
from __future__ import annotations

from functools import lru_cache

from . import llm
from .lexicon import EN_GLOSSARY
from .normalize import has_cjk, norm_key


@lru_cache(maxsize=1)
def _glossary() -> dict[str, str]:
    return {norm_key(k): v for k, v in EN_GLOSSARY.items()}


def glossary_en(label: str | None) -> str | None:
    if not label:
        return None
    hit = _glossary().get(norm_key(label))
    if hit:
        return hit
    if not has_cjk(label):
        # Already latin (e.g. "SSD", "microSD") — keep as-is.
        return label.strip()
    return None


class Translator:
    """Collects labels that need English, resolves deterministically first and
    batches the rest to the LLM. Every result carries its source."""

    def __init__(self, known: dict[str, str] | None = None, budget: llm.LLMBudget | None = None):
        self.known = {norm_key(k): v for k, v in (known or {}).items() if v}
        self.budget = budget
        self._pending: set[str] = set()
        self._ai: dict[str, str] = {}

    def lookup(self, label: str) -> tuple[str | None, str]:
        k = norm_key(label)
        if k in self.known:
            return self.known[k], "TAXONOMY"
        g = glossary_en(label)
        if g:
            return g, "RULE"
        if label in self._ai:
            return self._ai[label], "AI"
        return None, "MISSING"

    def want(self, label: str) -> None:
        if label and self.lookup(label)[0] is None:
            self._pending.add(label)

    def flush(self) -> None:
        if self._pending:
            self._ai.update(llm.translate_batch(sorted(self._pending), self.budget))
            self._pending.clear()
