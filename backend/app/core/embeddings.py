"""Semantic (vector-embedding) relevance layer.

Every SRP keyword and every category (name + EN name + breadcrumb context) is
embedded with OpenAI `text-embedding-3-small` (256 dims). Vectors are cached in
the `embeddings` table, so re-runs only embed new texts (16k SRPs ≈ $0.003).

The layer never maps on its own authority over the rules; it:
  1. re-ranks rule candidates by meaning (±20 points),
  2. rejects a rule match whose meaning is clearly unrelated (prevents
     irrelevant output from shared characters), and
  3. proposes the nearest category for rule NO_MATCH SRPs when the meaning is
     very close — always as Low Confidence for human review.
Without OPENAI_API_KEY (or with EMBEDDINGS_ENABLED=false) everything runs on rules only.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os

import httpx
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import CategoryNode, Embedding

log = logging.getLogger(__name__)

MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
DIMS = int(os.getenv("EMBEDDING_DIMS", "256"))
REJECT_BELOW = float(os.getenv("EMBEDDING_REJECT_BELOW", "0.22"))   # clearly unrelated
PROPOSE_ABOVE = float(os.getenv("EMBEDDING_PROPOSE_ABOVE", "0.62"))  # very close meaning
MIN_VALID = 45


def embeddings_enabled() -> bool:
    return bool(settings.openai_api_key) and os.getenv("EMBEDDINGS_ENABLED", "true").lower() not in ("0", "false", "no")


def _hash(text: str) -> str:
    return hashlib.sha1(f"{MODEL}|{DIMS}|{text}".encode("utf-8")).hexdigest()


def _encode(v: np.ndarray) -> str:
    return base64.b64encode(v.astype(np.float16).tobytes()).decode()


def _decode(s: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(s), dtype=np.float16).astype(np.float32)


def _call_openai(texts: list[str]) -> list[np.ndarray]:
    r = httpx.post(
        "https://api.openai.com/v1/embeddings",
        json={"model": MODEL, "input": texts, "dimensions": DIMS},
        headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        timeout=120,
    )
    r.raise_for_status()
    data = sorted(r.json()["data"], key=lambda d: d["index"])
    return [np.asarray(d["embedding"], dtype=np.float32) for d in data]


def embed(db: Session, texts: list[str]) -> dict[str, np.ndarray]:
    """Unit-normalised vectors for texts, from cache or the API (batched)."""
    uniq = list(dict.fromkeys(t for t in texts if t))
    out: dict[str, np.ndarray] = {}
    hashes = {t: _hash(t) for t in uniq}
    for i in range(0, len(uniq), 900):
        chunk = uniq[i : i + 900]
        for e in db.scalars(select(Embedding).where(Embedding.text_hash.in_([hashes[t] for t in chunk]))):
            out[e.text] = _decode(e.vector)
    missing = [t for t in uniq if t not in out]
    for i in range(0, len(missing), 512):
        batch = missing[i : i + 512]
        try:
            vecs = _call_openai(batch)
        except Exception as e:  # network / quota → fall back to rules for the rest
            log.warning("embedding call failed: %s", e)
            break
        for t, v in zip(batch, vecs):
            v = v / (np.linalg.norm(v) or 1.0)
            out[t] = v
            db.add(Embedding(text_hash=hashes[t], text=t[:1000], model=MODEL, dims=DIMS, vector=_encode(v)))
        db.flush()
    for t, v in list(out.items()):
        out[t] = v / (np.linalg.norm(v) or 1.0)
    return out


def node_text(n: CategoryNode, ancestors: list[CategoryNode]) -> str:
    path = " > ".join(a.name_cn for a in ancestors)
    en = f" ({n.name_en})" if n.name_en else ""
    return f"{n.name_cn}{en}" + (f" — {path}" if path else "")


class SemanticIndex:
    def __init__(self, enabled: bool):
        self.enabled = enabled
        self.node_ids: list[int] = []
        self.node_matrix: np.ndarray | None = None
        self.node_row: dict[int, int] = {}
        self.vec: dict[str, np.ndarray] = {}

    @classmethod
    def for_nodes(cls, db: Session, ctx) -> "SemanticIndex":
        if not embeddings_enabled():
            return cls(False)
        nodes = ctx.index.real_nodes()
        texts = {n.id: node_text(n, ctx.index.ancestors(n)) for n in nodes}
        vecs = embed(db, list(texts.values()) + [n.name_cn for n in nodes])
        si = cls(True)
        si.vec = vecs
        si.node_ids = [n.id for n in nodes if texts[n.id] in vecs]
        if not si.node_ids:
            return cls(False)
        si.node_matrix = np.stack([vecs[texts[i]] for i in si.node_ids])
        si.node_row = {nid: r for r, nid in enumerate(si.node_ids)}
        si._names = {n.id: n.name_cn for n in nodes}
        return si

    @classmethod
    def for_srps(cls, db: Session, ctx, srps) -> "SemanticIndex":
        si = cls.for_nodes(db, ctx)
        if not si.enabled or not srps:
            return si
        si.vec.update(embed(db, [cls.srp_text(s) for s in srps]))
        si._ctx = ctx
        return si

    @staticmethod
    def srp_text(s) -> str:
        return s.keyword + (f" / {s.keyword_en}" if s.keyword_en else "")

    def sim_text_node(self, text: str, node_id: int) -> float | None:
        v = self.vec.get(text)
        r = self.node_row.get(node_id)
        if v is None or r is None:
            return None
        return float(self.node_matrix[r] @ v)

    def sim_names(self, a: str, b: str) -> float | None:
        va, vb = self.vec.get(a), self.vec.get(b)
        return float(va @ vb) if va is not None and vb is not None else None

    def nearest(self, text: str, k: int = 3) -> list[tuple[int, float]]:
        v = self.vec.get(text)
        if v is None:
            return []
        sims = self.node_matrix @ v
        idx = np.argsort(-sims)[:k]
        return [(self.node_ids[i], float(sims[i])) for i in idx]

    def apply(self, srp, res) -> int:
        """Re-rank / gate a rule MatchResult in place. Returns 1 if a rule match was rejected."""
        from .matcher import Candidate

        text = self.srp_text(srp)
        if text not in self.vec:
            return 0
        rejected = 0
        for c in res.candidates:
            s = self.sim_text_node(text, c.node.id)
            if s is None:
                continue
            c.semantic = s
            bonus = max(-20, min(20, round((s - 0.35) / 0.35 * 20)))
            if bonus:
                c.add(bonus, f"embedding similarity {s:.2f}", relevance=False)
            exactish = c.exact or any(x.startswith(("core product exact", "human-approved")) for x in c.signals)
            if s < REJECT_BELOW and not exactish and not c.conflict:
                c.conflict = True
                c.signals.append(f"rejected: meaning unrelated (embedding {s:.2f} < {REJECT_BELOW})")
                if res.top is c:
                    rejected = 1
        res.candidates.sort(key=lambda c: (-c.score, -c.node.depth))
        top = next((c for c in res.candidates if c.score >= MIN_VALID and not c.conflict), None)
        if top is None and res.method in ("RULE", "NONE"):
            # nothing valid by rules → nearest category by meaning, for review only
            for nid, s in self.nearest(text, 1):
                if s >= PROPOSE_ABOVE:
                    node = self._ctx.index.nodes[nid]
                    c = Candidate(node, score=MIN_VALID + 15, relevance=MIN_VALID + 15)
                    c.signals.append(f"nearest category by meaning (embedding {s:.2f}); no rule match — please review")
                    c.semantic = s
                    res.candidates.insert(0, c)
                    top = c
                    res.method = "SEMANTIC"
        if top is not res.top:
            res.top = top
            res.confidence = 0 if top is None else min(int(round(top.score)), 69 if res.method == "SEMANTIC" else 100)
            if top is not None and res.method == "NONE":
                res.method = "RULE"
            if top is None:
                res.method = "NONE"
        return rejected
