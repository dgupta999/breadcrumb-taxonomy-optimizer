import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { api, type Paged } from "@/lib/api";
import { useProject } from "@/lib/project";
import { DataTable, FilterChips, NeedProject, Pager } from "@/components/common";
import { Badge, Button, Card, Crumb, PageHeader, StatusBadge } from "@/components/ui";

type Rule = { id: number; entity_type: string; match_key: string; decision: string; payload: Record<string, string>; approved_by?: string; created_at: string };

export default function RulesPage() {
  const { projectId } = useProject();
  const qc = useQueryClient();
  const [types, setTypes] = useState<string[]>([]);
  const [offset, setOffset] = useState(0);
  const { data, isLoading } = useQuery({
    queryKey: ["rules", projectId, types, offset],
    queryFn: () => api.get<Paged<Rule>>(`/projects/${projectId}/approved-rules`, { entity_type: types, offset, limit: 100 }),
    enabled: !!projectId,
  });
  const del = async (r: Rule) => {
    if (!confirm("Remove this approved rule? Future runs will use rules/AI again for this item.")) return;
    await api.del(`/projects/${projectId}/approved-rules/${r.id}`);
    qc.invalidateQueries({ queryKey: ["rules"] });
  };
  return (
    <NeedProject>
      <PageHeader title="Approved rules" description="Every human decision is stored here and overrides rule/AI decisions on every future run (keys survive taxonomy re-imports because targets are stored by breadcrumb path)." />
      <Card>
        <div className="mb-3 flex items-center justify-between">
          <FilterChips label="Type" options={["SRP", "AUDIT", "GAP", "COMPETITOR_CATEGORY"]} value={types} onChange={(v) => { setTypes(v); setOffset(0); }} />
          {data && <Pager total={data.total} limit={data.limit} offset={offset} onChange={setOffset} />}
        </div>
        <DataTable
          rows={data?.items || []}
          loading={isLoading}
          empty="No approved rules yet — approve items in the Review Queue."
          columns={[
            { key: "t", header: "Type", render: (r) => <Badge tone="indigo">{r.entity_type}</Badge> },
            { key: "k", header: "Applies to", render: (r) => <span className="text-xs">{r.payload?.recommended_breadcrumb ? <Crumb path={r.payload.recommended_breadcrumb} /> : r.match_key.split("␟").join(" › ")}</span> },
            { key: "d", header: "Decision", render: (r) => <StatusBadge value={r.decision} /> },
            { key: "tg", header: "Target", render: (r) => r.payload?.target_breadcrumb ? <Crumb path={r.payload.target_breadcrumb} /> : <span className="text-xs text-slate-500">{r.payload?.parent_name || r.payload?.child_name || r.payload?.consolidate_into || "—"}</span> },
            { key: "b", header: "By", render: (r) => <span className="text-xs">{r.approved_by}</span> },
            { key: "w", header: "When", render: (r) => <span className="text-xs text-slate-500">{new Date(r.created_at).toLocaleString()}</span> },
            { key: "x", header: "", render: (r) => <Button size="xs" variant="ghost" onClick={() => del(r)}><Trash2 size={12} /></Button> },
          ]}
        />
      </Card>
    </NeedProject>
  );
}
