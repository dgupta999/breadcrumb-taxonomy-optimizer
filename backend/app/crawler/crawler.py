"""Polite BFS crawler for competitor category sections.

- stays on the start URL's host, begins only from the start URL
- obeys robots.txt (and its Crawl-delay), one request at a time
- retries transient failures with backoff
- prefers taxonomy URLs; skips products, cart/account, search/sort/filter URLs
- persists every page + progress so the UI can poll it
"""
from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Callable
from urllib import robotparser
from urllib.parse import urlsplit

import httpx
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Competitor, CrawlJob, CrawlPage
from .classify import classify, strip_home
from .extract import extract
from .urls import UrlFilter, is_product_url, looks_like_category_url, normalize_url

log = logging.getLogger(__name__)


class Cancelled(Exception):
    pass


class Fetcher:
    def __init__(self, render_js: bool):
        self.client = httpx.Client(
            headers={"User-Agent": settings.crawl_user_agent, "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"},
            timeout=settings.crawl_timeout_seconds,
            follow_redirects=True,
        )
        self.render_js = render_js
        self._pw = None
        self._browser = None
        self.js_error: str | None = None
        if render_js:
            try:
                from playwright.sync_api import sync_playwright

                self._pw = sync_playwright().start()
                self._browser = self._pw.chromium.launch(headless=True)
                self._ctx = self._browser.new_context(user_agent=settings.crawl_user_agent, locale="zh-TW")
            except Exception as e:  # browsers not installed etc.
                self.js_error = f"Playwright unavailable ({e.__class__.__name__}); falling back to plain HTTP"
                log.warning(self.js_error)
                self.render_js = False
                self.close_browser()

    def get_text(self, url: str) -> tuple[int, str, dict]:
        r = self.client.get(url)
        return r.status_code, r.text, dict(r.headers)

    def fetch(self, url: str) -> tuple[int, str, dict, str]:
        """Return (status, html, headers, final_url)."""
        if self.render_js and self._browser is not None:
            page = self._ctx.new_page()
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=settings.crawl_timeout_seconds * 1000)
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                html = page.content()
                status = resp.status if resp else 0
                headers = resp.headers if resp else {}
                return status, html, headers, page.url
            finally:
                page.close()
        r = self.client.get(url)
        ctype = r.headers.get("content-type", "")
        html = r.text if ("html" in ctype or not ctype) else ""
        return r.status_code, html, dict(r.headers), str(r.url)

    def close_browser(self):
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._browser = self._pw = None

    def close(self):
        self.close_browser()
        self.client.close()


def _robots(fetcher: Fetcher, start_url: str) -> tuple[robotparser.RobotFileParser, float | None]:
    parts = urlsplit(start_url)
    rp = robotparser.RobotFileParser()
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        code, text, _ = fetcher.get_text(robots_url)
        if code >= 500:
            rp.parse(["User-agent: *", "Disallow: /"])
        elif code >= 400:
            rp.parse([])
        else:
            rp.parse(text.splitlines())
    except httpx.HTTPError:
        rp.parse([])
    delay = rp.crawl_delay(settings.crawl_user_agent) or rp.crawl_delay("*")
    return rp, float(delay) if delay else None


def _indexability(status: int, pd, headers: dict, url: str) -> str:
    if status and status >= 300:
        return f"Non-indexable: HTTP {status}"
    xr = (headers.get("x-robots-tag") or headers.get("X-Robots-Tag") or "").lower()
    if "noindex" in (pd.meta_robots or "") or "noindex" in xr:
        return "Non-indexable: noindex"
    if pd.canonical and pd.canonical.rstrip("/") != url.rstrip("/"):
        return "Non-indexable: canonicalized"
    return "Indexable"


