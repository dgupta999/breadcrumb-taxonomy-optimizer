import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Plus, Square, Trash2 } from "lucide-react";
import { api, type Paged } from "@/lib/api";
import type { Competitor, CrawlPage } from "@/lib/types";
import { useProject } from "@/lib/project";
import { DataTable, ExportButtons, FilterChips, NeedProject, Pager, SearchBox } from "@/components/common";
import { JobProgress } from "@/components/jobs";
import { Button, Card, Input, Label, PageHeader, Select, StatusBadge, Textarea } from "@/components/ui";
import { Uploader } from "./Upload";

const TYPES = ["CATEGORY", "SUBCATEGORY", "PRODUCT", "SRP", "FILTER", "CAMPAIGN", "CONTENT", "UNKNOWN", "BLOCKED"];
const EMPTY = { name: "", start_url: "", target_category: "3C", max_urls: "1000", max_depth: "5", include: "", exclude: "", render_js: false, crawl_delay: "1.5" };

export default function CrawlPageView() {
  const { projectId } = useProject();
  const qc = useQueryClient();
  const [form, setForm] = useState(EMPTY);
  const [err, setErr] = useState<string | null>(null);
  const comps = useQuery({
    queryKey: ["competitors", projectId],
    queryFn: () => api.get<Competitor[]>(`/projects/${projectId}/competitors`),
    enabled: !!projectId,
    refetchInterval: (q) => (q.state.data?.some((c) => ["QUEUED", "RUNNING", "CANCEL_REQUESTED"].includes(c.last_job?.status || "")) ? 2000 : false),
  });
  const [compFilter, setCompFilter] = useState<string>("");
  const [upComp, setUpComp] = useState<string>("");
  const [append, setAppend] = useState(false);
  const [types, setTypes] = useState<string[]>([]);
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const pages = useQuery({
    queryKey: ["crawl-pages", projectId, compFilter, types, q, offset],
    queryFn: () => api.get<Paged<CrawlPage>>(`/projects/${projectId}/crawl-pages`, { competitor_id: compFilter || undefined, page_type: types, q, offset, limit: 100 }),
    enabled: !!projectId,
    refetchInterval: (q) => (comps.data?.some((c) => ["QUEUED", "RUNNING"].includes(c.last_job?.status || "")) ? 4000 : false),
  });

  const add = async () => {
    setErr(null);
    try {
      await api.post(`/projects/${projectId}/competitors`, {
        name: form.name,
        start_url: form.start_url,
        target_category: form.target_category,
        max_urls: Number(form.max_urls),
        max_depth: Number(form.max_depth),
        include_patterns: form.include.split("\n").map((s) => s.trim()).filter(Boolean),
        exclude_patterns: form.exclude.split("\n").map((s) => s.trim()).filter(Boolean),
        render_js: form.render_js,
        crawl_delay: Number(form.crawl_delay) || null,
      });
      setForm(EMPTY);
      qc.invalidateQueries({ queryKey: ["competitors"] });
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const crawl = async (c: Competitor) => {
    try {
      await api.post(`/projects/${projectId}/competitors/${c.id}/crawl`);
    } catch (e) {
      alert((e as Error).message);
    }
    qc.invalidateQueries({ queryKey: ["competitors"] });
  };
  const remove = async (c: Competitor) => {
    if (!confirm(`Delete competitor ${c.name} and its crawl data?`)) return;
    await api.del(`/projects/${projectId}/competitors/${c.id}`);
    qc.invalidateQueries({ queryKey: ["competitors"] });
  };

  return (
    <NeedProject>
      <PageHeader
        step="Steps 6–7"
        title="Competitor crawl"
        description="Crawls run in a background worker: same host only, start URL only, robots.txt respected, polite delay, retries, deduplication. Product, cart, checkout, login, account, tracking, sort/filter/search and campaign URLs are skipped."
      />
      <div className="mb-5">
        <Uploader
          kind="COMPETITOR_CRAWL"
          title="Upload a competitor crawl file (recommended)"
          description="Export from Screaming Frog / Sitebulb / any crawler as CSV or XLSX. Needed: URL + Breadcrumb (one 'A > B > C' column or Breadcrumb 1, 2, 3… columns). H1, Title, Status Code, Canonical optional. Product pages are fine — their breadcrumbs reveal category paths. After import the competitor tree, comparison and gap detection run automatically."
          extra={{ competitor_id: upComp ? Number(upComp) : null, append }}
          blockedReason={upComp ? null : "Choose the competitor first"}
        >
          <div className="mb-3 flex flex-wrap items-end gap-3">
            <div>
              <Label required>Competitor</Label>
              <Select value={upComp} onChange={(e) => setUpComp(e.target.value)}>
                <option value="">Choose…</option>
                {comps.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </Select>
            </div>
            <label className="flex items-center gap-2 pb-2 text-xs text-slate-600">
              <input type="checkbox" checked={append} onChange={(e) => setAppend(e.target.checked)} />
              Append to this competitor's previous file (crawl split over several exports)
            </label>
            {comps.data?.length === 0 && <span className="pb-2 text-xs text-amber-700">Add the competitor (name + any start URL) in the form below first.</span>}
          </div>
        </Uploader>
      </div>
      <div className="grid gap-5 xl:grid-cols-3">
        <Card title="Add competitor (optional server crawl)" subtitle="Name + start URL. Use 'Start crawl' only if you want the server to crawl; with an uploaded file you can skip it." className="xl:col-span-1">
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <div><Label required>Competitor name</Label><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="MOMO" /></div>
              <div><Label>Target category</Label><Input value={form.target_category} onChange={(e) => setForm({ ...form, target_category: e.target.value })} /></div>
            </div>
            <div><Label required>Start URL</Label><Input value={form.start_url} onChange={(e) => setForm({ ...form, start_url: e.target.value })} placeholder="https://www.momoshop.com.tw/category/LgrpCategory.jsp?l_code=…" /></div>
            <div className="grid grid-cols-3 gap-2">
              <div><Label>Max URLs</Label><Input type="number" value={form.max_urls} onChange={(e) => setForm({ ...form, max_urls: e.target.value })} /></div>
              <div><Label>Max depth</Label><Input type="number" value={form.max_depth} onChange={(e) => setForm({ ...form, max_depth: e.target.value })} /></div>
              <div><Label>Delay (s)</Label><Input type="number" step="0.5" value={form.crawl_delay} onChange={(e) => setForm({ ...form, crawl_delay: e.target.value })} /></div>
            </div>
            <div><Label>Include URL patterns (regex, one per line)</Label><Textarea rows={2} value={form.include} onChange={(e) => setForm({ ...form, include: e.target.value })} placeholder="/category/" /></div>
            <div><Label>Exclude URL patterns (regex, one per line)</Label><Textarea rows={2} value={form.exclude} onChange={(e) => setForm({ ...form, exclude: e.target.value })} placeholder="/brand/" /></div>
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input type="checkbox" checked={form.render_js} onChange={(e) => setForm({ ...form, render_js: e.target.checked })} />
              Render JavaScript with Playwright (needed for MOMO / PChome)
            </label>
            {err && <div className="text-xs text-rose-600">{err}</div>}
            <Button onClick={add} disabled={!form.name || !form.start_url}><Plus size={14} /> Add competitor</Button>
          </div>
        </Card>
        <Card title="Competitors" className="xl:col-span-2" actions={<ExportButtons exportKey="competitor_crawl_raw" label="Raw crawl" />}>
          <div className="space-y-3">
            {comps.data?.length === 0 && <div className="text-sm text-slate-500">No competitors yet.</div>}
            {comps.data?.map((c) => {
              const running = ["QUEUED", "RUNNING", "CANCEL_REQUESTED"].includes(c.last_job?.status || "");
              return (
                <div key={c.id} className="rounded-lg border border-slate-200 p-3">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <div className="flex items-center gap-2 text-sm font-semibold">{c.name} <StatusBadge value={c.last_crawl?.status || c.status} /></div>
                      <div className="break-all text-xs text-slate-500">{c.start_url}</div>
                      <div className="mt-0.5 text-[11px] text-slate-400">
                        max {c.max_urls} URLs · depth {c.max_depth} · {c.render_js ? "JS rendering" : "plain HTTP"} · {c.categories} categories in tree
                      </div>
                    </div>
                    <div className="flex gap-1.5">
                      {running ? (
                        <Button variant="outline" size="sm" onClick={() => c.last_job && api.post(`/jobs/${c.last_job.id}/cancel`).then(() => qc.invalidateQueries())}><Square size={12} /> Stop</Button>
                      ) : (
                        <Button size="sm" onClick={() => crawl(c)}><Play size={12} /> {c.last_crawl ? "Re-crawl" : "Start crawl"}</Button>
                      )}
                      <Button variant="ghost" size="sm" onClick={() => remove(c)}><Trash2 size={13} /></Button>
                    </div>
                  </div>
                  {c.last_job && (
                    <div className="mt-2">
                      <JobProgress job={{ ...c.last_job, crawl: c.last_crawl ? { processed_urls: c.last_crawl.processed_urls, discovered_urls: c.last_crawl.discovered_urls, error_count: c.last_crawl.error_count, skipped_robots: c.last_crawl.skipped_robots, status: c.last_crawl.status } : undefined }} compact />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </Card>
      </div>
      <Card className="mt-5" title="Crawled pages" subtitle="Only CATEGORY and SUBCATEGORY pages feed the competitor taxonomy." actions={<ExportButtons exportKey="competitor_clean_categories" label="Clean categories" />}>
        <div className="mb-3 flex flex-wrap items-center gap-x-5 gap-y-2">
          <SearchBox value={q} onChange={(v) => { setQ(v); setOffset(0); }} placeholder="Search URL / title / breadcrumb…" />
          <Select value={compFilter} onChange={(e) => { setCompFilter(e.target.value); setOffset(0); }}>
            <option value="">All competitors</option>
            {comps.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </Select>
          <FilterChips label="Page type" options={TYPES} value={types} onChange={(v) => { setTypes(v); setOffset(0); }} />
          {pages.data && <Pager total={pages.data.total} limit={pages.data.limit} offset={offset} onChange={setOffset} />}
        </div>
        <DataTable
          rows={pages.data?.items || []}
          loading={pages.isLoading}
          expand={(p) => (
            <div className="grid gap-3 text-xs md:grid-cols-2">
              <div className="space-y-0.5">
                <div><span className="text-slate-500">Canonical:</span> {p.canonical || "—"}</div>
                <div><span className="text-slate-500">Parent URL:</span> {p.parent_url || "—"}</div>
                <div><span className="text-slate-500">Anchor from parent:</span> {p.anchor_text || "—"}</div>
                <div><span className="text-slate-500">Title:</span> {p.title}</div>
                {p.error && <div className="text-rose-600">{p.error}</div>}
              </div>
              <div>
                <div className="mb-1 text-slate-500">Child category links ({p.child_category_links.length})</div>
                <div className="flex flex-wrap gap-1">{p.child_category_links.slice(0, 40).map((l) => <span key={l.url} className="rounded bg-white px-1.5 py-0.5 ring-1 ring-slate-200">{l.text || l.url}</span>)}</div>
              </div>
            </div>
          )}
          columns={[
            { key: "u", header: "URL", className: "max-w-[360px]", render: (p) => <a href={p.url} target="_blank" rel="noreferrer" className="break-all text-xs text-indigo-600 hover:underline">{p.url}</a> },
            { key: "s", header: "Status", render: (p) => <span className="tabular-nums text-xs">{p.status_code ?? "—"}</span> },
            { key: "t", header: "Type", render: (p) => <StatusBadge value={p.page_type} /> },
            { key: "h", header: "H1 / category", render: (p) => <span className="text-sm">{p.category_name || p.h1}</span> },
            { key: "b", header: "Breadcrumb", className: "min-w-[220px]", render: (p) => <span className="text-xs text-slate-600">{p.breadcrumb_text || "—"}</span> },
            { key: "d", header: "Depth", render: (p) => p.depth },
            { key: "i", header: "Indexability", render: (p) => <span className="text-xs">{p.indexability || "—"}</span> },
            { key: "c", header: "Cat. conf.", render: (p) => <span className="tabular-nums text-xs">{p.category_confidence ?? "—"}</span> },
          ]}
        />
      </Card>
    </NeedProject>
  );
}
