"""URL normalization and taxonomy-oriented crawl filtering."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

TRACKING_PARAMS = re.compile(
    r"^(utm_.*|gclid|fbclid|msclkid|yclid|ref|ref_src|referrer|spm|scm|_ga|mc_cid|mc_eid|src|"
    r"track|tracking|trk|aff.*|affiliate.*|campaign|cmp|mkt|osm|osc|mdiv|sourcepagetype)$",
    re.I,
)
SORT_FILTER_PARAMS = re.compile(
    r"^(sort|sortby|sort_by|order|orderby|dir|direction|filter.*|attr.*|price.*|min.*|max.*|brand.*|color|size|"
    r"facet.*|view|layout|limit|per_page|pagesize|showtype|stype|fq|f\[.*\]|spec.*|tag)$",
    re.I,
)
PAGINATION_PARAMS = re.compile(r"^(page|p|pg|pageno|page_no|pagenum|curpage|offset|start)$", re.I)
SEARCH_PARAMS = re.compile(r"^(q|query|keyword|keywords|kw|search|searchterm|term|s|k)$", re.I)

# Built-in exclusions (cart, checkout, account, ...). Users can add more.
DEFAULT_EXCLUDE = [
    r"/(cart|checkout|basket|order|orders|payment|login|logout|signin|signup|register|member|account|my|mypage|"
    r"wishlist|favorite|favourite|coupon|help|faq|customer|service|cs|contact|about|privacy|terms|policy|"
    r"careers|investor|seller|store-?apply|app-?download|download|notice|news|blog|article)(/|$|\?|\.)",
    r"\.(jpg|jpeg|png|gif|webp|svg|ico|pdf|zip|mp4|mp3|css|js|json|xml)(\?|$)",
    r"^(mailto|tel|javascript):",
    r"/(search|searchresult|find)(/|\?|\.|$)",
    r"[?&](q|keyword|keywords|kw|searchterm)=",
]
PRODUCT_PATTERNS = [
    r"/(goods|good|product|products|prod|item|items|dp|gp/product|p)/[^/]+",
    r"goodsdetail", r"[?&](i_code|goodsno|goods_id|product_id|productid|item_id|itemid|sku|pid)=",
    r"/vp/products/", r"-p-\d+", r"/\d{6,}\.html?$",
]
CAMPAIGN_PATTERNS = [r"/(event|events|campaign|promo|promotion|activity|activities|edm|festival|sale|deal|deals|special|topic|brandweek|lp)(/|$|\?|\.|_|-)"]
CONTENT_PATTERNS = [r"/(blog|article|articles|news|magazine|guide|guides|editorial|story|stories|content)(/|$)"]
CATEGORY_HINTS = [
    r"/(category|categories|cat|c|catalog|dept|department|region|store|sub|subcategory|list|lgrp|mgrp|sgrp|dgrp|browse|np/categories)(/|$|\?|\.)",
    r"(lgrpcategory|mgrpcategory|dgrpcategory|category\.jsp|cate_code|cat_code|categorycode|l_code|m_code|d_code|s_code|cid=)",
]

# Domain profiles: sensible include/exclude defaults for known marketplaces.
SITE_PROFILES: dict[str, dict] = {
    "momoshop.com.tw": {
        "include": [r"/category/(LgrpCategory|MgrpCategory|DgrpCategory|SgrpCategory)\.jsp", r"/category/.*\?.*(l_code|m_code|d_code|cn)="],
        "exclude": [r"/goods/GoodsDetail\.jsp", r"/search/", r"/edm/", r"/mypage/"],
        "keep_params": ["l_code", "m_code", "d_code", "s_code", "cn", "areaCode", "sourcePageType"],
        "render_js": True,
    },
    "24h.pchome.com.tw": {
        "include": [r"/region/[A-Z0-9]+", r"/store/[A-Z0-9]+", r"/sign/"],
        "exclude": [r"/prod/", r"/search/", r"/onsale/", r"/activity/"],
        "keep_params": [],
        "render_js": True,
    },
    "tw.coupang.com": {
        "include": [r"/categories/\d+", r"/np/categories/\d+"],
        "exclude": [r"/vp/products/", r"/np/search"],
        "keep_params": [],
        "render_js": True,
    },
    "shopee.tw": {
        "include": [r"-cat\.\d+", r"/mall/.*-cat\."],
        "exclude": [r"-i\.\d+\.\d+", r"/search"],
        "keep_params": [],
        "render_js": True,
    },
}


def profile_for(host: str) -> dict | None:
    host = host.lower()
    for dom, prof in SITE_PROFILES.items():
        if host == dom or host.endswith("." + dom):
            return prof
    return None


def normalize_url(url: str, base: str | None = None, keep_params: list[str] | None = None) -> str | None:
    if not url:
        return None
    url = url.strip()
    if url.startswith(("javascript:", "mailto:", "tel:", "#")):
        return None
    if base:
        url = urljoin(base, url)
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None
    host = (parts.hostname or "").lower()
    if not host:
        return None
    netloc = host + (f":{parts.port}" if parts.port and parts.port not in (80, 443) else "")
    keep = {k.lower() for k in (keep_params or [])}
    q = []
    for k, v in parse_qsl(parts.query, keep_blank_values=False):
        kl = k.lower()
        if kl in keep:
            q.append((k, v))
        elif TRACKING_PARAMS.match(k):
            continue
        else:
            q.append((k, v))
    q.sort()
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return urlunsplit((parts.scheme.lower(), netloc, path, urlencode(q), ""))


def _any(patterns: list[str], url: str) -> bool:
    return any(re.search(p, url, re.I) for p in patterns)


def is_product_url(url: str) -> bool:
    return _any(PRODUCT_PATTERNS, url)


def is_campaign_url(url: str) -> bool:
    return _any(CAMPAIGN_PATTERNS, url)


def is_content_url(url: str) -> bool:
    return _any(CONTENT_PATTERNS, url)


def looks_like_category_url(url: str) -> bool:
    return _any(CATEGORY_HINTS, url)


def query_kind(url: str) -> str | None:
    """'SEARCH' | 'FILTER' | 'PAGINATION' | None based on query params."""
    params = [k for k, _ in parse_qsl(urlsplit(url).query)]
    if any(SEARCH_PARAMS.match(k) for k in params):
        return "SEARCH"
    if any(SORT_FILTER_PARAMS.match(k) for k in params):
        return "FILTER"
    if any(PAGINATION_PARAMS.match(k) for k in params):
        return "PAGINATION"
    return None


@dataclass
class UrlFilter:
    start_url: str
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    keep_params: list[str] = field(default_factory=list)
    allow_subdomains: bool = False

    def __post_init__(self):
        self.host = (urlsplit(self.start_url).hostname or "").lower()
        prof = profile_for(self.host)
        self.profile = prof
        if prof:
            self.include = list(self.include) or list(prof["include"])
            self.exclude = list(self.exclude) + list(prof["exclude"])
            self.keep_params = list(self.keep_params) + list(prof["keep_params"])
        self.exclude = list(self.exclude) + DEFAULT_EXCLUDE
        root = self.host.removeprefix("www.")
        self.root_domain = ".".join(root.split(".")[-3:]) if root.endswith((".com.tw", ".co.jp", ".co.kr", ".co.uk")) else ".".join(root.split(".")[-2:])

    def same_site(self, url: str) -> bool:
        h = (urlsplit(url).hostname or "").lower()
        if h == self.host:
            return True
        if self.allow_subdomains:
            return h == self.root_domain or h.endswith("." + self.root_domain)
        return False

    def decision(self, url: str) -> tuple[bool, str]:
        """Whether to ENQUEUE the url (the start URL is always fetched)."""
        if not self.same_site(url):
            return False, "off-site"
        if _any(self.exclude, url):
            return False, "excluded pattern"
        if is_product_url(url):
            return False, "product page"
        qk = query_kind(url)
        if qk in ("SEARCH", "FILTER", "PAGINATION"):
            return False, f"{qk.lower()} parameters"
        if self.include and not _any(self.include, url):
            return False, "not matching include patterns"
        return True, "ok"
