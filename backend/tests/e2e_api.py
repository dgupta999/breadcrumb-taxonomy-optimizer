"""End-to-end acceptance run against a live API (default http://127.0.0.1:8000).

Requires the fixture competitor sites to be served:
  python -m http.server 8765 --directory tests/fixtures/sites/momo
  python -m http.server 8766 --directory tests/fixtures/sites/pchome
"""
import os
import sys
import time
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")
API = os.getenv("API", "http://127.0.0.1:8000/api")
SAMPLES = Path(__file__).resolve().parents[2] / "sample_data"
c = httpx.Client(base_url=API, timeout=120)


def wait(job, timeout=600):
    t0 = time.time()
    while True:
        j = c.get(f"/jobs/{job['id']}").json()
        if j["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
            assert j["status"] == "COMPLETED", j
            return j
        if time.time() - t0 > timeout:
            raise TimeoutError(j)
        time.sleep(0.5)


def run(pid, job_type, params=None):
    return wait(c.post(f"/projects/{pid}/jobs", json={"job_type": job_type, "params": params or {}}).json())


def main():
    pid = c.post("/projects", json={"name": "Coupang 3C e2e", "target_category": "3C"}).json()["id"]
    for kind, fname in (("TAXONOMY", "current_taxonomy.xlsx"), ("SRP", "srp_data.csv")):
        with open(SAMPLES / fname, "rb") as f:
            up = c.post(f"/projects/{pid}/uploads", data={"kind": kind}, files={"file": (fname, f)}).json()
        print(kind, "columns:", up["columns"], "suggested:", {k: v for k, v in up["mapping"].items() if v})
        res = wait(c.post(f"/projects/{pid}/uploads/{up['id']}/commit", json={"mapping": up["mapping"]}).json())
        print(" import:", res["result"])

    print("MAP_SRP:", run(pid, "MAP_SRP")["result"])
    print("AUDIT:", run(pid, "AUDIT_BREADCRUMBS")["result"])

    for name, url in (("MOMO", "http://127.0.0.1:8765/category/C000.html"), ("PChome", "http://127.0.0.1:8766/region/C000")):
        comp = c.post(f"/projects/{pid}/competitors", json={"name": name, "start_url": url, "target_category": "3C",
                                                           "max_urls": 1000, "max_depth": 5, "crawl_delay": 0.5}).json()
        job = c.post(f"/projects/{pid}/competitors/{comp['id']}/crawl").json()
        r = wait(job)["result"]
        print(f"CRAWL {name}:", {k: r[k] for k in ("processed", "discovered", "errors", "skipped_robots")}, "tree:", r["tree"])

    print("COMPARE:", run(pid, "COMPARE_TAXONOMY")["result"])
    print("GAPS:", run(pid, "DETECT_GAPS")["result"])
    print("RE-AUDIT (with competitor evidence):", run(pid, "AUDIT_BREADCRUMBS")["result"])

    pages = c.get(f"/projects/{pid}/crawl-pages", params={"limit": 500}).json()["items"]
    bad = [p["url"] for p in pages if any(x in p["url"] for x in ("GoodsDetail", "/cart", "/login", "search", "sort=", "page=", "/private/", "/help/"))]
    print("crawled pages:", len(pages), "| unwanted URLs crawled:", bad)
    assert not bad

    maps = c.get(f"/projects/{pid}/competitor-mappings", params={"limit": 500}).json()["items"]
    for m in maps:
        if m["competitor_category"] in ("網路交換器", "PoE交換器"):
            assert m["my_category"] != "Nintendo Switch", m
    print("\nCOMPETITOR MAPPINGS")
    for m in maps:
        print(f"  {m['competitor']:7} {m['competitor_breadcrumb']:35} {m['match_type']:26} -> {m['my_category']}")

    gaps = c.get(f"/projects/{pid}/gaps", params={"limit": 500}).json()["items"]
    print("\nGAPS")
    for g in gaps:
        kids = ", ".join(f"{k['name_cn']}[{k['status']}]" for k in g["children"])
        print(f"  {g['gap_type']:28} {g['priority']:6} {g['score']:4} parent={g['parent_name_cn']}({g['parent_status']}) main={g['main_name_cn']}({g['main_status']}) "
              f"srps={g['srp_count']} vol={g['combined_search_volume']} comps={list((g['competitor_evidence'] or {}).keys())} -> {g['suggested_breadcrumb_cn']} | {g['suggested_breadcrumb_en']} | {kids} | {g['recommended_action']}")

    audits = c.get(f"/projects/{pid}/audits", params={"limit": 500, "action": "MOVE,FLATTEN,MOVE + CREATE PARENT,CONSOLIDATE,REVIEW,CREATE CHILD"}).json()["items"]
    print("\nAUDIT (non-KEEP)")
    for a in audits:
        print(f"  {a['category_name']:10} {a['action']:22} {a['current_score']}->{a['recommended_score']} {a['linking_improvement']:6} {a['recommended_breadcrumb_cn']} | {a['linking_explanation']}")
    t = next(a for a in audits if a["category_name"] == "變壓器")
    assert t["action"] == "MOVE" and "電腦配件" in t["recommended_breadcrumb_cn"], t

    # --- human review
    srps = c.get(f"/projects/{pid}/srps", params={"limit": 500}).json()["items"]
    s = next(x for x in srps if x["keyword"] == "wifi分享器")
    nodes = c.get(f"/projects/{pid}/categories", params={"limit": 500, "q": "網路/分享器"}).json()["items"]
    r = c.post(f"/projects/{pid}/review", json={"entity_type": "srp", "entity_ids": [s["id"]], "action": "CHANGE_CATEGORY",
                                               "payload": {"node_id": nodes[0]["id"]}, "reviewer": "e2e"}).json()
    print("\nreview:", r)
    c.post(f"/projects/{pid}/review", json={"entity_type": "audit", "entity_ids": [t["id"]], "action": "APPROVE", "reviewer": "e2e"})
    hp = [g for g in gaps if g["gap_type"] in ("MISSING PARENT", "MISSING CHILD", "BOTH MISSING") and g["priority"] in ("HIGH", "MEDIUM")]
    c.post(f"/projects/{pid}/review", json={"entity_type": "gap", "entity_ids": [g["id"] for g in hp], "action": "APPROVE", "reviewer": "e2e"})
    # human mapping survives re-run
    run(pid, "MAP_SRP")
    s2 = c.get(f"/projects/{pid}/srps", params={"q": "wifi分享器"}).json()["items"][0]
    assert s2["review_status"] == "APPROVED" and s2["match_method"] == "HUMAN", s2
    print("human override persisted after re-run:", s2["matched_category"], s2["breadcrumb_cn"])
    print("rules:", c.get(f"/projects/{pid}/approved-rules").json()["total"])

    # --- exports
    out = Path(os.getenv("EXPORT_DIR", "e2e_exports"))
    out.mkdir(exist_ok=True)
    for e in c.get("/exports").json():
        for fmt in ("xlsx", "csv"):
            r = c.get(f"/projects/{pid}/exports/{e['key']}", params={"format": fmt})
            assert r.status_code == 200, (e, r.text[:200])
            (out / f"{e['number']:02d} {e['title']}.{fmt}").write_bytes(r.content)
    print("exports written:", len(list(out.iterdir())))
    d = c.get(f"/projects/{pid}/dashboard").json()
    print("steps done:", [s["step"] for s in d["steps"] if s["done"]])


if __name__ == "__main__":
    main()
