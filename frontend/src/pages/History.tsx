import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Paged } from "@/lib/api";
import type { Job } from "@/lib/types";
import { useProject } from "@/lib/project";
import { NeedProject } from "@/components/common";
import { JobProgress } from "@/components/jobs";
import { Card, PageHeader, StatusBadge } from "@/components/ui";

type Review = { id: number; entity_type: string; entity_id: number; action: string; previous_status?: string; new_status?: string; reviewer?: string; note?: string; payload: Record<string, unknown>; created_at: string };
type Override = { id: number; entity_type: string; entity_id: number; field: string; old_value?: string; new_value?: string; created_by?: string; created_at: string };
type Exp = { id: number; export_key: string; format: string; filename: string; row_count: number; created_at: string };

export default function HistoryPage() {
  const { projectId } = useProject();
  const [tab, setTab] = useState<"reviews" | "overrides" | "jobs" | "exports">("reviews");
  const { data } = useQuery({
    queryKey: ["history", projectId],
    queryFn: () => api.get<{ reviews: Paged<Review>; overrides: Override[]; exports: Exp[]; jobs: Job[] }>(`/projects/${projectId}/history`, { limit: 500 }),
    enabled: !!projectId,
  });
  const when = (s: string) => new Date(s).toLocaleString();
  return (
    <NeedProject>
      <PageHeader title="History" description="Audit trail of review decisions, manual overrides, job runs and exports." />
      <div className="mb-4 flex gap-1 rounded-lg bg-slate-100 p-1 text-sm">
        {(["reviews", "overrides", "jobs", "exports"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)} className={`rounded-md px-3 py-1.5 capitalize ${tab === t ? "bg-white font-medium shadow-sm" : "text-slate-600"}`}>
            {t}
          </button>
        ))}
      </div>
      <Card>
        {tab === "reviews" && (
          <table className="w-full text-sm">
            <thead className="text-left text-[11px] uppercase text-slate-500"><tr><th className="py-1">When</th><th>Reviewer</th><th>Item</th><th>Action</th><th>Status change</th><th>Payload</th></tr></thead>
            <tbody>
              {data?.reviews.items.map((r) => (
                <tr key={r.id} className="border-t border-slate-100 align-top">
                  <td className="py-1.5 text-xs text-slate-500">{when(r.created_at)}</td>
                  <td className="text-xs">{r.reviewer}</td>
                  <td className="text-xs">{r.entity_type} #{r.entity_id}</td>
                  <td><StatusBadge value={r.action} /></td>
                  <td className="text-xs"><StatusBadge value={r.previous_status} /> → <StatusBadge value={r.new_status} /></td>
                  <td className="text-[11px] text-slate-500">{Object.keys(r.payload || {}).length ? JSON.stringify(r.payload) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {tab === "overrides" && (
          <table className="w-full text-sm">
            <thead className="text-left text-[11px] uppercase text-slate-500"><tr><th className="py-1">When</th><th>By</th><th>Item</th><th>Field</th><th>Old</th><th>New</th></tr></thead>
            <tbody>
              {data?.overrides.map((o) => (
                <tr key={o.id} className="border-t border-slate-100">
                  <td className="py-1.5 text-xs text-slate-500">{when(o.created_at)}</td><td className="text-xs">{o.created_by}</td>
                  <td className="text-xs">{o.entity_type} #{o.entity_id}</td><td className="text-xs">{o.field}</td>
                  <td className="text-xs text-slate-500">{o.old_value}</td><td className="text-xs font-medium">{o.new_value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {tab === "jobs" && <div className="space-y-1.5">{data?.jobs.map((j) => <JobProgress key={j.id} job={j} compact />)}</div>}
        {tab === "exports" && (
          <table className="w-full text-sm">
            <thead className="text-left text-[11px] uppercase text-slate-500"><tr><th className="py-1">When</th><th>File</th><th>Format</th><th>Rows</th></tr></thead>
            <tbody>
              {data?.exports.map((e) => (
                <tr key={e.id} className="border-t border-slate-100"><td className="py-1.5 text-xs text-slate-500">{when(e.created_at)}</td><td className="text-xs">{e.filename}</td><td className="text-xs uppercase">{e.format}</td><td className="text-xs tabular-nums">{e.row_count}</td></tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </NeedProject>
  );
}
