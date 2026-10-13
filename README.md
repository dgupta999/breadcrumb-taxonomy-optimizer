# Breadcrumb Taxonomy Optimizer

An internal SEO workflow tool for ecommerce category taxonomies. It:

- Maps SRPs (search result pages) to existing categories and generates their breadcrumbs.
- Audits the current category breadcrumbs.
- Crawls competitor category sections and reconstructs their hierarchy.
- Detects missing, misplaced and duplicate categories at both parent and child level, and validates them against SRP demand.
- Proposes Chinese and English breadcrumbs and shows the internal-linking impact of each change.
- Records human approvals, which override future runs.
- Exports every stage to XLSX and CSV.

```
frontend/   React + Vite + Tailwind + React Query (same stack Lovable generates)
backend/    Python FastAPI · SQLAlchemy · DB-backed job queue + worker threads
            crawler: httpx / Playwright + BeautifulSoup · openpyxl exports
supabase/   Postgres schema migration (all tables)
sample_data/  example taxonomy + SRP files (CSV + XLSX) built from the 酷澎 examples
```

## Quick start (local, SQLite, no keys needed)

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt        # macOS/Linux: .venv/bin/pip
.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173  (proxies /api → :8000)
# or: npm run build    # then the API also serves the UI at http://127.0.0.1:8000
```

Then: **Projects → New project → Upload Taxonomy** and import `sample_data/current_taxonomy.xlsx` and `sample_data/srp_data.csv`.

### Enable JavaScript rendering for MOMO / PChome

Both sites render their category pages with JavaScript. Install the Playwright browser once:

```bash
cd backend
.venv/Scripts/python -m playwright install chromium
```

Then tick **Render JavaScript** when you add the competitor. If Playwright isn't installed, the crawler falls back to plain HTTP and records a note in the job result.

### Use Supabase

1. Create a Supabase project. Run `supabase/migrations/0001_init.sql` in the SQL editor. This step is optional: the backend also creates any missing tables on startup.
2. Copy `backend/.env.example` to `backend/.env`. Set `DATABASE_URL=postgresql+psycopg://…` to the Session-pooler (port 5432) connection string.
3. Restart the API.

Row Level Security is enabled with no public policies. The browser only talks to the FastAPI backend, never directly to the tables.

### Enable the LLM fallback

Set `ANTHROPIC_API_KEY` in `backend/.env`. The default model is `claude-opus-5-5`; change it with `LLM_MODEL`. The LLM is called only for:

