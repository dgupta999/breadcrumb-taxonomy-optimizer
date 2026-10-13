import { useState } from "react";
import type { Gap } from "@/lib/types";
import { DataTable, ExportButtons, FilterChips, NeedProject, Pager } from "@/components/common";
import { JobRunner } from "@/components/jobs";
import { ReviewActions } from "@/components/review";
import { Badge, Card, Crumb, PageHeader, StatusBadge } from "@/components/ui";
import { useGaps } from "./Gaps";

const TYPES = ["MISSING PARENT", "MISSING CHILD", "BOTH MISSING", "MISPLACED EXISTING CATEGORY"];

type Row = { id: number; gap: Gap; child?: Gap["children"][number] };

export default function ParentChildGaps() {
  const [types, setTypes] = useState<string[]>([]);
  const [offset, setOffset] = useState(0);
  const { data, isLoading } = useGaps({ parent_child: true, gap_type: types, offset, limit: 50 });
  const rows: Row[] = [];
  data?.items.forEach((g) => {
    if (g.children.length) g.children.forEach((c) => rows.push({ id: g.id * 100000 + c.id, gap: g, child: c }));
    else rows.push({ id: g.id * 100000, gap: g });
  });
  return (
    <NeedProject>
      <PageHeader
        step="Steps 10 · 12"
        title="Parent / child gaps"
        description="One row per child: whether the suggested parent and each child already exist, are new, or exist under the wrong parent — with CN/EN breadcrumbs built from existing ancestors."
        actions={
          <>
            <JobRunner jobType="DETECT_GAPS" label="Re-detect gaps" variant="outline" />
            <ExportButtons exportKey="parent_child_gap_analysis" />
          </>
        }
      />
      <Card>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <FilterChips label="Gap type" options={TYPES} value={types} onChange={(v) => { setTypes(v); setOffset(0); }} />
          {data && <Pager total={data.total} limit={data.limit} offset={offset} onChange={setOffset} />}
        </div>
        <DataTable
          rows={rows}
          loading={isLoading}
          empty="No parent/child gaps yet."
          columns={[
            { key: "t", header: "Gap type", render: (r) => <div className="space-y-1"><StatusBadge value={r.gap.gap_type} /><StatusBadge value={r.gap.priority} /></div> },
            { key: "p", header: "Suggested parent", render: (r) => <div><div className="font-medium">{r.gap.parent_name_cn || "—"}</div><div className="text-[11px] text-slate-500">{r.gap.parent_name_en}</div><StatusBadge value={r.gap.parent_status} /></div> },
            {
              key: "c",
              header: "Child category",
              render: (r) =>
                r.child ? (
                  <div><div className="font-medium">{r.child.name_cn}</div><div className="text-[11px] text-slate-500">{r.child.name_en}</div><StatusBadge value={r.child.status} /></div>
                ) : (
                  <div><div className="font-medium">{r.gap.main_name_cn}</div><div className="text-[11px] text-slate-500">{r.gap.main_name_en}</div><StatusBadge value={r.gap.main_status} /></div>
                ),
            },
            {
              key: "ex",
              header: "Existing child breadcrumb",
              className: "min-w-[220px]",
              render: (r) => {
                const bc = r.child ? r.child.existing_breadcrumb : r.gap.current_breadcrumb_cn;
                const url = r.child ? r.child.existing_url : r.gap.existing_url;
                return bc ? <div><Crumb path={bc} />{url && <a href={url} target="_blank" rel="noreferrer" className="text-[11px] text-indigo-500">↗</a>}</div> : <span className="text-xs text-slate-400">—</span>;
              },
            },
            {
              key: "s",
              header: "Suggested breadcrumb CN / EN",
              className: "min-w-[320px]",
              render: (r) => {
                const cn = r.child ? r.child.suggested_breadcrumb_cn : r.gap.suggested_breadcrumb_cn;
                const en = r.child ? r.child.suggested_breadcrumb_en : r.gap.suggested_breadcrumb_en;
                return <div><Crumb path={cn} /><div className="text-[11px] text-slate-400">{en || "EN missing"}</div></div>;
              },
            },
            {
              key: "srp",
              header: "SRPs / volume",
              render: (r) => {
                const sup = r.child?.supporting_srps?.length ? r.child.supporting_srps : r.gap.supporting_srps;
                const vol = r.child?.search_volume || r.gap.combined_search_volume;
                return <div className="text-xs"><div className="tabular-nums font-medium">{vol.toLocaleString()}</div><div className="flex flex-wrap gap-0.5">{sup.slice(0, 3).map((s) => <Badge key={s.keyword} tone="blue">{s.keyword}</Badge>)}</div></div>;
              },
            },
            { key: "e", header: "Evidence", render: (r) => <div className="flex flex-wrap gap-1">{Object.keys(r.gap.competitor_evidence).map((c) => <Badge key={c} tone="indigo">{c}</Badge>)}</div> },
            { key: "a", header: "Action", className: "max-w-[200px]", render: (r) => <span className="text-xs font-medium text-indigo-700">{r.gap.recommended_action}</span> },
            { key: "r", header: "Review", render: (r) => <div className="space-y-1"><StatusBadge value={r.gap.review_status} /><ReviewActions entityType="gap" ids={[r.gap.id]} compact defaultName={r.child?.name_cn || r.gap.main_name_cn || ""} /></div> },
          ]}
        />
      </Card>
    </NeedProject>
  );
}
