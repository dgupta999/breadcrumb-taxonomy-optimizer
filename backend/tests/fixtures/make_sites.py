"""Generate two small static competitor sites used by the crawler tests.

momo-like:   JSON-LD BreadcrumbList, /category/<code>.html
pchome-like: HTML <ol class="breadcrumb">, /region/<code> and /store/<code>
Both include product, cart, login, search and sort links that must be skipped.
"""
import json
from pathlib import Path

ROOT = Path(__file__).parent / "sites"

MOMO = ("3C", [
    ("電腦周邊", [("滑鼠", [("無線滑鼠", []), ("電競滑鼠", [])]), ("鍵盤", [("機械鍵盤", [])]), ("電腦配件", [("變壓器", []), ("筆電散熱墊", [])])]),
    ("網路設備", [("無線路由器", []), ("網路交換器", []), ("Mesh WiFi", [])]),
    ("筆電配件", [("筆電充電器", []), ("筆電電池", []), ("筆電包", []), ("筆電支架", [])]),
    ("儲存設備", [("記憶卡", []), ("SSD", []), ("外接硬碟", []), ("讀卡機", [])]),
    ("顯示卡/主機板", [("顯示卡", []), ("主機板", [])]),
    ("電玩", [("Nintendo Switch", []), ("PS5", [])]),
])
PCHOME = ("電腦/週邊", [
    ("電腦配件", [("滑鼠", []), ("鍵盤", []), ("電腦喇叭", []), ("網路攝影機", []), ("變壓器", [])]),
    ("網通設備", [("無線路由器", []), ("網路交換器", [("PoE交換器", [])])]),
    ("筆電配件", [("筆電充電器", []), ("筆電電池", []), ("筆電包", [])]),
    ("顯示卡/主機板", [("顯示卡", []), ("主機板", []), ("記憶體", [])]),
    ("儲存", [("記憶卡", []), ("隨身碟", [])]),
])


def walk(tree, path=()):
    name, kids = tree
    yield path + (name,), kids
    for k in kids:
        yield from walk(k, path + (name,))


def build(site: str, tree, home: str, url_for, crumb_html):
    out = ROOT / site
    out.mkdir(parents=True, exist_ok=True)
    (out / "robots.txt").write_text("User-agent: *\nDisallow: /private/\n", encoding="utf-8")
    codes = {}
    for i, (path, _) in enumerate(walk(tree)):
        codes[path] = f"C{i:03d}"
    tops = [(tree[0], k[0]) for k in tree[1]]
    for path, kids in walk(tree):
        url = url_for(path, codes[path], len(kids) == 0)
        crumbs = [(home, "/")] + [(p, url_for(path[: j + 1], codes[path[: j + 1]], False)) for j, p in enumerate(path)]
        child_links = "".join(f'<li><a href="{url_for(path + (k[0],), codes[path + (k[0],)], not k[1])}">{k[0]}</a></li>' for k in kids)
        products = ""
        if not kids:
            products = "".join(f'<div class="prd"><a href="/goods/GoodsDetail.jsp?i_code={codes[path]}{n}">商品 {n}</a></div>' for n in range(12))
        nav = "".join(f'<a href="{url_for((t0, t), codes[(t0, t)], False)}">{t}</a>' for t0, t in tops)
        html = f"""<!doctype html><html><head><meta charset="utf-8"><title>{path[-1]} - {home}</title>
<link rel="canonical" href="{url}">{crumb_html(crumbs)[0]}</head><body>
<header><nav>{nav}<a href="/cart">購物車</a><a href="/login">登入</a><a href="/search?keyword=滑鼠">搜尋</a></nav></header>
{crumb_html(crumbs)[1]}
<h1>{path[-1]}</h1>
<div class="category-list"><ul>{child_links}</ul></div>
<div class="sort"><a href="{url}?sort=price">價格排序</a><a href="{url}?page=2">下一頁</a></div>
<div class="products">{products}</div>
<a href="/private/secret.html">private</a>
<footer><a href="/help/faq">FAQ</a></footer></body></html>"""
        dest = out / url.lstrip("/")
        if dest.suffix != ".html":
            dest = dest / "index.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(html, encoding="utf-8")
    for n in range(3):  # a product page that should never be crawled
        p = out / "goods" / "GoodsDetail.jsp"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("<html><body>product</body></html>", encoding="utf-8")
    (out / "index.html").write_text(f'<html><body><a href="{url_for((tree[0],), codes[(tree[0],)], False)}">{tree[0]}</a></body></html>', encoding="utf-8")


def momo_url(path, code, leaf):
    return f"/category/{code}.html"


def momo_crumbs(crumbs):
    ld = {"@context": "https://schema.org", "@type": "BreadcrumbList",
          "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n, "item": f"http://127.0.0.1:8765{u}"} for i, (n, u) in enumerate(crumbs)]}
    return f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>', ""


def pchome_url(path, code, leaf):
    return f"/store/{code}" if len(path) > 2 else f"/region/{code}"


def pchome_crumbs(crumbs):
    items = "".join(f'<li><a href="{u}">{n}</a></li>' for n, u in crumbs[:-1]) + f"<li>{crumbs[-1][0]}</li>"
    return "", f'<ol class="breadcrumb">{items}</ol>'


if __name__ == "__main__":
    build("momo", MOMO, "momo購物網", momo_url, momo_crumbs)
    build("pchome", PCHOME, "PChome 24h購物", pchome_url, pchome_crumbs)
    print("sites written to", ROOT)
