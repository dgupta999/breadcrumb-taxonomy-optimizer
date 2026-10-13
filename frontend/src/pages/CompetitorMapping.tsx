import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Paged } from "@/lib/api";
import type { Competitor, CompetitorMapping } from "@/lib/types";
import { useProject } from "@/lib/project";
import { DataTable, ExportButtons, FilterChips, NeedProject, Pager, SearchBox } from "@/components/common";
import { JobRunner } from "@/components/jobs";
import { ReviewActions } from "@/components/review";
import { Card, ConfidencePill, Crumb, PageHeader, Select, StatusBadge } from "@/components/ui";

const TYPES = ["EXACT MATCH", "SEMANTIC MATCH", "COMPETITOR MORE SPECIFIC", "COMPETITOR MORE GENERAL", "MISSING FROM MY TAXONOMY", "EXISTING BUT MISPLACED", "AMBIGUOUS"];

export default function CompetitorMappingPage() {
  const { projectId } = useProject();
  const comps = useQuery({ queryKey: ["competitors", projectId], queryFn: () => api.get<Competitor[]>(`/projects/${projectId}/competitors`), enabled: !!projectId });
  const [types, setTypes] = useState<string[]>([]);
  const [cid, setCid] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const { data, isLoading } = useQuery({
    queryKey: ["comp-mappings", projectId, types, cid, q, offset],
    queryFn: () => api.get<Paged<CompetitorMapping>>(`/projects/${projectId}/competitor-mappings`, { match_type: types, competitor_id: cid || undefined, q, offset, limit: 100 }),
    enabled: !!projectId,
  });
  return (
    <NeedProject>
      <PageHeader
        step="Step 9"
        title="Competitor vs current taxonomy"
        description="Each competitor category is matched on name, breadcrumb/parent context, child overlap, synonyms and product concept — not text overlap alone (poe switch never maps to Nintendo Switch). Competitor taxonomy is evidence, not the source of truth."
        actions={
          <>
            <JobRunner jobType="COMPARE_TAXONOMY" label="Compare taxonomies" params={{}} />
            <ExportButtons exportKey="competitor_vs_current" />
          </>
        }
      />
      <Card title="Mappings">
        <div className="mb-3 flex flex-wrap items-center gap-x-5 gap-y-2">
          <SearchBox value={q} onChange={(v) => { setQ(v); setOffset(0); }} placeholder="Search reason…" />
          <Select value={cid} onChange={(e) => { setCid(e.target.value); setOffset(0); }}>
            <option value="">All competitors</option>
            {comps.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </Select>
          <FilterChips options={TYPES} value={types} onChange={(v) => { setTypes(v); setOffset(0); }} />
          {data && <Pager total={data.total} limit={data.limit} offset={offset} onChange={setOffset} />}
        </div>
        <DataTable
          rows={data?.items || []}
          loading={isLoading}
          empty="Run the comparison after crawling competitors."
          columns={[
            { key: "c", header: "Competitor", render: (m) => <span className="text-xs font-medium">{m.competitor}</span> },
            { key: "cc", header: "Competitor category", className: "min-w-[240px]", render: (m) => <div><Crumb path={m.competitor_breadcrumb} />{m.competitor_url && <a href={m.competitor_url} target="_blank" rel="noreferrer" className="text-[11px] text-indigo-500">↗</a>}</div> },
            { key: "t", header: "Classification", render: (m) => <StatusBadge value={m.match_type} /> },
            { key: "mine", header: "My category", className: "min-w-[240px]", render: (m) => m.my_breadcrumb ? <Crumb path={m.my_breadcrumb} /> : <span className="text-xs text-slate-400">—</span> },
            { key: "p", header: "Competitor parent ≈", render: (m) => <span className="text-xs">{m.parent_maps_to || "—"}</span> },
            { key: "r", header: "Reason", className: "max-w-[320px]", render: (m) => <span className="text-xs text-slate-600">{m.reason}</span> },
            { key: "conf", header: "Conf.", render: (m) => <ConfidencePill value={m.confidence} /> },
            { key: "rs", header: "Review", render: (m) => <StatusBadge value={m.review_status} /> },
            { key: "x", header: "", render: (m) => <ReviewActions entityType="competitor_mapping" ids={[m.id]} compact /> },
          ]}
        />
      </Card>
    </NeedProject>
  );
}
