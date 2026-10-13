import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { api, type Paged } from "@/lib/api";
import type { Audit } from "@/lib/types";
import { useProject } from "@/lib/project";
import { DataTable, ExportButtons, FilterChips, LinkingImpact, NeedProject, Pager, SearchBox } from "@/components/common";
import { JobRunner } from "@/components/jobs";
import { ReviewActions } from "@/components/review";
import { Badge, Card, ConfidencePill, Crumb, PageHeader, StatusBadge } from "@/components/ui";

const ACTIONS = ["KEEP", "MOVE", "FLATTEN", "CREATE PARENT", "CREATE CHILD", "MOVE + CREATE PARENT", "CONSOLIDATE", "REVIEW"];
const LINKING = ["HIGH", "MEDIUM", "LOW", "NONE"];
const REVIEW = ["NEEDS_REVIEW", "APPROVED", "REJECTED", "AUTO_APPROVED"];

function ScoreDelta({ a }: { a: Audit }) {
  const up = a.recommended_score - a.current_score;
  return (
    <div className="flex items-center gap-1 text-sm tabular-nums">
      <span className="text-slate-500">{a.current_score}</span>
      <ArrowRight size={12} className="text-slate-400" />
      <span className={up > 0 ? "font-semibold text-emerald-600" : "text-slate-700"}>{a.recommended_score}</span>
    </div>
  );
}

