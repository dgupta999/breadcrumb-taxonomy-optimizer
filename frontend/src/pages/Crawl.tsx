import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { api, type Paged } from "@/lib/api";
import type { Competitor, Gap } from "@/lib/types";
import { useProject } from "@/lib/project";
import { DataTable, ExportButtons, NeedProject } from "@/components/common";
import { JobProgress, useLatestJob } from "@/components/jobs";
import { Badge, Button, Card, Crumb, Input, Label, PageHeader, StatusBadge } from "@/components/ui";
import { Uploader } from "./Upload";

type GapRow = { id: number; gap: Gap; level: string; name: string; nameEn?: string | null; status: string; crumb?: string | null; crumbEn?: string | null; volume: number };

function flatten(gaps: Gap[]): GapRow[] {
  const rows: GapRow[] = [];
  gaps.forEach((g) => {
    if (g.gap_type === "MISSING PARENT" || g.gap_type === "BOTH MISSING") {
      rows.push({ id: g.id * 1000, gap: g, level: "Parent", name: g.parent_name_cn || "", nameEn: g.parent_name_en, status: "NEW", crumb: g.suggested_breadcrumb_cn, crumbEn: g.suggested_breadcrumb_en, volume: g.combined_search_volume });
      g.children.forEach((c) =>
        rows.push({ id: g.id * 1000 + c.id, gap: g, level: "Child", name: c.name_cn, nameEn: c.name_en, status: c.status === "EXISTING" ? "EXISTING → MOVE" : "NEW", crumb: c.suggested_breadcrumb_cn, crumbEn: c.suggested_breadcrumb_en, volume: c.search_volume }),
      );
    } else {
      rows.push({ id: g.id * 1000, gap: g, level: g.gap_type === "MISSING CHILD" ? "Child" : "Existing page", name: g.main_name_cn || "", nameEn: g.main_name_en, status: g.gap_type === "MISSING CHILD" ? "NEW" : "EXISTING → MOVE", crumb: g.suggested_breadcrumb_cn, crumbEn: g.suggested_breadcrumb_en, volume: g.combined_search_volume });
    }
  });
  return rows;
}

