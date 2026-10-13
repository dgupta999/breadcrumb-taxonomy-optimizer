"""Deterministic category candidate generation + scoring (SRP → category and
competitor category → category). Scores follow the agreed rubric:

  Human-approved mapping        +150
  Exact normalized match        +100
  Exact synonym match            +90
  Core product exact match       +80
  Canonical concept match        +75
  Category term contained in SRP +50
  SRP product term in category   +50
  Important shared token         +10 each (max 30)
  Semantic similarity           0..+30
  Deeper relevant category       +2 / depth level
  Very broad parent              -20
  Clearly wrong taxonomy branch -100
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..models import CategoryNode
from .concepts import Extraction, Vocabulary
from .lexicon import BRANCH_CONFLICTS, GENERIC_MODIFIERS, GROUP_SUFFIXES
from .normalize import char_ngrams, common_suffix_len, jaccard, name_parts, norm_key, normalize, tokens
from .relations import is_a
from .taxonomy import TaxonomyIndex

MIN_VALID_SCORE = 45


@dataclass
class Candidate:
    node: CategoryNode
    score: float = 0.0
    relevance: float = 0.0  # lexical/semantic part only (no depth bonus)
    signals: list[str] = field(default_factory=list)
    exact: bool = False
    conflict: bool = False

    def add(self, pts: float, why: str, relevance: bool = True) -> None:
        self.score += pts
        if relevance:
            self.relevance += pts
        self.signals.append(f"{why} ({pts:+.0f})")


@dataclass
class MatchResult:
    extraction: Extraction
    candidates: list[Candidate]
    top: Candidate | None
    confidence: int
    ambiguous: bool
    method: str  # HUMAN | RULE | NONE


def _sense(text_norm: str, head: str, exclude: set[str] | None = None) -> str | None:
    senses = BRANCH_CONFLICTS.get(head)
    if not senses:
        return None
    hits = {}
    for sense, words in senses.items():
        n = sum(1 for w in words if w in text_norm and w not in (exclude or set()))
        if n:
            hits[sense] = n
    if not hits:
        return None
    best = max(hits.values())
    winners = [s for s, n in hits.items() if n == best]
    return winners[0] if len(winners) == 1 else None


def branch_conflict(query_norm: str, node: CategoryNode) -> str | None:
    """Return an explanation if the query and the candidate sit in clearly different senses."""
    node_ctx = normalize(f"{node.breadcrumb_cn} {node.breadcrumb_en or ''}")
    for head in BRANCH_CONFLICTS:
        if head not in query_norm:
            continue
        if head not in node_ctx and head not in normalize(node.name_cn) and head not in normalize(node.name_en or ""):
            continue
        qs = _sense(query_norm.replace(head, " "), head)
        ns = _sense(node_ctx.replace(head, " "), head)
        if qs and ns and qs != ns:
            return f"'{head}' means {qs} in query but {ns} in category branch"
    return None


def _strip_group(part: str) -> tuple[str, str | None]:
    for suf in sorted(GROUP_SUFFIXES, key=len, reverse=True):
        if part.endswith(suf) and len(part) > len(suf):
            return part[: -len(suf)], suf
    return part, None


def group_profile(name: str, vocab: Vocabulary) -> tuple[bool, set[str], set[str]]:
    """(is_group_label, concept stems, group suffixes) — 網路設備 → (True, {網路}, {設備})."""
    parts = [norm_key(p) for p in (name_parts(name) or [name])]
    # a section/group label: compound name ("網路/分享器") or ends with a group word ("儲存裝置", "電腦3C")
    is_group = "/" in name or any(p.endswith(suf) for p in parts for suf in GROUP_SUFFIXES)
    stems, sufs = set(), set()
    for p in parts:
        if p in GROUP_SUFFIXES:  # a part that is only a group word ("電腦/週邊" → 周邊)
            sufs.add(p)
            continue
        st, suf = _strip_group(p)
        if st:
            stems.add(vocab.canonical(st) or st)
        if suf:
            sufs.add(suf)
    return is_group, stems, sufs


class Matcher:
    def __init__(self, index: TaxonomyIndex, vocab: Vocabulary):
        self.index = index
        self.vocab = vocab
        self.nodes = index.real_nodes()
        self._bigrams: dict[str, set[int]] = defaultdict(set)
        self._node_grams: dict[int, set[str]] = {}
        self._node_tokens: dict[int, set[str]] = {}
        for n in self.nodes:
            g = char_ngrams(n.norm_key) | (char_ngrams(norm_key(n.name_en)) if n.name_en else set())
            self._node_grams[n.id] = g
            for x in g:
                self._bigrams[x].add(n.id)
            toks = {norm_key(t) for t in tokens(n.name_cn)} | ({norm_key(t) for t in tokens(n.name_en)} if n.name_en else set())
            toks |= {norm_key(p) for p in n.name_cn.replace("/", " ").split()}
            self._node_tokens[n.id] = {t for t in toks if t and t not in GENERIC_MODIFIERS}
        self._group = {n.id: group_profile(n.name_cn, vocab) for n in self.nodes}
        self._by_stem: dict[str, set[int]] = defaultdict(set)
        for nid, (is_group, stems, _) in self._group.items():
            if is_group:
                for st in stems:
                    self._by_stem[st].add(nid)

    # ------------------------------------------------------------------ candidates
    def _candidate_ids(self, ext: Extraction, extra_keys: list[str]) -> set[int]:
        ids: set[int] = set(ext.term_node_ids)
        for k in [ext.key, ext.core_key, ext.canonical_key, *extra_keys]:
            if not k:
                continue
            for n in self.index.by_key.get(k, []):
                ids.add(n.id)
        # containment of core term inside category names
        for k in {ext.core_key, ext.canonical_key}:
            if not k:
                continue
            grams = char_ngrams(k)
            pool: set[int] = set()
            for g in grams:
                pool |= self._bigrams.get(g, set())
            for nid in pool:
                if k in self.index.nodes[nid].norm_key:
                    ids.add(nid)
        # fuzzy: top bigram overlaps
        q = char_ngrams(ext.key)
        pool = defaultdict(int)
        for g in q:
            for nid in self._bigrams.get(g, ()):
                pool[nid] += 1
        ranked = sorted(pool.items(), key=lambda kv: -kv[1])[:25]
        ids |= {nid for nid, _ in ranked}
        is_group, stems, _ = group_profile(ext.text, self.vocab)
        if is_group:
            for st in stems:
                ids |= self._by_stem.get(st, set())
        return {i for i in ids if i in self.index.nodes and not self.index.nodes[i].is_root}

    # ------------------------------------------------------------------ scoring
    def _score(self, node: CategoryNode, ext: Extraction) -> Candidate:
        c = Candidate(node)
        nk = node.norm_key
        ek = norm_key(node.name_en) if node.name_en else ""
        keys = {k for k in (nk, ek) if k}
        node_canon = {self.vocab.canonical(k) for k in keys}
        core = ext.core_key
        canon = ext.canonical_key

        if ext.key in keys:
            c.add(100, "exact normalized category match")
            c.exact = True
        elif ext.alias_exact and (
            (ext.alias_exact.preferred_node_id == node.id) or (ext.alias_exact.canonical_key in keys)
        ):
            c.add(90, f"exact synonym match ({ext.alias_exact.label} → {ext.alias_exact.canonical_label})")
            c.exact = True
        if core and core in keys:
            c.add(80, f"core product exact match '{ext.core_label}'")
        elif canon and (canon in keys or canon in node_canon or (core and self.vocab.canonical(core) in node_canon)):
            c.add(75, f"canonical concept match '{ext.canonical_label}'")
        if not c.exact:
            ql = ext.label_key
            q_is_a = any(is_a(x, k, self.vocab) for x in {ql, core} if x for k in keys)
            if not q_is_a and node.name_en and core and core.isascii():
                # English is head-final too: "type-c hub" is a hub, like "USB Hubs"
                sing = lambda w: w[:-1] if w.endswith("s") and len(w) > 3 else w  # noqa: E731
                q_head = sing(normalize(ext.text).split()[-1]) if normalize(ext.text).split() else ""
                n_words = normalize(node.name_en).split()
                q_is_a = bool(q_head) and bool(n_words) and q_head == sing(n_words[-1]) and q_head == sing(core)
            if q_is_a:
                c.add(50, f"query is a kind of '{node.name_cn}'")
            elif any(len(k) >= 2 and k in ext.key for k in keys):
                # 手機殼 / 滑鼠墊: the category word only qualifies another product → accessory-of, not a match
                c.add(-40, f"'{node.name_cn}' only appears as a qualifier (accessory-of relation, not a kind of it)")
            if core and len(core) >= 2 and core not in keys and any(is_a(k, core, self.vocab) for k in keys):
                c.add(20, f"category is a more specific kind of '{ext.core_label}'")
            elif core and nk not in ext.key:
                # all category terms present but split / reordered: "電競滑鼠 無線" vs 無線滑鼠
                mods = [norm_key(m) for m in ext.modifiers]
                if any(m + core == nk or core + m == nk for m in mods if m):
                    c.add(50, "all category terms present in query")
                    c.add(80, f"core product '{ext.core_label}' with category qualifier")
                elif not c.exact:
                    parts = [norm_key(p) for p in name_parts(node.name_cn)]
                    hit = [p for p in parts if len(p) >= 2 and any(is_a(x, p, self.vocab) for x in {ext.label_key, core} if x)]
                    if hit:
                        c.add(40, f"query is a kind of '{hit[0]}' (part of '{node.name_cn}')")
        shared = {k for k in ext.matched_keys if k in self._node_tokens[node.id] or k in keys}
        shared |= {norm_key(t) for t in tokens(ext.norm) if norm_key(t) in self._node_tokens[node.id]}
        shared -= {ext.key}
        if shared:
            c.add(min(30, 10 * len(shared)), f"shared tokens {sorted(shared)[:3]}")
        sim = max(
            jaccard(char_ngrams(ext.key), self._node_grams[node.id]),
            jaccard(char_ngrams(core or ""), self._node_grams[node.id]),
        )
        suffix = common_suffix_len(core or ext.key, nk)
        sem = min(30.0, sim * 30 + (5 * min(suffix, 3) if suffix >= 2 else 0))
        if sem >= 1:
            c.add(round(sem), "semantic similarity")
        # Group / section categories: 網路設備 ≈ 網路/分享器, 儲存設備 ≈ 儲存裝置, 筆電配件 ≠ 電腦配件
        q_group, q_stems, q_sufs = group_profile(ext.text, self.vocab)
        n_group, n_stems, n_sufs = self._group[node.id]
        if q_group and n_group and q_stems and n_stems and not c.exact:
            if q_stems & n_stems:
                c.add(70, f"equivalent group category (concept {sorted(q_stems & n_stems)[0]})")
                if q_sufs & n_sufs:
                    c.add(20, "same group type")
            elif (q_sufs & n_sufs) and c.relevance < 80:
                # 筆電配件 vs 電腦配件: same kind of group, different concept → not a match
                c.add(-30, "different group concept")
                c.conflict = True
        if c.relevance > 0:
            c.add(2 * node.depth, f"depth {node.depth} specificity", relevance=False)
            parent = self.index.nodes.get(node.parent_id) if node.parent_id else None
            if parent is not None and parent.norm_key == nk:
                c.add(-15, "duplicate-level page (parent has the same name)", relevance=False)
        why = branch_conflict(ext.norm, node)
        if why:
            c.add(-100, f"clearly wrong taxonomy branch: {why}")
            c.conflict = True
        return c

    def match(
        self,
        text: str,
        *,
        extra_text: str | None = None,
        approved_node_id: int | None = None,
        context_parent_ids: set[int] | None = None,
        context_child_keys: set[str] | None = None,
    ) -> MatchResult:
        ext = self.vocab.extract(text)
        extra_keys: list[str] = []
        ext2 = None
        if extra_text:
            ext2 = self.vocab.extract(extra_text)
            extra_keys = [ext2.key, ext2.core_key or ""]
        ids = self._candidate_ids(ext, extra_keys)
        if ext2:
            ids |= self._candidate_ids(ext2, [])
        if approved_node_id and approved_node_id in self.index.nodes:
            ids.add(approved_node_id)
        cands: list[Candidate] = []
        for nid in ids:
            node = self.index.nodes[nid]
            c = self._score(node, ext)
            if ext2:
                c2 = self._score(node, ext2)
                if c2.score * 0.9 > c.score:
                    c2.score *= 0.9
                    c2.signals.append("(scored on English keyword)")
                    c = c2
            if approved_node_id == nid:
                c.add(150, "human-approved mapping")
            if context_parent_ids:
                anc_ids = {a.id for a in self.index.ancestors(node)}
                if anc_ids & context_parent_ids:
                    c.add(15, "parent context agrees")
            if context_child_keys:
                kids = {k.norm_key for k in self.index.children.get(node.id, [])}
                overlap = len(kids & context_child_keys)
                if overlap:
                    c.add(min(20, 5 * overlap), f"{overlap} shared child categories")
            cands.append(c)

        # Deepest valid category rule: penalize broad ancestors of a relevant candidate.
        strong = [c for c in cands if c.relevance >= 50 and not c.conflict and not any(s.startswith("duplicate-level") for s in c.signals)]
        for c in cands:
            if any(s.startswith("same group type") for s in c.signals):
                continue  # 電腦/週邊 ≈ 電腦/平板周邊: the matching section, not a too-broad parent
            if c.node.children_count and any(self.index.is_ancestor(c.node, d.node) for d in strong if d is not c):
                c.add(-20, "very broad parent (more specific valid category exists)", relevance=False)

        cands.sort(key=lambda c: (-c.score, -c.node.depth))
        top = cands[0] if cands and cands[0].score >= MIN_VALID_SCORE and not cands[0].conflict else None
        method = "NONE"
        conf = 0
        ambiguous = False
        if top:
            method = "HUMAN" if approved_node_id == top.node.id else "RULE"
            conf = 100 if method == "HUMAN" else int(min(100, round(top.score)))
            rival = next(
                (
                    c
                    for c in cands[1:]
                    if not self.index.is_ancestor(c.node, top.node)
                    and not self.index.is_ancestor(top.node, c.node)
                    and not c.conflict
                ),
                None,
            )
            if method != "HUMAN" and rival and top.score - rival.score < 10:
                ambiguous = True
                conf = max(0, conf - 15)
                top.signals.append(f"close rival: {rival.node.name_cn} ({rival.score:.0f})")
        return MatchResult(ext, cands[:10], top, conf, ambiguous, method)


def band(conf: int, matched: bool) -> str:
    if not matched:
        return "NO_MATCH"
    if conf >= 90:
        return "AUTO_APPROVED"
    if conf >= 70:
        return "NEEDS_REVIEW"
    return "LOW_CONFIDENCE"


def candidate_payload(c: Candidate) -> dict:
    return {
        "node_id": c.node.id,
        "name": c.node.name_cn,
        "breadcrumb": c.node.breadcrumb_cn,
        "score": round(c.score, 1),
        "signals": c.signals[:8],
    }