function Breakdown({ b }: { b?: Record<string, number> }) {
  if (!b) return null;
  return (
    <table className="text-[11px]">
      <tbody>
        {Object.entries(b).map(([k, v]) => (
          <tr key={k}>
            <td className="pr-3 text-slate-500">{k.replace(/_/g, " ")}</td>
            <td className="tabular-nums">{v}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function AuditPage() {
  const { projectId } = useProject();
  const [q, setQ] = useState("");
  const [actions, setActions] = useState<string[]>(ACTIONS.filter((a) => a !== "KEEP"));
  const [linking, setLinking] = useState<string[]>([]);
  const [review, setReview] = useState<string[]>([]);
  const [offset, setOffset] = useState(0);
  const [sel, setSel] = useState<Set<number>>(new Set());
  const { data, isLoading } = useQuery({
    queryKey: ["audits", projectId, q, actions, linking, review, offset],
    queryFn: () => api.get<Paged<Audit>>(`/projects/${projectId}/audits`, { q, action: actions, linking, review_status: review, offset, limit: 100 }),
    enabled: !!projectId,
  });
  return (
    <NeedProject>
      <PageHeader
        step="Steps 4 · 12 · 13"
        title="Breadcrumb audit & recommended architecture"
        description="Checks parent relevance, specificity, duplicate/generic levels, missing logical parents, wrong branches and duplicates. Re-run after competitor comparison to add competitor evidence. Existing breadcrumbs are never changed automatically — every row is a proposal."
        actions={<JobRunner jobType="AUDIT_BREADCRUMBS" label="Run breadcrumb audit" />}
      />
      <Card
        title="Audit results"
        actions={
          <>
            <ExportButtons exportKey="breadcrumb_audit" label="Audit" />
            <ExportButtons exportKey="breadcrumb_optimization_recommendations" label="Recommendations" />
          </>
        }
      >
        <div className="mb-3 flex flex-wrap items-center gap-x-5 gap-y-2">
          <SearchBox value={q} onChange={(v) => { setQ(v); setOffset(0); }} placeholder="Search category / breadcrumb…" />
          <FilterChips label="Action" options={ACTIONS} value={actions} onChange={(v) => { setActions(v); setOffset(0); }} />
          <FilterChips label="Linking" options={LINKING} value={linking} onChange={(v) => { setLinking(v); setOffset(0); }} />
          <FilterChips label="Review" options={REVIEW} value={review} onChange={(v) => { setReview(v); setOffset(0); }} />
        </div>
        <div className="mb-2 flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs text-slate-500">
            {sel.size > 0 && (<><span>{sel.size} selected</span><ReviewActions entityType="audit" ids={[...sel]} /></>)}
          </div>
          {data && <Pager total={data.total} limit={data.limit} offset={offset} onChange={setOffset} />}
        </div>
        <DataTable
          rows={data?.items || []}
          loading={isLoading}
          selectable
          selected={sel}
          onSelect={setSel}
          empty="Run the breadcrumb audit after uploading the taxonomy."
          expand={(a) => (
            <div className="grid gap-5 md:grid-cols-3">
              <div className="space-y-2 text-xs">
                <div className="font-semibold text-slate-600">Issues</div>
                <ul className="list-disc space-y-0.5 pl-4">{a.issues.length ? a.issues.map((i, k) => <li key={k}>{i}</li>) : <li>None</li>}</ul>
                <div className="font-semibold text-slate-600">Evidence</div>
                <pre className="whitespace-pre-wrap rounded bg-white p-2 text-[11px] text-slate-600">{JSON.stringify(a.evidence, null, 1)}</pre>
              </div>
              <div className="space-y-2">
                <div className="text-xs font-semibold text-slate-600">Ancestors (breadcrumb links)</div>
                <div className="text-xs"><span className="text-slate-500">Current:</span> {a.current_ancestors.join(" › ") || "—"}</div>
                <div className="text-xs"><span className="text-slate-500">Recommended:</span> {a.recommended_ancestors.join(" › ") || "—"}</div>
                <LinkingImpact removed={a.links_removed} added={a.links_added} level={a.linking_improvement} explanation={a.linking_explanation} />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div><div className="mb-1 text-xs font-semibold text-slate-600">Current score</div><Breakdown b={a.score_breakdown.current} /></div>
                <div><div className="mb-1 text-xs font-semibold text-slate-600">Recommended score</div><Breakdown b={a.score_breakdown.recommended} /></div>
              </div>
            </div>
          )}
          columns={[
            { key: "c", header: "Category", render: (a) => <div><div className="font-medium">{a.category_name}</div>{a.category_url && <a href={a.category_url} target="_blank" rel="noreferrer" className="text-[11px] text-indigo-600">open ↗</a>}</div> },
            { key: "cur", header: "Current breadcrumb", className: "min-w-[280px]", render: (a) => <Crumb path={a.current_breadcrumb_cn} highlight={a.links_removed.filter((x) => x.irrelevant).map((x) => x.label)} /> },
            { key: "act", header: "Action", render: (a) => <div className="space-y-1"><StatusBadge value={a.action} />{a.recommended_parent_status === "NEW" && <Badge tone="violet">new parent</Badge>}</div> },
            {
              key: "rec",
              header: "Recommended breadcrumb (CN / EN)",
              className: "min-w-[300px]",
              render: (a) =>
                a.action === "KEEP" ? (
                  <span className="text-xs text-slate-400">unchanged</span>
                ) : (
                  <div>
                    <Crumb path={a.recommended_breadcrumb_cn} highlight={a.links_added.map((x) => x.label)} />
                    <div className="text-[11px] text-slate-400">{a.recommended_breadcrumb_en}</div>
                    <div className="mt-1 text-[11px] text-slate-600">{a.reason}</div>
                  </div>
                ),
            },
            { key: "score", header: "Quality score", render: (a) => <ScoreDelta a={a} /> },
            { key: "link", header: "Linking", render: (a) => <StatusBadge value={a.linking_improvement} /> },
            { key: "conf", header: "Conf.", render: (a) => <ConfidencePill value={a.confidence} /> },
            { key: "rs", header: "Review", render: (a) => <StatusBadge value={a.review_status} /> },
            { key: "x", header: "", render: (a) => <ReviewActions entityType="audit" ids={[a.id]} compact /> },
          ]}
        />
      </Card>
    </NeedProject>
  );
}