export default function CompetitorUpload() {
  const { projectId } = useProject();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [append, setAppend] = useState(false);
  const comps = useQuery({ queryKey: ["competitors", projectId], queryFn: () => api.get<Competitor[]>(`/projects/${projectId}/competitors`), enabled: !!projectId });
  const imp = useLatestJob("IMPORT_COMPETITOR_CRAWL");
  const cmp = useLatestJob("COMPARE_TAXONOMY");
  const gapJob = useLatestJob("DETECT_GAPS");
  const busy = [imp.data, cmp.data, gapJob.data].some((j) => j && ["QUEUED", "RUNNING"].includes(j.status));
  const gaps = useQuery({
    queryKey: ["gaps", projectId, "competitor-report"],
    queryFn: () => api.get<Paged<Gap>>(`/projects/${projectId}/gaps`, { parent_child: true, limit: 500 }),
    enabled: !!projectId,
    refetchInterval: busy ? 3000 : false,
  });
  const rows = flatten((gaps.data?.items || []).filter((g) => g.review_status !== "REJECTED"));
  const rerun = async () => {
    await api.post(`/projects/${projectId}/jobs`, { job_type: "COMPARE_TAXONOMY", params: { then: [{ job_type: "DETECT_GAPS" }] } });
    qc.invalidateQueries();
  };
  const remove = async (c: Competitor) => {
    if (!confirm(`Delete ${c.name} and its uploaded data?`)) return;
    await api.del(`/projects/${projectId}/competitors/${c.id}`);
    qc.invalidateQueries();
  };

  return (
    <NeedProject>
      <PageHeader
        step="Steps 6–11"
        title="Competitors"
        description="Upload each competitor's crawl CSV. It is compared with the Coupang taxonomy automatically, and you get a gap report: every new page to create (or existing page to move) with where it falls in Coupang's hierarchy."
      />

      <div className="grid gap-5 xl:grid-cols-5">
        <div className="xl:col-span-3">
          <Uploader
            kind="COMPETITOR_CRAWL"
            title="1 · Upload competitor CSV"
            description="Columns needed: URL + Breadcrumb (one 'A > B > C' column, or Breadcrumb 1, 2, 3… columns). Optional: H1, Title, Status Code. CSV or XLSX; product pages are fine."
            extra={{ competitor_name: name.trim(), append }}
            blockedReason={name.trim() ? null : "Enter the competitor name first"}
          >
            <div className="mb-3 flex flex-wrap items-end gap-3">
              <div className="w-56">
                <Label required>Competitor name</Label>
                <Input list="competitor-names" value={name} onChange={(e) => setName(e.target.value)} placeholder="MOMO" />
                <datalist id="competitor-names">
                  {comps.data?.map((c) => <option key={c.id} value={c.name} />)}
                </datalist>
              </div>
              <label className="flex items-center gap-2 pb-2 text-xs text-slate-600">
                <input type="checkbox" checked={append} onChange={(e) => setAppend(e.target.checked)} />
                Add to this competitor's previous file (otherwise it replaces it)
              </label>
            </div>
          </Uploader>
        </div>
        <Card title="Uploaded competitors" className="xl:col-span-2" actions={<Button variant="outline" size="sm" onClick={rerun} disabled={busy}>Re-run comparison</Button>}>
          <div className="space-y-2">
            {comps.data?.length === 0 && <div className="text-sm text-slate-500">None yet.</div>}
            {comps.data?.map((c) => (
              <div key={c.id} className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2">
                <div>
                  <div className="text-sm font-semibold">{c.name}</div>
                  <div className="text-[11px] text-slate-500">
                    {c.start_url.startsWith("(") ? "" : `${c.start_url} · `}{c.last_crawl?.processed_urls ?? 0} URLs · {c.categories} categories
                  </div>
                </div>
                <Button variant="ghost" size="sm" onClick={() => remove(c)} title="Delete"><Trash2 size={13} /></Button>
              </div>
            ))}
          </div>
          <div className="mt-3 space-y-1.5">
            {imp.data && <JobProgress job={imp.data} compact />}
            {cmp.data && <JobProgress job={cmp.data} compact />}
            {gapJob.data && <JobProgress job={gapJob.data} compact />}
          </div>
        </Card>
      </div>

      <Card
        className="mt-5"
        title="2 · Gap report — new pages and where they fall in Coupang"
        subtitle="One row per page to create (or existing page to move). A new parent is listed above its children. Breadcrumbs use Coupang's existing hierarchy for every existing level."
        actions={<ExportButtons exportKey="competitor_gap_pages" label="Download gaps" />}
      >
        <DataTable
          rows={rows}
          loading={gaps.isLoading}
          empty={busy ? "Comparing with Coupang…" : "No gaps yet — upload the Coupang taxonomy (Upload Taxonomy) and a competitor CSV."}
          columns={[
            { key: "p", header: "Priority", render: (r) => <StatusBadge value={r.gap.priority} /> },
            { key: "t", header: "Gap type", render: (r) => <div className="space-y-1"><StatusBadge value={r.gap.gap_type} /><div className="text-[11px] text-slate-500">{r.level}</div></div> },
            { key: "n", header: "Page", render: (r) => <div><div className="font-medium">{r.name}</div><div className="text-[11px] text-slate-500">{r.nameEn}</div></div> },
            { key: "s", header: "Status", render: (r) => <Badge tone={r.status === "NEW" ? "violet" : "amber"}>{r.status}</Badge> },
            { key: "b", header: "Breadcrumb in Coupang (CN / EN)", className: "min-w-[360px]", render: (r) => <div><Crumb path={r.crumb} highlight={[r.name]} /><div className="text-[11px] text-slate-400">{r.crumbEn || "EN: set OPENAI_API_KEY for AI translation"}</div></div> },
            { key: "c", header: "Competitors", render: (r) => <div className="flex flex-wrap gap-1">{Object.keys(r.gap.competitor_evidence || {}).map((c) => <Badge key={c} tone="indigo">{c}</Badge>)}</div> },
            { key: "v", header: "SRP volume", render: (r) => <span className="tabular-nums text-xs">{(r.volume || 0).toLocaleString()}</span> },
            { key: "a", header: "Action", className: "max-w-[200px]", render: (r) => <span className="text-xs text-indigo-700">{r.gap.recommended_action}</span> },
          ]}
        />
      </Card>
    </NeedProject>
  );
}
