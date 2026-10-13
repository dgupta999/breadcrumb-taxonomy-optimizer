import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Paged } from "@/lib/api";
import type { Competitor, Gap } from "@/lib/types";
import { useProject } from "@/lib/project";
import { ExportButtons, FilterChips, LinkingImpact, NeedProject, Pager, SearchBox } from "@/components/common";
import { JobRunner } from "@/components/jobs";
import { ReviewActions } from "@/components/review";
import { Badge, Card, ConfidencePill, Crumb, Empty, PageHeader, StatusBadge } from "@/components/ui";

export const GAP_TYPES = ["MISSING PARENT", "MISSING CHILD", "BOTH MISSING", "MISPLACED EXISTING CATEGORY", "DUPLICATE", "SRP-ONLY GAP"];
const PRIORITY = ["HIGH", "MEDIUM", "LOW"];
const REVIEW = ["NEEDS_REVIEW", "APPROVED", "REJECTED"];

export function GapCard({ g }: { g: Gap }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge value={g.gap_type} />
            <StatusBadge value={g.priority} />
            <span className="text-xs tabular-nums text-slate-500">score {g.score}</span>
            <ConfidencePill value={g.confidence} />
            <StatusBadge value={g.review_status} />
          </div>
          <div className="text-base font-semibold">
            {g.gap_type === "MISSING PARENT" || g.gap_type === "BOTH MISSING" ? g.parent_name_cn : g.main_name_cn}
            <span className="ml-2 text-sm font-normal text-slate-500">{g.gap_type === "MISSING PARENT" || g.gap_type === "BOTH MISSING" ? g.parent_name_en : g.main_name_en}</span>
          </div>
          <div className="text-sm font-medium text-indigo-700">{g.recommended_action}</div>
        </div>
        <ReviewActions entityType="gap" ids={[g.id]} defaultName={g.main_name_cn || ""} />
      </div>

      <div className="mt-3 grid gap-4 lg:grid-cols-2">
        <div className="space-y-2 text-xs">
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            <span>Parent: <b>{g.parent_name_cn || "—"}</b> <StatusBadge value={g.parent_status} /></span>
            <span>Main: <b>{g.main_name_cn || "—"}</b> <StatusBadge value={g.main_status} /></span>
          </div>
          {g.current_breadcrumb_cn && <div><span className="text-slate-500">Current: </span><Crumb path={g.current_breadcrumb_cn} /></div>}
          <div><span className="text-slate-500">Suggested CN: </span><Crumb path={g.suggested_breadcrumb_cn} /></div>
          <div><span className="text-slate-500">Suggested EN: </span>{g.suggested_breadcrumb_en ? <Crumb path={g.suggested_breadcrumb_en} /> : <Badge tone="amber">EN missing — enable LLM or add synonym</Badge>} {g.en_source === "AI" && <Badge tone="violet">EN: AI</Badge>}</div>
          {g.children.length > 0 && (
            <div className="rounded-lg border border-slate-100">
              <table className="w-full text-xs">
                <thead className="bg-slate-50 text-left text-[10px] uppercase text-slate-500"><tr><th className="px-2 py-1">Child</th><th>Status</th><th>Existing / suggested breadcrumb</th><th className="text-right pr-2">Vol.</th></tr></thead>
                <tbody>
                  {g.children.map((c) => (
                    <tr key={c.id} className="border-t border-slate-100 align-top">
                      <td className="px-2 py-1 font-medium">{c.name_cn}<div className="font-normal text-slate-400">{c.name_en}</div></td>
                      <td className="py-1"><StatusBadge value={c.status} /></td>
                      <td className="py-1">{c.existing_breadcrumb && <div className="text-slate-400 line-through decoration-slate-300">{c.existing_breadcrumb}</div>}<Crumb path={c.suggested_breadcrumb_cn} /></td>
                      <td className="py-1 pr-2 text-right tabular-nums">{c.search_volume || ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="text-slate-600">{g.reason}</div>
        </div>
        <div className="space-y-3 text-xs">
          <div>
            <div className="mb-1 font-semibold text-slate-600">SRP validation · {g.srp_count} SRPs · combined volume {g.combined_search_volume.toLocaleString()}{g.product_count ? ` · ${g.product_count} products` : ""}</div>
            <div className="flex flex-wrap gap-1">
              {g.supporting_srps.slice(0, 15).map((s) => (
                <Badge key={s.keyword} tone="blue" title={s.match}>{s.keyword} · {s.search_volume ?? 0}</Badge>
              ))}
              {g.supporting_srps.length === 0 && <span className="text-slate-400">No supporting SRP demand</span>}
            </div>
          </div>
          <div>
            <div className="mb-1 font-semibold text-slate-600">Competitor evidence ({g.competitor_count})</div>
            {Object.entries(g.competitor_evidence).map(([c, ev]) => (
              <div key={c} className="mb-1"><b>{c}</b>: {ev.map((e, i) => <span key={i} className="mr-2">{e.url ? <a href={e.url} target="_blank" rel="noreferrer" className="text-indigo-600 hover:underline">{e.breadcrumb}</a> : e.breadcrumb}</span>)}</div>
            ))}
            {g.competitor_count === 0 && <span className="text-slate-400">None</span>}
          </div>
          <div>
            <div className="mb-1 font-semibold text-slate-600">Score breakdown</div>
            <div className="flex flex-wrap gap-1">{Object.entries(g.score_breakdown).filter(([, v]) => v).map(([k, v]) => <Badge key={k} tone={v > 0 ? "green" : "red"}>{k.replace(/_/g, " ")} {v > 0 ? `+${v}` : v}</Badge>)}</div>
          </div>
          <LinkingImpact removed={g.links_removed} added={g.links_added} level={g.linking_improvement} />
        </div>
      </div>
    </div>
  );
}

export function useGaps(filters: Record<string, unknown>) {
  const { projectId } = useProject();
  return useQuery({
    queryKey: ["gaps", projectId, filters],
    queryFn: () => api.get<Paged<Gap>>(`/projects/${projectId}/gaps`, filters),
    enabled: !!projectId,
  });
}

export default function GapsPage() {
  const { projectId } = useProject();
  const comps = useQuery({ queryKey: ["competitors", projectId], queryFn: () => api.get<Competitor[]>(`/projects/${projectId}/competitors`), enabled: !!projectId });
  const [types, setTypes] = useState<string[]>([]);
  const [prio, setPrio] = useState<string[]>([]);
  const [review, setReview] = useState<string[]>([]);
  const [comp, setComp] = useState<string[]>([]);
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const { data, isLoading } = useGaps({ gap_type: types, priority: prio, review_status: review, competitor: comp, q, offset, limit: 25 });
  return (
    <NeedProject>
      <PageHeader
        step="Steps 10–11"
        title="Taxonomy gaps"
        description="Detected from competitor evidence and validated with SRP demand. A competitor-only gap with no SRP support is never recommended for creation; existing equivalents are flagged as duplicates instead of new pages."
        actions={
          <>
            <JobRunner jobType="DETECT_GAPS" label="Detect & validate gaps" />
            <ExportButtons exportKey="taxonomy_gap_analysis" />
          </>
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-x-5 gap-y-2 rounded-xl border border-slate-200 bg-white p-3">
        <SearchBox value={q} onChange={(v) => { setQ(v); setOffset(0); }} placeholder="Search category / breadcrumb…" />
        <FilterChips label="Type" options={GAP_TYPES} value={types} onChange={(v) => { setTypes(v); setOffset(0); }} />
        <FilterChips label="Priority" options={PRIORITY} value={prio} onChange={(v) => { setPrio(v); setOffset(0); }} />
        <FilterChips label="Review" options={REVIEW} value={review} onChange={(v) => { setReview(v); setOffset(0); }} />
        {!!comps.data?.length && <FilterChips label="Competitor" options={comps.data.map((c) => c.name)} value={comp} onChange={(v) => { setComp(v); setOffset(0); }} />}
        {data && <Pager total={data.total} limit={data.limit} offset={offset} onChange={setOffset} />}
      </div>
      <div className="space-y-4">
        {isLoading && <Card><span className="text-sm text-slate-500">Loading…</span></Card>}
        {data?.items.length === 0 && <Empty>No gaps match. Run competitor comparison, then “Detect & validate gaps”.</Empty>}
        {data?.items.map((g) => <GapCard key={g.id} g={g} />)}
      </div>
    </NeedProject>
  );
}
