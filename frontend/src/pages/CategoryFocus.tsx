import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, FileSpreadsheet, Search } from "lucide-react";
import { api } from "@/lib/api";
import type { Competitor } from "@/lib/types";
import { useProject } from "@/lib/project";
import { DataTable, FilterChips, NeedProject } from "@/components/common";
import { Badge, Button, Card, Crumb, Empty, Input, PageHeader, Spinner, Stat, StatusBadge } from "@/components/ui";

type Row = {
  competitor: string;
  competitor_category: string;
  competitor_breadcrumb: string;
  competitor_url?: string | null;
  status: string;
  classification?: string | null;
  coupang_category?: string | null;
  coupang_url?: string | null;
  coupang_breadcrumb_cn?: string | null;
  coupang_breadcrumb_en?: string | null;
  suggested_parent?: string | null;
  suggested_parent_status?: string | null;
  suggested_breadcrumb_cn?: string | null;
  suggested_breadcrumb_en?: string | null;
  gap_type?: string | null;
  recommended_action?: string | null;
  supporting_srps: { keyword: string; search_volume?: number | null }[];
  srp_count: number;
  search_volume: number;
  products_seen: number;
  reason?: string | null;
  confidence?: number | null;
};
type Focus = {
  category: string;
  match_keys: string[];
  coupang_focus: { id: number; name: string; breadcrumb_cn: string }[];
  summary: Record<string, number>;
  url_counts: Record<string, number>;
  unmapped: number;
  rows: Row[];
  urls: { competitor: string; url: string; page_type: string; breadcrumb?: string | null; h1?: string | null; status_code?: number | null }[];
  coupang_categories: { category: string; name_en?: string | null; breadcrumb_cn: string; url?: string | null; competitors_with_it: string[] }[];
};

const STATUS_TONE: Record<string, string> = { PRESENT: "green", "PRESENT (BROADER)": "blue", "PRESENT (MISPLACED)": "amber", MISSING: "red", REVIEW: "amber", "NOT COMPARED": "gray" };

