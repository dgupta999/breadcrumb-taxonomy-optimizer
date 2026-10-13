"""Sample competitor crawl exports (what you'd export from Screaming Frog).

momo_crawl_sample.csv     — 'Address, Status Code, Title 1, H1-1, Breadcrumb 1..N' (numbered columns)
pchome_crawl_sample.xlsx  — 'URL, Breadcrumb, H1, Title' (single 'A > B > C' column)
Both include product pages whose breadcrumbs end with the product name.
"""
import csv
import sys
from pathlib import Path

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures"))
from make_sites import MOMO, PCHOME, walk  # noqa: E402

OUT = Path(__file__).parent


def rows_for(tree, home, base, cat_url, prod_url):
    rows = []
    for i, (path, kids) in enumerate(walk(tree)):
        rows.append({"url": base + cat_url(i), "crumbs": [home, *path], "h1": path[-1], "title": f"{path[-1]} | {home}", "status": 200})
        if not kids:  # two products per leaf category
            for n in range(2):
                name = f"{path[-1]} 熱銷款 {n + 1}"
                rows.append({"url": base + prod_url(i, n), "crumbs": [home, *path, name], "h1": name, "title": name, "status": 200})
    return rows


momo = rows_for(MOMO, "momo購物網", "https://www.momoshop.com.tw",
                lambda i: f"/category/DgrpCategory.jsp?d_code={4000000000 + i}",
                lambda i, n: f"/goods/GoodsDetail.jsp?i_code={10000000 + i * 10 + n}")
depth = max(len(r["crumbs"]) for r in momo)
with open(OUT / "momo_crawl_sample.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["Address", "Status Code", "Title 1", "H1-1"] + [f"Breadcrumb {i + 1}" for i in range(depth)])
    for r in momo:
        w.writerow([r["url"], r["status"], r["title"], r["h1"]] + r["crumbs"] + [""] * (depth - len(r["crumbs"])))

pchome = rows_for(PCHOME, "PChome 24h購物", "https://24h.pchome.com.tw",
                  lambda i: f"/store/DCAX{i:02d}" if i else "/region/DCAX",
                  lambda i, n: f"/prod/DCAX{i:02d}-A900{n}XYZ")
wb = Workbook()
ws = wb.active
ws.append(["URL", "Breadcrumb", "H1", "Title", "Status Code"])
for r in pchome:
    ws.append([r["url"], " > ".join(r["crumbs"]), r["h1"], r["title"], r["status"]])
wb.save(OUT / "pchome_crawl_sample.xlsx")
print(len(momo), "MOMO rows,", len(pchome), "PChome rows")
