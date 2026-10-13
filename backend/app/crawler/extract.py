"""HTML extraction: title, H1, canonical, robots, breadcrumb, internal links."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag

from .urls import is_product_url, normalize_url

_WS = re.compile(r"\s+")
_SEP_ONLY = re.compile(r"^[\s>›»/|\\\-–—→＞:]*$")
_CRUMB_ATTR = re.compile(r"bread|crumb|bc-|location-path|path-nav|navi-path", re.I)


def _text(el) -> str:
    return _WS.sub(" ", el.get_text(" ", strip=True)).strip() if el is not None else ""


@dataclass
class PageData:
    title: str | None = None
    h1: str | None = None
    canonical: str | None = None
    meta_robots: str | None = None
    breadcrumb: list[dict] = field(default_factory=list)  # [{name, url}]
    breadcrumb_source: str | None = None
    links: list[dict] = field(default_factory=list)  # [{url, text, zone}]
    product_link_count: int = 0
    has_product_schema: bool = False
    og_type: str | None = None
    has_price: bool = False
    item_list_count: int = 0


def _jsonld_objects(soup: BeautifulSoup) -> list[dict]:
    out: list[dict] = []
    for s in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        raw = s.string or s.get_text() or ""
        try:
            data = json.loads(raw.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        stack = [data]
        while stack:
            d = stack.pop()
            if isinstance(d, list):
                stack.extend(d)
            elif isinstance(d, dict):
                out.append(d)
                if "@graph" in d:
                    stack.append(d["@graph"])
    return out


def _types(d: dict) -> set[str]:
    t = d.get("@type")
    if isinstance(t, list):
        return {str(x).lower() for x in t}
    return {str(t).lower()} if t else set()


def _breadcrumb_jsonld(objs: list[dict], base: str) -> list[dict]:
    for d in objs:
        if "breadcrumblist" not in _types(d):
            continue
        items = d.get("itemListElement") or []
        if isinstance(items, dict):
            items = [items]
        rows = []
        for it in items:
            if not isinstance(it, dict):
                continue
            item = it.get("item")
            name = it.get("name")
            url = None
            if isinstance(item, dict):
                name = name or item.get("name")
                url = item.get("@id") or item.get("url")
            elif isinstance(item, str):
                url = item
            try:
                pos = int(it.get("position") or 0)
            except (TypeError, ValueError):
                pos = 0
            if name:
                rows.append((pos, {"name": _WS.sub(" ", str(name)).strip(), "url": normalize_url(url, base) if url else None}))
        rows.sort(key=lambda x: x[0])
        if rows:
            return [r for _, r in rows]
    return []


def _breadcrumb_microdata(soup: BeautifulSoup, base: str) -> list[dict]:
    root = soup.find(attrs={"itemtype": re.compile("BreadcrumbList", re.I)})
    if not root:
        return []
    out = []
    for li in root.find_all(attrs={"itemprop": "itemListElement"}):
        name_el = li.find(attrs={"itemprop": "name"})
        a = li.find("a", href=True)
        name = _text(name_el) if name_el else _text(li)
        if name and not _SEP_ONLY.match(name):
            out.append({"name": name, "url": normalize_url(a["href"], base) if a else None})
    return out


def _breadcrumb_dom(soup: BeautifulSoup, base: str) -> list[dict]:
    cands: list[Tag] = []
    for el in soup.find_all(["nav", "ol", "ul", "div", "p", "section"]):
        attrs = " ".join([" ".join(el.get("class") or []), el.get("id") or "", el.get("aria-label") or ""])
        if _CRUMB_ATTR.search(attrs):
            cands.append(el)
    best: list[dict] = []
    for el in cands:
        items: list[dict] = []
        lis = el.find_all("li")
        nodes = lis if lis else el.find_all(["a", "span", "strong", "em", "b"], recursive=True)
        seen = set()
        for n in nodes:
            if not lis and n.name != "a" and n.find("a"):
                continue
            a = n if n.name == "a" else n.find("a", href=True)
            name = _text(n)
            if not name or _SEP_ONLY.match(name) or len(name) > 60:
                continue
            if name in seen:
                continue
            seen.add(name)
            href = a.get("href") if a is not None and a.has_attr("href") else None
            items.append({"name": name, "url": normalize_url(href, base) if href else None})
        if 2 <= len(items) <= 10 and len(items) > len(best):
            best = items
    return best


def extract(html: str, url: str) -> PageData:
    soup = BeautifulSoup(html, "lxml")
    pd = PageData()
    if soup.title:
        pd.title = _text(soup.title) or None
    h1 = soup.find("h1")
    pd.h1 = _text(h1) or None
    can = soup.find("link", rel=lambda v: v and "canonical" in (v if isinstance(v, list) else [v]))
    if can and can.get("href"):
        pd.canonical = normalize_url(can["href"], url)
    mr = soup.find("meta", attrs={"name": re.compile("^robots$", re.I)})
    if mr and mr.get("content"):
        pd.meta_robots = mr["content"].lower()
    og = soup.find("meta", attrs={"property": "og:type"})
    if og and og.get("content"):
        pd.og_type = og["content"].lower()

    objs = _jsonld_objects(soup)
    pd.has_product_schema = any("product" in _types(d) for d in objs)
    for d in objs:
        if "itemlist" in _types(d):
            items = d.get("itemListElement") or []
            pd.item_list_count = max(pd.item_list_count, len(items) if isinstance(items, list) else 0)
    pd.has_price = bool(soup.find(attrs={"itemprop": "price"})) or bool(soup.find(class_=re.compile(r"(^|\b)(buy|add-?to-?cart)", re.I)))

    for fn, src in ((_breadcrumb_jsonld, "jsonld"), (_breadcrumb_microdata, "microdata"), (_breadcrumb_dom, "dom")):
        bc = fn(objs, url) if fn is _breadcrumb_jsonld else fn(soup, url)
        if len(bc) >= 1:
            pd.breadcrumb, pd.breadcrumb_source = bc, src
            break

    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        u = normalize_url(a["href"], url)
        if not u or u in seen:
            continue
        seen.add(u)
        zone = "body"
        for parent in a.parents:
            if parent.name in ("nav", "header"):
                zone = "nav"
                break
            if parent.name == "footer":
                zone = "footer"
                break
            cls = " ".join(parent.get("class") or []) + " " + (parent.get("id") or "")
            if re.search(r"(side|left|cate|menu|tree|subcat|sub-cat|category)", cls, re.I):
                zone = "category_nav"
                break
        text = _text(a) or (a.get("title") or "").strip() or (a.find("img").get("alt") if a.find("img") else "") or ""
        pd.links.append({"url": u, "text": text[:120], "zone": zone})
        if is_product_url(u):
            pd.product_link_count += 1
    return pd
