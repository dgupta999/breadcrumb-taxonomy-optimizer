"""E2E for the 'upload your own crawl → Category Focus' workflow against a live API."""
import os
import sys
import time
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")
API = os.getenv("API", "http://127.0.0.1:8000/api")
SAMPLES = Path(__file__).resolve().parents[2] / "sample_data"
c = httpx.Client(base_url=API, timeout=120)


def idle(pid, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        jobs = c.get(f"/projects/{pid}/jobs", params={"limit": 50}).json()["items"]
        failed = [j for j in jobs if j["status"] == "FAILED"]
        assert not failed, failed[0]["error_message"]
        if not any(j["status"] in ("QUEUED", "RUNNING") for j in jobs):
            return jobs
        time.sleep(0.7)
    raise TimeoutError


def upload(pid, kind, fname, **extra):
    with open(SAMPLES / fname, "rb") as f:
        up = c.post(f"/projects/{pid}/uploads", data={"kind": kind}, files={"file": (fname, f)}).json()
    r = c.post(f"/projects/{pid}/uploads/{up['id']}/commit", json={"mapping": up["mapping"], **extra})
    assert r.status_code == 200, r.text
    return up


pid = c.post("/projects", json={"name": "Focus e2e"}).json()["id"]
upload(pid, "TAXONOMY", "current_taxonomy.xlsx")
upload(pid, "SRP", "srp_data.csv", then=[{"job_type": "MAP_SRP"}])
idle(pid)
for name, url, f in (("MOMO", "https://www.momoshop.com.tw/", "momo_crawl_sample.csv"), ("PChome", "https://24h.pchome.com.tw/", "pchome_crawl_sample.xlsx")):
    up = upload(pid, "COMPETITOR_CRAWL", f, competitor_name=name)  # competitor created from the name
    print(name, "mapping:", {k: v for k, v in up["mapping"].items() if v})
    idle(pid)
jobs = idle(pid)
for j in jobs:
    if j["job_type"] == "IMPORT_COMPETITOR_CRAWL":
        print(" import:", c.get(f"/jobs/{j['id']}").json()["result"])

for term in ("滑鼠", "網路設備", "筆電配件", "顯示卡", "mouse"):
    res = c.get(f"/projects/{pid}/category-focus", params={"category": term}).json()
    print(f"\n=== {term}  summary={res['summary']}  urls={res['url_counts']}  coupang_focus={[n['breadcrumb_cn'] for n in res['coupang_focus']][:2]}")
    for r in res["rows"]:
        where = r["coupang_breadcrumb_cn"] if r["status"].startswith("PRESENT") else r["suggested_breadcrumb_cn"]
        print(f"  {r['competitor']:6} {r['competitor_breadcrumb']:32} {r['status']:20} -> {where} | {r['suggested_breadcrumb_en'] or ''} | {r['recommended_action'] or ''}")

r = c.get(f"/projects/{pid}/category-focus", params={"category": "滑鼠", "format": "xlsx"})
assert r.status_code == 200 and r.content[:2] == b"PK"
print("\nxlsx export ok", len(r.content), "bytes")

r = c.get(f"/projects/{pid}/exports/competitor_gap_pages", params={"format": "csv"})
assert r.status_code == 200
print("--- Competitor Gaps - New Pages.csv ---")
import csv, io
rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
h = rows[0]
for row in rows[1:]:
    d = dict(zip(h, row))
    print(f"{d['Priority']:6} {d['Gap Type']:28} {d['Page Level']:13} {d['New / Changed Page CN']:10} {d['Page Status']:16} {d['Suggested Breadcrumb CN']}  [{d['Competitors']}] vol={d['Search Volume']}")
comps = c.get(f"/projects/{pid}/competitors").json()
print("competitors:", [(x["name"], x["start_url"]) for x in comps])