- SRP or competitor categories whose rule-based confidence is below 90 or that are ambiguous (top-5 candidates only; the answer is validated against those candidates, so it can't invent a category).
- Audit parents that look wrong when there is no competitor evidence.
- Missing English labels, which are marked `EN source = AI`.

The LLM never crawls, never builds breadcrumbs and never overrides a human approval. Each job is capped at `LLM_MAX_CALLS_PER_JOB` calls.

### Using it with Lovable

`frontend/` is a standard Vite + React + TypeScript + Tailwind project. To edit it in Lovable:

1. Push the repo to GitHub.
2. Import the `frontend/` folder into Lovable, or start a Lovable project and replace its `src/` with this one.
3. Set `VITE_API_URL` to the deployed backend URL, and `VITE_API_TOKEN` if you set `API_TOKEN`.

Deploy the backend (Docker, Fly, Render, a VM, etc.) with `uvicorn app.main:app`. For long crawls, also run `python -m app.worker` with `EMBEDDED_WORKER=false`.

## Recommended workflow: your own crawl files + Category Focus

1. **Upload Taxonomy**: upload the Coupang taxonomy and the SRP file.
2. **Competitors (CSV)**: type the competitor name (e.g. MOMO) and upload its crawl CSV with **URL + Breadcrumb**. No start URL or server crawling is needed. Breadcrumbs can be one `A > B > C` column or numbered `Breadcrumb 1..N` columns, and product pages are fine.
   - The comparison with Coupang and gap detection run automatically.
   - The same page shows the **gap report**: every new page to create, or existing page to move, with its Chinese and English breadcrumb in Coupang's hierarchy. A new parent is listed directly above its children.
   - **Download gaps** gives `Competitor Gaps - New Pages.csv` / `.xlsx`.
3. **Category Focus**: type a category (e.g. `滑鼠`, `網路設備`, `mouse`). You get every competitor category and URL in it, its breadcrumb, whether Coupang has it, and where each missing one fits (CN and EN breadcrumb, gap type, SRP demand). Click **XLSX** or **CSV** to download.

Sample files: `sample_data/momo_crawl_sample.csv`, `sample_data/pchome_crawl_sample.xlsx`.

**AI fallback:** set `OPENAI_API_KEY` (optional `OPENAI_MODEL`, default `gpt-4.1-mini`) or `ANTHROPIC_API_KEY`. With neither set, the tool runs on rules only.

## Workflow → where it runs

| Step | Page | Job type |
|---|---|---|
| 1–3 Upload taxonomy & SRPs, build tree | Upload Taxonomy (column-mapping screen) | `IMPORT_TAXONOMY`, `IMPORT_SRP` |
| 4, 12, 13 Breadcrumb audit, recommended architecture, linking impact | Breadcrumb Audit | `AUDIT_BREADCRUMBS` |
| 5 SRP → category mapping | SRP Mapping | `MAP_SRP` |
| 6–7 Competitor start URLs, crawl (≤1000 URLs, configurable depth) | Competitor Crawl | `CRAWL_COMPETITOR` |
| 8 Competitor trees | Competitor Taxonomy | `BUILD_COMPETITOR_TREE` (also automatic after a crawl) |
| 9 Compare | Competitor Mapping | `COMPARE_TAXONOMY` |
| 10–11 Gaps + SRP validation | Taxonomy Gaps, Parent / Child Gaps | `DETECT_GAPS` |
| 14 Human review | Review Queue (plus inline actions on every table) | — |
| 15 Exports | Exports (and on every page) | `GENERATE_EXPORT` / direct download |

Recommended order: upload → map SRPs → audit → add competitors and crawl → compare → detect gaps → **re-run the audit**, which now uses competitor evidence (e.g. 變壓器 → MOVE to 電腦配件) → review → export.

## How the engine decides

**Entity relations come first.** A mapping or a parent-child placement is made only when there is a real **is-a** relation. Product names are head-final, in both Chinese and English: the last part names the product.

| Pair | Relation | Effect |
|---|---|---|
| 無線滑鼠 → 滑鼠, 筆電充電器 → 充電器, type-c hub → USB Hubs | is-a | Match; valid child of the parent |
| 滑鼠墊 (mouse pad) → 滑鼠, 手機殼 (phone case) → 手機 | accessory-of | Never mapped to it (−40); not demand evidence for it |
| 無線滑鼠 vs 電競滑鼠 | siblings | Not parent and child |
| 筆電充電器 under 筆電配件, 手機配件 under 手機 | accessory section | Valid placement |

This rule also drives:
- **SRP demand:** an SRP counts for a category only if what it searches for *is a kind of* that category.
- **Category Focus:** only categories that are kinds of the searched category, or that sit below it in the competitor's breadcrumb, are included.
- **The breadcrumb audit:** a child that isn't a kind of its parent is flagged.

The logic lives in `backend/app/core/relations.py`.

**Entity-aware breadcrumbs.**
- **An SRP that is the same entity as its category** gets the category breadcrumb with no repeated level, e.g. `… > SSD`, not `… > SSD > SSD`. This applies to synonyms and generic-word variants such as `ssd推薦` or `電腦喇叭`, and the SRP is flagged as duplicate intent.
- **A brand, spec or attribute variant** keeps its own level, e.g. `… > SSD > 1TB SSD` or `… > 滑鼠 > 電競滑鼠`.
- **The audit moves misplaced categories up:** a category is moved up when its parent is a narrower kind of it (滑鼠 under 無線滑鼠), or when two sibling types are nested (無線滑鼠 under 電競滑鼠).
- **Category Focus on a broad category** (e.g. `3C`) covers every child category at any depth, every SRP mapped anywhere inside it, and every competitor category whose Coupang placement falls inside it, even when the competitor names its top level differently.

**Normalization.** NFKC normalization (full-width → half-width), lowercase, unified hyphens, `128 gb → 128gb`, `Wi Fi → wifi`, `micro sd → microsd`, and variant characters (`週邊 → 周邊`). The original keyword is kept for display.

**Core product extraction.** Uses a vocabulary built from category names, name parts (`網路/分享器` → `網路`, `分享器`), latin tokens, head suffixes and synonyms. The longest match that ends a segment wins (`ASUS 筆電充電器` → `筆電充電器`). Chinese is head-final, so `筆電支架` → core `支架`, modifier `筆電`. Modifiers are classified as brand, spec, attribute or generic.

**Candidate scoring.** Uses the weights from the spec:

| Signal | Points |
|---|---|
| Human-approved mapping | +150 |
| Exact normalized match | +100 |
| Exact synonym match | +90 |
| Core product exact match | +80 |
| Canonical concept match | +75 |
| Term containment | +50 |
| Shared tokens | +10 each |
| Semantic similarity | 0 to +30 |
| Depth | +2 per level |
| Very broad parent | −20 |
| Clearly wrong branch | −100 |

Section categories also get a group-category equivalence check (`網路設備 ≈ 網路/分享器`, `儲存設備 ≈ 儲存裝置`, `筆電配件 ≠ 電腦配件`). The "clearly wrong branch" penalty comes from a sense lexicon in `backend/app/core/lexicon.py`; for example, *switch* has networking and gaming senses, so `poe switch` can never map to Nintendo Switch.

**Deepest valid category.** Ancestors of a strong candidate get the broad-parent penalty, so `256gb microsd` maps to microSD, not to 記憶卡 or 儲存裝置.

**SRP breadcrumb.** The matched category's existing breadcrumb plus the SRP H1. The application builds it, not the LLM.

**Confidence bands.** 90–100 Auto Approved, 70–89 Needs Review, below 70 Low Confidence, and NO_MATCH, which sets `potential_gap`.

**Breadcrumb audit actions.**

| Action | When |
|---|---|
| FLATTEN | Duplicate or generic levels |
| MOVE | A more specific existing parent exists, or competitors / the LLM point to a better existing parent |
| MOVE + CREATE PARENT | Siblings share a product concept with no common parent (`筆電充電器/電池/包` → `筆電配件`) |
| CONSOLIDATE | Duplicate category |
| CREATE CHILD | SRP clusters show demand for a missing subtype |
| REVIEW | No safe automatic answer |

The 0–100 quality score is shown for both the current and recommended breadcrumb. It has eight components: parent relevance, specificity, duplicate levels, missing parent, depth, SRP support, competitor support and linking relevance.

**Gap types.**
- MISSING CHILD
- MISSING PARENT (reconnect the existing children)
- BOTH MISSING
- MISPLACED EXISTING CATEGORY (MOVE; never creates a duplicate page)
- DUPLICATE (consolidate / keep existing)
- SRP-ONLY GAP

**Gap scoring.**

| Signal | Points |
|---|---|
| Competitor has the category | +20 |
| Multiple competitors | +20 |
| SRPs exist | +25 |
| Strong search volume | +20 |
| Stable product type | +20 |
| Strong inventory | +15 |
| Existing equivalent | −100 |
| Temporary intent | −40 |

Priority is HIGH ≥ 70, MEDIUM ≥ 40, otherwise LOW. Competitor-only gaps with no SRP demand are always LOW and marked "MONITOR".

**Safeguards.**
- The uploaded taxonomy is never modified.
- Every recommendation stores its reason, confidence and evidence.
- Approvals are stored by breadcrumb path, so they survive taxonomy re-imports.

## Tests

```bash
cd backend
.venv/Scripts/python -m pytest -q        # 26 rule tests (normalization, extraction, deepest match,
                                         # poe switch guard, duplicates, audit actions, human override)
```

`tests/e2e_api.py` runs the whole 15-step workflow through the REST API. It uses two local fixture competitor sites (MOMO-like with JSON-LD breadcrumbs, PChome-like with HTML breadcrumbs, including product, cart, login, search and robots-blocked noise):

```bash
.venv/Scripts/python tests/fixtures/make_sites.py
.venv/Scripts/python -m http.server 8765 --directory tests/fixtures/sites/momo &
.venv/Scripts/python -m http.server 8766 --directory tests/fixtures/sites/pchome &
.venv/Scripts/python -m uvicorn app.main:app --port 8000 &
.venv/Scripts/python tests/e2e_api.py
```

## Extending domain knowledge

`backend/app/core/lexicon.py` holds:
- Default synonyms
- Generic modifiers
- Brand list
- Temporary-intent words
- Branch-conflict senses
- The EN glossary for common labels

Project-level synonyms edited on the **Synonyms** page always take precedence.

## Notes and limits

- **Crawl politeness.** The crawler fetches one URL at a time, with a default 1.5 s delay or the robots `Crawl-delay` if that is larger. A 1000-URL crawl takes about 25–40 minutes per competitor. It runs in the background and the UI polls its progress.
- **Bot protection.** Large marketplaces may block automated traffic. The crawler does not try to get around bot protection; blocked pages are recorded as errors.
- **Script coverage.** The engine targets Traditional Chinese and English. Simplified Chinese works lexically but isn't converted to Traditional.
