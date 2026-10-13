"""Vocabulary, synonym/concept resolution and core-product extraction.

Core product = the longest known product term that ends a text segment
(Chinese compounds are head-final: 無線滑鼠 -> 滑鼠, 筆電充電器 -> 筆電充電器).
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from ..models import CategoryNode, Synonym
from .lexicon import GENERIC_MODIFIERS
from .relations import ACCESSORY_HEADS
from .normalize import (
    classify_modifier,
    has_cjk,
    is_cjk,
    name_parts,
    norm_key,
    normalize,
)

KIND_PRIORITY = {"CATEGORY": 3, "SYNONYM": 3, "CANONICAL": 3, "EN": 3, "PART": 2, "TOKEN": 2, "HEAD": 1}
_SEP_RE = re.compile(r"[\s\-/.&+]")
_ASCII_RE = re.compile(r"[a-z0-9]")


@dataclass
class Term:
    kind: str
    label: str
    node_ids: set[int] = field(default_factory=set)
    canonical_key: str | None = None
    canonical_label: str | None = None
    synonym_source: str | None = None  # HUMAN | DEFAULT
    preferred_node_id: int | None = None


@dataclass
class Extraction:
    text: str
    norm: str
    key: str
    core_label: str | None = None
    core_key: str | None = None
    core_kind: str | None = None
    canonical_key: str | None = None
    canonical_label: str | None = None
    modifiers: list[str] = field(default_factory=list)
    modifier_types: dict[str, str] = field(default_factory=dict)
    matched_keys: list[str] = field(default_factory=list)
    alias_exact: Term | None = None
    term_node_ids: set[int] = field(default_factory=set)

    @property
    def label_key(self) -> str:
        """The product phrase without brand / spec / generic words: 'asus 筆電充電器 65w' → 筆電充電器."""
        k = self.key
        for m in self.modifiers:
            if self.modifier_types.get(m) in ("BRAND", "SPEC", "GENERIC"):
                k = k.replace(m, "", 1)
        return k or self.core_key or self.key

    @property
    def only_generic_modifiers(self) -> bool:
        return all(t == "GENERIC" for t in self.modifier_types.values())

    @property
    def attribute_modifiers(self) -> list[str]:
        return [m for m in self.modifiers if self.modifier_types.get(m) == "ATTRIBUTE"]


def _keyed(text: str) -> tuple[str, set[int], set[int]]:
    """Return comparison key, the key positions preceded by any separator, and
    the positions preceded by a hard separator (space or slash)."""
    norm = normalize(text)
    key_chars: list[str] = []
    boundaries: set[int] = {0}
    hard: set[int] = {0}
    for ch in norm:
        if _SEP_RE.match(ch):
            boundaries.add(len(key_chars))
            if ch in " /":
                hard.add(len(key_chars))
        else:
            key_chars.append(ch)
    key = "".join(key_chars)
    boundaries.add(len(key))
    hard.add(len(key))
    return key, boundaries, hard


def _is_ascii(ch: str) -> bool:
    return bool(_ASCII_RE.match(ch))


class Vocabulary:
    def __init__(self, nodes: list[CategoryNode], synonyms: list[Synonym]):
        self.terms: dict[str, list[Term]] = defaultdict(list)
        self.max_len = 2
        self.alias: dict[str, Term] = {}
        for n in nodes:
            if n.is_root:
                continue
            self._add(n.norm_key, Term("CATEGORY", n.name_cn, {n.id}))
            if n.name_en:
                self._add(norm_key(n.name_en), Term("EN", n.name_en, {n.id}))
            for p in name_parts(n.name_cn):
                self._add(norm_key(p), Term("PART", p, {n.id}))
            # latin word tokens ("switch" in "Nintendo Switch", "hub" in "USB Hubs")
            for src in (n.name_cn, n.name_en or ""):
                for tok in re.findall(r"[a-z][a-z0-9]{2,}", normalize(src)):
                    if tok in GENERIC_MODIFIERS or norm_key(tok) == n.norm_key:
                        continue
                    self._add(tok, Term("TOKEN", tok, {n.id}))
                    if tok.endswith("s") and len(tok) >= 4:
                        self._add(tok[:-1], Term("TOKEN", tok[:-1], {n.id}))
            # Head suffixes of CJK names (PC用喇叭 -> 喇叭, 用喇叭)
            k = n.norm_key
            m = re.search(r"[㐀-鿿]+$", k)
            if m:
                run = m.group(0)
                for L in range(2, len(run)):
                    self._add(run[-L:], Term("HEAD", run[-L:], {n.id}))
                if len(k) > len(run) and len(run) >= 2:  # mixed name like "pc用喇叭"
                    self._add(run, Term("HEAD", run, {n.id}))
        # Synonyms: human approved beat defaults for the same alias.
        ordered = sorted(synonyms, key=lambda s: 0 if s.source == "DEFAULT" else 1)
        for s in ordered:
            ak = norm_key(s.alias)
            ck = norm_key(s.canonical)
            if not ak or not ck or ak == ck:
                continue
            t = Term("SYNONYM", s.alias, set(), ck, s.canonical, s.source, s.preferred_node_id)
            if s.preferred_node_id:
                t.node_ids.add(s.preferred_node_id)
            self.alias[ak] = t
            self.terms[ak] = [x for x in self.terms[ak] if x.kind != "SYNONYM"]
            self._add(ak, t)
            self._add(ck, Term("CANONICAL", s.canonical))
            self.max_len = max(self.max_len, len(ak))

    def _add(self, key: str, term: Term) -> None:
        if not key or len(key) < 2 and not (len(key) == 1 and not is_cjk(key)):
            return
        if len(key) < 2:
            return
        bucket = self.terms[key]
        for existing in bucket:
            if existing.kind == term.kind and existing.canonical_key == term.canonical_key:
                existing.node_ids |= term.node_ids
                return
        bucket.append(term)
        self.max_len = max(self.max_len, len(key))

    def canonical(self, key: str | None) -> str | None:
        if not key:
            return None
        t = self.alias.get(key)
        return t.canonical_key if t else key

    def extract(self, text: str) -> Extraction:
        key, bounds, hard = _keyed(text)
        ext = Extraction(text=text, norm=normalize(text), key=key)
        if not key:
            return ext
        ext.alias_exact = self.alias.get(key)
        n = len(key)
        matches: list[tuple[int, int, str]] = []
        for i in range(n):
            if i not in bounds and _is_ascii(key[i - 1]) and _is_ascii(key[i]):
                continue
            for j in range(min(n, i + self.max_len), i + 1, -1):
                sub = key[i:j]
                if sub not in self.terms:
                    continue
                if j not in bounds and _is_ascii(key[j - 1]) and _is_ascii(key[j]):
                    continue
                matches.append((i, j, sub))
        for _, _, sub in matches:
            for t in self.terms[sub]:
                ext.term_node_ids |= t.node_ids
        ext.matched_keys = sorted({m[2] for m in matches}, key=len, reverse=True)

        def seg_end(j: int) -> bool:
            return j == n or j in bounds or is_cjk(key[j - 1]) != is_cjk(key[j])

        def best_kind(sub: str) -> int:
            return max(KIND_PRIORITY.get(t.kind, 0) for t in self.terms[sub])

        if matches:
            i, j, sub = max(
                matches,
                key=lambda m: (seg_end(m[1]), best_kind(m[2]) >= 2, m[1] == n, m[1] - m[0], best_kind(m[2]), m[1]),
            )
            # Head-final rule: "筆電支架" — a known term followed by an unknown CJK
            # remainder means the remainder is the product head (支架), not the term.
            run_end = j
            while run_end < n and is_cjk(key[run_end]) and is_cjk(key[j - 1]) and run_end not in bounds:
                run_end += 1
            if run_end - j >= 2 and key[j:run_end] not in GENERIC_MODIFIERS and not any(m[0] >= j and m[1] <= run_end for m in matches):
                ext.core_key, ext.core_kind = key[j:run_end], "GUESS"
                ext.core_label = ext.core_key
                ext.canonical_key, ext.canonical_label = self.canonical(ext.core_key), ext.core_label
                rest = [(0, j), (run_end, n)]
                ext.modifiers, ext.modifier_types = self._modifiers(key, rest, hard)
                return ext
            # Single-character head after a known term: 滑鼠墊 (pad), 手機殼 (case) — the product
            # is the compound, not the term in front of it.
            if j < n and key[j] in ACCESSORY_HEADS and (j + 1 == n or (j + 1) in bounds or not is_cjk(key[j + 1])) \
                    and not any(m[0] <= i and m[1] > j for m in matches):
                ext.core_key, ext.core_kind = key[i : j + 1], "GUESS"
                ext.core_label = ext.core_key
                ext.canonical_key, ext.canonical_label = self.canonical(ext.core_key), ext.core_label
                ext.modifiers, ext.modifier_types = self._modifiers(key, [(0, i), (j + 1, n)], hard)
                return ext
            terms = self.terms[sub]
            top = max(terms, key=lambda t: KIND_PRIORITY.get(t.kind, 0))
            ext.core_key = sub
            ext.core_kind = top.kind
            ext.core_label = self._display(text, sub)
            syn = next((t for t in terms if t.kind == "SYNONYM"), None)
            if syn:
                ext.canonical_key, ext.canonical_label = syn.canonical_key, syn.canonical_label
            else:
                ext.canonical_key, ext.canonical_label = sub, ext.core_label
            rest = [(0, i), (j, n)]
        else:
            m = None
            for m in re.finditer(r"[㐀-鿿]{2,}", key):
                pass
            if m:
                ext.core_key, ext.core_kind = m.group(0), "GUESS"
                ext.core_label = m.group(0)
                rest = [(0, m.start()), (m.end(), n)]
            else:
                ext.core_key, ext.core_kind, ext.core_label = key, "GUESS", ext.norm
                rest = []
            ext.canonical_key, ext.canonical_label = self.canonical(ext.core_key), ext.core_label
        if ext.alias_exact:
            ext.canonical_key = ext.alias_exact.canonical_key
            ext.canonical_label = ext.alias_exact.canonical_label

        ext.modifiers, ext.modifier_types = self._modifiers(key, rest, hard)
        return ext

    @staticmethod
    def _modifiers(key: str, rest: list[tuple[int, int]], hard: set[int]) -> tuple[list[str], dict[str, str]]:
        mods: list[str] = []
        for a, b in rest:
            cur = ""
            for idx in range(a, b):
                ch = key[idx]
                unit_join = cur and cur[-1].isdigit() and ch in "吋寸"
                if cur and not unit_join and (idx in hard or is_cjk(cur[-1]) != is_cjk(ch)):
                    mods.append(cur)
                    cur = ""
                cur += ch
            if cur:
                mods.append(cur)
        mods = [m for m in mods if m]
        return mods, {m: classify_modifier(m) for m in mods}

    @staticmethod
    def _display(text: str, sub: str) -> str:
        # Recover original casing for latin terms where possible.
        if has_cjk(sub):
            return sub
        m = re.search(re.escape(sub), re.sub(r"[\s\-]", "", text or ""), re.I)
        return m.group(0) if m else sub
