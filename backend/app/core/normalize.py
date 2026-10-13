"""Text normalization for Chinese/English ecommerce keywords and category names."""
from __future__ import annotations

import re
import unicodedata

# Breadcrumb separators seen in uploads and on competitor sites.
BREADCRUMB_SPLIT_RE = re.compile(r"\s*(?:>|＞|›|»|→|\s/\s|\s\|\s)\s*")

_DASHES = "‐‑‒–—―−ー－"
_DASH_RE = re.compile(f"[{_DASHES}]")
_STORAGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(tb|gb|mb|g|t|m|吋|寸|inch|w|mah|hz|mm|cm)(?![a-z])", re.I)
_WIFI_RE = re.compile(r"\bwi[\s\-]?fi\b", re.I)
_USB_C_RE = re.compile(r"\busb[\s\-]?c\b", re.I)
_TYPE_C_RE = re.compile(r"\btype[\s\-]?c\b", re.I)
_MICRO_SD_RE = re.compile(r"\bmicro[\s\-]?sd\b", re.I)
# Keep CJK, latin letters, digits, spaces and a few joiners; everything else is punctuation.
_PUNCT_RE = re.compile(r"[^\w\s㐀-鿿豈-﫿/+&.\-]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")
_CJK_RE = re.compile(r"[㐀-鿿豈-﫿]")
# Traditional-Chinese variant spellings that should compare equal.
_VARIANTS = [("週邊", "周邊"), ("臺", "台"), ("綫", "線"), ("峯", "峰")]


def is_cjk(ch: str) -> bool:
    return bool(_CJK_RE.match(ch))


def has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def normalize(text: str | None) -> str:
    """Human-readable normalized form: NFKC (full→half width), lowercase,
    unified dashes, joined storage units, single spaces."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", str(text))
    t = t.lower().strip()
    for a, b in _VARIANTS:
        t = t.replace(a, b)
    t = _DASH_RE.sub("-", t)
    t = _WIFI_RE.sub("wifi", t)
    t = _USB_C_RE.sub("usb-c", t)
    t = _TYPE_C_RE.sub("type-c", t)
    t = _MICRO_SD_RE.sub("microsd", t)
    t = _STORAGE_RE.sub(lambda m: f"{m.group(1)}{m.group(2).lower()}", t)
    t = _PUNCT_RE.sub(" ", t)
    t = t.replace("_", " ")
    t = _SPACE_RE.sub(" ", t).strip(" -/.&+")
    return t


def norm_key(text: str | None) -> str:
    """Comparison key: normalized with all spaces, hyphens and joiners removed."""
    t = normalize(text)
    return re.sub(r"[\s\-/.&+]", "", t)


def split_breadcrumb(text: str | None) -> list[str]:
    if not text:
        return []
    t = unicodedata.normalize("NFKC", str(text)).strip()
    parts = [p.strip() for p in BREADCRUMB_SPLIT_RE.split(t)]
    return [p for p in parts if p]


def join_breadcrumb(labels: list[str]) -> str:
    return " > ".join(l for l in labels if l)


def name_parts(name: str) -> list[str]:
    """Split compound category names like '電腦/平板周邊' or '網路/分享器'."""
    t = unicodedata.normalize("NFKC", name or "")
    parts = re.split(r"\s*(?:/|、|&|與|及|和|,|，)\s*", t)
    return [p.strip() for p in parts if p.strip() and p.strip() != t.strip()]


def tokens(text: str) -> list[str]:
    """Split normalized text into ASCII-word tokens and CJK runs."""
    out: list[str] = []
    for m in re.finditer(r"[a-z0-9][a-z0-9\-\.]*|[㐀-鿿豈-﫿]+", normalize(text)):
        out.append(m.group(0))
    return out


def char_ngrams(key: str, n: int = 2) -> set[str]:
    if not key:
        return set()
    if len(key) < n:
        return {key}
    return {key[i : i + n] for i in range(len(key) - n + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def common_suffix_len(a: str, b: str) -> int:
    n = 0
    for x, y in zip(reversed(a), reversed(b)):
        if x != y:
            break
        n += 1
    return n


SPEC_RE = re.compile(r"^\d+(?:\.\d+)?[a-z吋寸]*$|^\d+$|^(?:usb|type)-?[a-z0-9.]+$|^[a-z]{1,3}\d+[a-z0-9]*$", re.I)
YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")


def classify_modifier(mod: str) -> str:
    """BRAND | SPEC | ATTRIBUTE (product-type modifier) | GENERIC."""
    from .lexicon import GENERIC_MODIFIERS, KNOWN_BRANDS

    m = normalize(mod)
    if not m:
        return "GENERIC"
    if m in GENERIC_MODIFIERS:
        return "GENERIC"
    if YEAR_RE.match(m) or SPEC_RE.match(m):
        return "SPEC"
    if m in KNOWN_BRANDS:
        return "BRAND"
    if not has_cjk(m):
        # Latin words that aren't specs are most often brands / model lines.
        return "BRAND"
    return "ATTRIBUTE"
