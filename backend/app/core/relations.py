"""Entity relations between product concepts.

Chinese (and English) product names are head-final: the LAST part names the
product type, earlier parts only qualify it.

  無線滑鼠  is-a 滑鼠        (wireless mouse is a mouse)          → parent/child
  滑鼠墊    is-a 墊, NOT 滑鼠  (mouse pad is a pad *for* a mouse)  → accessory-of
  手機殼    NOT 手機           (phone case)                         → accessory-of
  筆電充電器 is-a 充電器, accessory-of 筆電

Only an is-a relation justifies mapping / parent-child placement. A shared word
in modifier position (accessory-of) is never treated as a match.
"""
from __future__ import annotations

from .normalize import norm_key

IS_A = "IS_A"            # child is a kind of parent
SAME = "SAME"            # same concept
SUPERTYPE = "SUPERTYPE"  # other way round: parent is a kind of child
ACCESSORY = "ACCESSORY"  # parent word only appears as a qualifier (accessory / for-X)
SIBLING = "SIBLING"      # both are kinds of the same thing
NONE = "NONE"

# Single-character product heads: 滑鼠墊 = pad, 手機殼 = case, 筆電包 = bag …
ACCESSORY_HEADS = set("墊殼套架線包膜座夾貼袋盒罩扣環繩帶貼片頭桿")


def _canon(vocab, k: str) -> str:
    return (vocab.canonical(k) if vocab is not None else None) or k


def _ends_with(x: str, y: str) -> bool:
    return len(y) >= 2 and len(x) > len(y) and x.endswith(y)


def is_a(child: str, parent: str, vocab=None) -> bool:
    """True when `child` is the same concept as, or a kind of, `parent`."""
    if vocab is not None:
        cache = vocab.__dict__.setdefault("_isa_cache", {})
        k = (child, parent)
        hit = cache.get(k)
        if hit is None:
            hit = cache[k] = _is_a(child, parent, vocab)
        return hit
    return _is_a(child, parent, vocab)


def _is_a(child: str, parent: str, vocab=None) -> bool:
    c, p = norm_key(child), norm_key(parent)
    if not c or not p:
        return False
    cs, ps = {c, _canon(vocab, c)}, {p, _canon(vocab, p)}
    if cs & ps:
        return True
    return any(_ends_with(x, y) for x in cs for y in ps)


def relation(child: str, parent: str, vocab=None) -> str:
    c, p = norm_key(child), norm_key(parent)
    if not c or not p:
        return NONE
    cs, ps = {c, _canon(vocab, c)}, {p, _canon(vocab, p)}
    if cs & ps:
        return SAME
    if any(_ends_with(x, y) for x in cs for y in ps):
        return IS_A
    if any(_ends_with(y, x) for x in cs for y in ps):
        return SUPERTYPE
    if any(len(y) >= 2 and y in x for x in cs for y in ps):
        return ACCESSORY
    # shared head (≥2 chars) but neither contains the other → siblings
    n = 0
    for a, b in zip(reversed(c), reversed(p)):
        if a != b:
            break
        n += 1
    if n >= 2:
        return SIBLING
    return NONE
