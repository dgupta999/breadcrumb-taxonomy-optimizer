import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { EntityType, ReviewItem } from "@/lib/types";
import { useProject } from "@/lib/project";
import { DataTable, ExportButtons, FilterChips, NeedProject } from "@/components/common";
import { ReviewActions } from "@/components/review";
import { Badge, Card, ConfidencePill, Crumb, Input, PageHeader, StatusBadge } from "@/components/ui";

const TYPE_LABEL: Record<EntityType, string> = { srp: "SRP mapping", audit: "Breadcrumb audit", gap: "Taxonomy gap", competitor_mapping: "Competitor mapping" };

export default function ReviewQueue() {
  const { projectId } = useProject();
  const [types, setTypes] = useState<string[]>([]);
  const [band, setBand] = useState<string[]>([]);
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [reviewer, setReviewer] = useState(() => {
    try { return localStorage.getItem("bto.reviewer") || ""; } catch { return ""; }
  });
  const typeKeys = types.map((t) => (Object.entries(TYPE_LABEL).find(([, v]) => v === t)?.[0] as EntityType));
  const { data, isLoading } = useQuery({
    queryKey: ["review-queue", projectId, typeKeys],
    queryFn: () => api.get<{ items: ReviewItem[]; total: number }>(`/projects/${projectId}/review-queue`, { entity_type: typeKeys, limit: 500 }),
    enabled: !!projectId,
  });
  // unique ids across entity types for selection
  const rows = useMemo(
    () => (data?.items || [])
      .filter((i) => {
        if (!band.length) return true;
        const c = i.confidence ?? 0;
        return band.some((b) => (b === "High (≥90)" ? c >= 90 : b === "Medium (70–89)" ? c >= 70 && c < 90 : c < 70));
      })
      .map((i) => ({ ...i, uid: i.id, id: ({ srp: 1, audit: 2, gap: 3, competitor_mapping: 4 }[i.entity_type]) * 10_000_000 + i.id })),
    [data, band],
  );
  const selectedByType = (t: EntityType) => rows.filter((r) => sel.has(r.id) && r.entity_type === t).map((r) => r.uid);
  return (
    <NeedProject>
      <PageHeader
        step="Step 14"
        title="Review queue"
        description="Everything that needs a human decision: medium/low-confidence SRP mappings, NO_MATCH SRPs, breadcrumb recommendations, taxonomy gaps and ambiguous competitor mappings. Approved decisions are saved as rules and override future runs."
        actions={<ExportButtons exportKey="srp_review_queue" label="SRP queue" />}
      />
      <Card>
        <div className="mb-3 flex flex-wrap items-center gap-x-5 gap-y-2">
          <FilterChips label="Type" options={Object.values(TYPE_LABEL)} value={types} onChange={setTypes} />
          <FilterChips label="Confidence" options={["High (≥90)", "Medium (70–89)", "Low (<70)"]} value={band} onChange={setBand} />
          <div className="flex items-center gap-2 text-xs text-slate-500">
            Reviewer
            <Input className="w-36 py-1" value={reviewer} onChange={(e) => { setReviewer(e.target.value); try { localStorage.setItem("bto.reviewer", e.target.value); } catch { /* ignore */ } }} placeholder="your name" />
          </div>
        </div>
        {sel.size > 0 && (
          <div className="mb-3 flex flex-wrap items-center gap-4 rounded-lg bg-indigo-50 px-3 py-2 text-xs">
            <span className="font-medium">{sel.size} selected</span>
            {(Object.keys(TYPE_LABEL) as EntityType[]).map((t) => {
              const ids = selectedByType(t);
              return ids.length ? (
                <span key={t} className="flex items-center gap-2">
                  {TYPE_LABEL[t]} ({ids.length}) <ReviewActions entityType={t} ids={ids} compact />
                </span>
              ) : null;
            })}
          </div>
        )}
        <DataTable
          rows={rows}
          loading={isLoading}
          selectable
          selected={sel}
          onSelect={setSel}
          empty="Nothing to review 🎉"
          expand={(r) => (
            <div className="space-y-2 text-xs">
              <div>{r.reason}</div>
              {r.candidates && r.candidates.length > 0 && (
                <div>
                  <div className="mb-1 font-semibold text-slate-600">Candidates</div>
                  {r.candidates.map((c) => <div key={c.node_id}><Badge>{c.score}</Badge> <Crumb path={c.breadcrumb} /></div>)}
                </div>
              )}
            </div>
          )}
          columns={[
            { key: "t", header: "Type", render: (r) => <div className="space-y-1"><Badge tone="indigo">{TYPE_LABEL[r.entity_type]}</Badge><div><StatusBadge value={r.kind} /></div></div> },
            { key: "n", header: "Item", render: (r) => <div><div className="font-medium">{r.title}</div>{r.search_volume ? <div className="text-[11px] text-slate-500">vol {r.search_volume.toLocaleString()}</div> : null}</div> },
            { key: "c", header: "Current", className: "min-w-[220px]", render: (r) => <Crumb path={r.current} /> },
            { key: "r", header: "Recommended", className: "min-w-[260px]", render: (r) => <Crumb path={r.recommended} /> },
            { key: "conf", header: "Confidence", render: (r) => <ConfidencePill value={r.confidence} /> },
            { key: "p", header: "Priority / linking", render: (r) => <div className="space-y-1"><StatusBadge value={r.priority} />{r.linking && <StatusBadge value={r.linking} />}</div> },
            { key: "x", header: "Decision", render: (r) => <ReviewActions entityType={r.entity_type} ids={[r.uid]} compact defaultName={r.title} /> },
          ]}
        />
      </Card>
    </NeedProject>
  );
}