export default function CategoryFocus() {
  const { projectId } = useProject();
  const comps = useQuery({ queryKey: ["competitors", projectId], queryFn: () => api.get<Competitor[]>(`/projects/${projectId}/competitors`), enabled: !!projectId });
  const [input, setInput] = useState("");
  const [term, setTerm] = useState("");
  const [compSel, setCompSel] = useState<string[]>([]);
  const [statusSel, setStatusSel] = useState<string[]>([]);
  const [tab, setTab] = useState<"categories" | "urls" | "coupang">("categories");
  const compIds = (comps.data || []).filter((c) => compSel.includes(c.name)).map((c) => c.id);
  const { data, isFetching, error } = useQuery({
    queryKey: ["focus", projectId, term, compIds],
    queryFn: () => api.get<Focus>(`/projects/${projectId}/category-focus`, { category: term, competitor_id: compIds }),
    enabled: !!projectId && !!term,
  });
  const rows = (data?.rows || []).filter((r) => !statusSel.length || statusSel.includes(r.status)).map((r, i) => ({ ...r, id: i + 1 }));
  const dl = (format: "xlsx" | "csv") => api.download(`/projects/${projectId}/category-focus`, { category: term, competitor_id: compIds, format });

  return (
    <NeedProject>
      <PageHeader
        title="Category focus"
        description="Type one category (Chinese or English, e.g. 滑鼠, 電腦周邊, 網路設備, mouse). You get every competitor category and URL inside it, its breadcrumb, whether Coupang already has it, and — if missing — where it fits in the current Coupang taxonomy."
      />
      <Card>
        <form
          className="flex flex-wrap items-center gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            setTerm(input.trim());
          }}
        >
          <div className="relative w-80">
            <Search size={15} className="absolute left-3 top-2.5 text-slate-400" />
            <Input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Category name, e.g. 滑鼠" className="pl-9" />
          </div>
          <Button type="submit" disabled={!input.trim()}>
            {isFetching ? <Spinner /> : <Search size={14} />} Analyze
          </Button>
          {!!comps.data?.length && <FilterChips label="Competitors" options={comps.data.map((c) => c.name)} value={compSel} onChange={setCompSel} />}
          {data && (
            <div className="ml-auto flex gap-1.5">
              <Button variant="outline" size="sm" onClick={() => dl("xlsx")}><FileSpreadsheet size={13} className="text-emerald-600" /> XLSX</Button>
              <Button variant="outline" size="sm" onClick={() => dl("csv")}><Download size={13} /> CSV</Button>
            </div>
          )}
        </form>
        {error && <div className="mt-3 text-sm text-rose-600">{(error as Error).message}</div>}
      </Card>

      {!term && <div className="mt-5"><Empty>Upload competitor crawl files on <b>Competitor Crawl</b>, then type a category above.</Empty></div>}

      {data && (
        <div className="mt-5 space-y-5">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <Stat label="Competitor categories" value={data.rows.length} hint={`matched on: ${data.match_keys.slice(0, 4).join(", ")}`} />
            <Stat label="Present in Coupang" value={(data.summary.PRESENT || 0) + (data.summary["PRESENT (BROADER)"] || 0)} tone="text-emerald-600" />
            <Stat label="Missing in Coupang" value={data.summary.MISSING || 0} tone="text-rose-600" />
            <Stat label="Misplaced / review" value={(data.summary["PRESENT (MISPLACED)"] || 0) + (data.summary.REVIEW || 0)} tone="text-amber-600" />
            <Stat label="Competitor URLs" value={data.urls.length} hint={Object.entries(data.url_counts).map(([k, v]) => `${k.toLowerCase()} ${v}`).join(" · ")} />
          </div>
          <div className="text-xs text-slate-600">
            Coupang focus: {data.coupang_focus.length ? data.coupang_focus.map((n) => <Badge key={n.id} tone="indigo" className="mr-1">{n.breadcrumb_cn}</Badge>) : <span className="text-amber-700">no Coupang category matches “{data.category}” — missing items are placed by their competitor parent</span>}
            {data.unmapped > 0 && <span className="ml-2 text-amber-700">{data.unmapped} competitor categories not compared yet — run Compare on Competitor Mapping.</span>}
          </div>

          <div className="flex gap-1 rounded-lg bg-slate-100 p-1 text-sm">
            {([["categories", `Competitor categories (${data.rows.length})`], ["urls", `Competitor URLs (${data.urls.length})`], ["coupang", `Coupang categories (${data.coupang_categories.length})`]] as const).map(([k, l]) => (
              <button key={k} onClick={() => setTab(k)} className={`rounded-md px-3 py-1.5 ${tab === k ? "bg-white font-medium shadow-sm" : "text-slate-600"}`}>{l}</button>
            ))}
          </div>

          {tab === "categories" && (
            <Card>
              <div className="mb-3">
                <FilterChips label="Status" options={["PRESENT", "PRESENT (BROADER)", "PRESENT (MISPLACED)", "MISSING", "REVIEW"]} value={statusSel} onChange={setStatusSel} />
              </div>
              <DataTable
                rows={rows}
                empty="No competitor categories match this category."
                expand={(r) => (
                  <div className="grid gap-3 text-xs md:grid-cols-2">
                    <div>
                      <div className="text-slate-500">Reason</div>
                      <div>{r.reason}</div>
                      <div className="mt-2 text-slate-500">Classification</div>
                      <StatusBadge value={r.classification} />
                    </div>
                    <div>
                      <div className="text-slate-500">Supporting SRPs ({r.srp_count}, volume {r.search_volume.toLocaleString()})</div>
                      <div className="mt-1 flex flex-wrap gap-1">{r.supporting_srps.map((s) => <Badge key={s.keyword} tone="blue">{s.keyword} · {s.search_volume ?? 0}</Badge>)}</div>
                    </div>
                  </div>
                )}
                columns={[
                  { key: "c", header: "Competitor", render: (r) => <span className="text-xs font-medium">{r.competitor}</span> },
                  {
                    key: "cc",
                    header: "Competitor category & breadcrumb",
                    className: "min-w-[260px]",
                    render: (r) => (
                      <div>
                        <div className="font-medium">{r.competitor_category}</div>
                        <Crumb path={r.competitor_breadcrumb} />
                        {r.competitor_url && <a href={r.competitor_url} target="_blank" rel="noreferrer" className="block break-all text-[11px] text-indigo-600 hover:underline">{r.competitor_url}</a>}
                      </div>
                    ),
                  },
                  { key: "s", header: "In Coupang?", render: (r) => <Badge tone={STATUS_TONE[r.status] || "gray"}>{r.status}</Badge> },
                  {
                    key: "cp",
                    header: "Coupang match",
                    className: "min-w-[240px]",
                    render: (r) =>
                      r.coupang_breadcrumb_cn && r.status.startsWith("PRESENT") ? (
                        <div>
                          <Crumb path={r.coupang_breadcrumb_cn} />
                          {r.coupang_url && <a href={r.coupang_url} target="_blank" rel="noreferrer" className="text-[11px] text-indigo-600">open ↗</a>}
                        </div>
                      ) : r.coupang_category ? (
                        <span className="text-xs text-slate-500">closest: {r.coupang_category}</span>
                      ) : (
                        <span className="text-xs text-slate-400">—</span>
                      ),
                  },
                  {
                    key: "sg",
                    header: "Where it fits in Coupang (CN / EN)",
                    className: "min-w-[300px]",
                    render: (r) =>
                      r.suggested_breadcrumb_cn ? (
                        <div>
                          <Crumb path={r.suggested_breadcrumb_cn} />
                          <div className="text-[11px] text-slate-400">{r.suggested_breadcrumb_en || "EN: add LLM key or synonym"}</div>
                          <div className="mt-1 flex flex-wrap gap-1">
                            {r.gap_type && <StatusBadge value={r.gap_type} />}
                            {r.suggested_parent && <Badge tone={r.suggested_parent_status === "NEW" ? "violet" : "gray"}>parent: {r.suggested_parent} ({r.suggested_parent_status})</Badge>}
                          </div>
                        </div>
                      ) : (
                        <span className="text-xs text-slate-400">—</span>
                      ),
                  },
                  { key: "v", header: "SRP demand", render: (r) => <div className="text-xs tabular-nums">{r.search_volume.toLocaleString()}<div className="text-slate-400">{r.srp_count} SRPs</div></div> },
                  { key: "a", header: "Action", className: "max-w-[180px]", render: (r) => <span className="text-xs font-medium text-indigo-700">{r.recommended_action || (r.status.startsWith("PRESENT") ? "Keep" : "")}</span> },
                ]}
              />
            </Card>
          )}

          {tab === "urls" && (
            <Card>
              <DataTable
                rows={data.urls.map((u, i) => ({ ...u, id: i + 1 }))}
                empty="No crawled URLs in this category."
                columns={[
                  { key: "c", header: "Competitor", render: (u) => <span className="text-xs font-medium">{u.competitor}</span> },
                  { key: "u", header: "URL", className: "max-w-[420px]", render: (u) => <a href={u.url} target="_blank" rel="noreferrer" className="break-all text-xs text-indigo-600 hover:underline">{u.url}</a> },
                  { key: "t", header: "Type", render: (u) => <StatusBadge value={u.page_type} /> },
                  { key: "b", header: "Breadcrumb", className: "min-w-[260px]", render: (u) => <Crumb path={u.breadcrumb} /> },
                  { key: "h", header: "H1", render: (u) => <span className="text-xs">{u.h1}</span> },
                  { key: "s", header: "Status", render: (u) => <span className="text-xs tabular-nums">{u.status_code ?? "—"}</span> },
                ]}
              />
            </Card>
          )}

          {tab === "coupang" && (
            <Card subtitle="Coupang categories inside this focus, and which competitors also have them.">
              <DataTable
                rows={data.coupang_categories.map((c, i) => ({ ...c, id: i + 1 }))}
                empty="No Coupang category matches this name."
                columns={[
                  { key: "b", header: "Coupang breadcrumb", className: "min-w-[320px]", render: (c) => <Crumb path={c.breadcrumb_cn} /> },
                  { key: "e", header: "Name EN", render: (c) => <span className="text-xs">{c.name_en}</span> },
                  { key: "w", header: "Competitors with it", render: (c) => (c.competitors_with_it.length ? c.competitors_with_it.map((x) => <Badge key={x} tone="green" className="mr-1">{x}</Badge>) : <Badge tone="amber">Coupang only</Badge>) },
                  { key: "u", header: "URL", render: (c) => (c.url ? <a href={c.url} target="_blank" rel="noreferrer" className="text-xs text-indigo-600">open ↗</a> : "—") },
                ]}
              />
            </Card>
          )}
        </div>
      )}
    </NeedProject>
  );
}