def crawl_competitor(
    db: Session,
    competitor: Competitor,
    crawl_job: CrawlJob,
    progress: Callable[[int, int, str | None], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> dict:
    flt = UrlFilter(competitor.start_url, competitor.include_patterns or [], competitor.exclude_patterns or [])
    fetcher = Fetcher(render_js=competitor.render_js)
    notes: list[str] = []
    if fetcher.js_error:
        notes.append(fetcher.js_error)
    start = normalize_url(competitor.start_url, keep_params=flt.keep_params)
    rp, robots_delay = _robots(fetcher, start)
    delay = max(competitor.crawl_delay or settings.crawl_delay_seconds, robots_delay or 0)
    max_urls = max(1, min(competitor.max_urls or 1000, 5000))
    max_depth = max(0, competitor.max_depth if competitor.max_depth is not None else 5)

    queue: deque[tuple[str, int, str | None, str | None]] = deque([(start, 0, None, None)])
    seen: set[str] = {start}
    processed = errors = skipped_robots = 0
    crawl_job.status, crawl_job.started_at = "RUNNING", datetime.now(timezone.utc)
    db.commit()

    try:
        while queue and processed < max_urls:
            if should_cancel and should_cancel():
                raise Cancelled()
            url, depth, parent_url, anchor = queue.popleft()
            if not rp.can_fetch(settings.crawl_user_agent, url):
                skipped_robots += 1
                db.add(CrawlPage(project_id=competitor.project_id, crawl_job_id=crawl_job.id, competitor_id=competitor.id,
                                 url=url, depth=depth, parent_url=parent_url, anchor_text=anchor, page_type="BLOCKED",
                                 error="Disallowed by robots.txt"))
                continue
            status, html, headers, final_url, err = 0, "", {}, url, None
            for attempt in range(settings.crawl_max_retries + 1):
                try:
                    status, html, headers, final_url = fetcher.fetch(url)
                    if status in (429, 500, 502, 503, 504) and attempt < settings.crawl_max_retries:
                        time.sleep(delay * (2 ** (attempt + 1)))
                        continue
                    err = None
                    break
                except Exception as e:  # network / timeout / browser errors
                    err = f"{e.__class__.__name__}: {str(e)[:200]}"
                    if attempt < settings.crawl_max_retries:
                        time.sleep(delay * (2 ** (attempt + 1)))
            processed += 1
            page = CrawlPage(project_id=competitor.project_id, crawl_job_id=crawl_job.id, competitor_id=competitor.id,
                             url=url, status_code=status or None, depth=depth, parent_url=parent_url, anchor_text=anchor)
            if err or not html:
                errors += 1 if err or status >= 400 else 0
                page.error = err or (f"HTTP {status}" if status >= 400 else "non-HTML response")
                page.page_type = "UNKNOWN"
            else:
                final = normalize_url(final_url, keep_params=flt.keep_params) or url
                pd = extract(html, final)
                crumb_urls = {c["url"] for c in pd.breadcrumb if c.get("url")}
                child_links = []
                for l in pd.links:
                    u = l["url"]
                    if u in (url, final, parent_url) or u in crumb_urls or is_product_url(u):
                        continue
                    ok, _ = flt.decision(u)
                    if ok and (looks_like_category_url(u) or flt.include):
                        child_links.append(l)
                body_children = [l for l in child_links if l["zone"] in ("body", "category_nav")]
                ptype, conf, signals = classify(final, pd, len(body_children))
                crumbs = strip_home(pd.breadcrumb)
                page.url = final
                page.canonical = pd.canonical
                page.indexability = _indexability(status, pd, headers, final)
                page.title, page.h1 = pd.title, pd.h1
                page.breadcrumb = pd.breadcrumb
                page.breadcrumb_text = " > ".join(c["name"] for c in pd.breadcrumb) or None
                page.internal_links_count = sum(1 for l in pd.links if flt.same_site(l["url"]))
                page.child_category_links = [{"url": l["url"], "text": l["text"], "zone": l["zone"]} for l in body_children[:300]]
                page.product_link_count = max(pd.product_link_count, pd.item_list_count)
                page.page_type, page.category_confidence = ptype, round(conf, 2)
                page.category_name = (crumbs[-1]["name"] if crumbs else None) or pd.h1 or anchor or pd.title
                page.error = None if status < 400 else f"HTTP {status}"
                if status >= 400:
                    errors += 1
                if final != url:
                    seen.add(final)
                if depth < max_depth and (depth == 0 or ptype in ("CATEGORY", "SUBCATEGORY", "UNKNOWN")):
                    for l in sorted(child_links, key=lambda l: 0 if l["zone"] in ("body", "category_nav") else 1):
                        if l["url"] not in seen:
                            seen.add(l["url"])
                            queue.append((l["url"], depth + 1, final, l["text"] or None))
            db.add(page)
            crawl_job.processed_urls, crawl_job.discovered_urls = processed, len(seen)
            crawl_job.error_count, crawl_job.skipped_robots = errors, skipped_robots
            db.commit()
            if progress:
                progress(processed, min(max_urls, len(seen)), f"{competitor.name}: {processed} processed, {len(seen)} discovered, {errors} errors")
            if queue and processed < max_urls:
                time.sleep(delay)
        crawl_job.status = "COMPLETED"
    except Cancelled:
        crawl_job.status = "CANCELLED"
        notes.append("cancelled by user")
    finally:
        crawl_job.completed_at = datetime.now(timezone.utc)
        crawl_job.processed_urls, crawl_job.discovered_urls = processed, len(seen)
        crawl_job.error_count, crawl_job.skipped_robots = errors, skipped_robots
        db.commit()
        fetcher.close()
    return {"competitor": competitor.name, "processed": processed, "discovered": len(seen), "errors": errors,
            "skipped_robots": skipped_robots, "render_js": fetcher.render_js, "delay_seconds": delay, "notes": notes,
            "status": crawl_job.status}
