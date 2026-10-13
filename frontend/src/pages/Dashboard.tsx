import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Circle } from "lucide-react";
import { api } from "@/lib/api";
import { useProject } from "@/lib/project";
import type { Job } from "@/lib/types";
import { NeedProject } from "@/components/common";
import { JobProgress } from "@/components/jobs";
import { Badge, Card, PageHeader, Stat, StatusBadge } from "@/components/ui";

type Dash = {
  taxonomy: { nodes: number; max_depth: number; inferred: number };
  srps: { total: number; mapped: number; by_band: Record<string, number>; duplicates: Record<string, number>; volume: number };
  audit: { by_action: Record<string, number>; by_linking: Record<string, number>; avg_current: number; avg_recommended: number };
  competitors: { competitor: string; status: string; processed: number; discovered: number; errors: number; categories: number }[];
  mappings: Record<string, number>;
  gaps: { by_type: Record<string, number>; by_priority: Record<string, number> };
  review_pending: number;
  steps: { step: number; title: string; done: boolean; page: string }[];
  recent_jobs: Job[];
  llm_available: boolean;
};

const PAGE: Record<string, string> = {
  upload: "/upload", srp: "/srp", audit: "/audit", crawl: "/crawl", "competitor-taxonomy": "/competitor-taxonomy",
  "competitor-mapping": "/competitor-mapping", gaps: "/gaps", review: "/review", exports: "/exports",
};

function Bars({ data, order }: { data: Record<string, number>; order?: string[] }) {
  const keys = (order || Object.keys(data)).filter((k) => data[k]);
  const max = Math.max(1, ...keys.map((k) => data[k] || 0));
  if (!keys.length) return <div className="text-xs text-slate-400">No data yet</div>;
  return (
    <div className="space-y-1.5">
      {keys.map((k) => (
        <div key={k} className="flex items-center gap-2 text-xs">
          <span className="w-44 truncate text-slate-600">{k.replace(/_/g, " ")}</span>
          <div className="h-2 flex-1 overflow-hidden rounded bg-slate-100">
            <div className="h-full rounded bg-indigo-500" style={{ width: `${(100 * (data[k] || 0)) / max}%` }} />
          </div>
          <span className="w-8 text-right tabular-nums text-slate-700">{data[k]}</span>
        </div>
      ))}
    </div>
  );
}

export default function Dashboard() {
  const { projectId, project } = useProject();
  const { data } = useQuery({
    queryKey: ["dashboard", projectId],
    queryFn: () => api.get<Dash>(`/projects/${projectId}/dashboard`),
    enabled: !!projectId,
    refetchInterval: (q) => (q.state.data?.recent_jobs?.some((j) => ["QUEUED", "RUNNING"].includes(j.status)) ? 5000 : 60000),
  });
  return (
    <NeedProject>
      <PageHeader title={project?.name || "Dashboard"} description="Workflow status for this project. Each step links to the page where it runs; every stage can be exported to Excel." />
      {data && (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <Stat label="Current taxonomy nodes" value={data.taxonomy.nodes} hint={`max depth ${data.taxonomy.max_depth} · ${data.taxonomy.inferred} breadcrumb-only`} />
            <Stat label="SRPs mapped" value={`${data.srps.mapped}/${data.srps.total}`} hint={`${(data.srps.by_band.AUTO_APPROVED || 0)} auto-approved`} />
            <Stat label="Avg breadcrumb score" value={`${data.audit.avg_current} → ${data.audit.avg_recommended}`} hint="current → recommended" />
            <Stat label="Taxonomy gaps" value={Object.values(data.gaps.by_type).reduce((a, b) => a + b, 0)} hint={`${data.gaps.by_priority.HIGH || 0} high priority`} />
            <Stat label="Awaiting review" value={data.review_pending} tone={data.review_pending ? "text-amber-600" : undefined} hint={<Link to="/review" className="text-indigo-600">Open review queue →</Link>} />
          </div>

          <div className="grid gap-5 lg:grid-cols-3">
            <Card title="Workflow" subtitle="15-step project workflow" className="lg:col-span-1">
              <ol className="space-y-1">
                {data.steps.map((s) => (
                  <li key={s.step}>
                    <Link to={PAGE[s.page] || "/"} className="flex items-center gap-2 rounded px-1.5 py-1 text-[13px] hover:bg-slate-50">
                      {s.done ? <CheckCircle2 size={15} className="text-emerald-500" /> : <Circle size={15} className="text-slate-300" />}
                      <span className="w-5 text-xs tabular-nums text-slate-400">{s.step}</span>
                      <span className={s.done ? "text-slate-700" : "text-slate-500"}>{s.title}</span>
                    </Link>
                  </li>
                ))}
              </ol>
            </Card>
            <div className="space-y-5 lg:col-span-2">
              <div className="grid gap-5 md:grid-cols-2">
                <Card title="SRP confidence">
                  <Bars data={data.srps.by_band} order={["AUTO_APPROVED", "NEEDS_REVIEW", "LOW_CONFIDENCE", "NO_MATCH"]} />
                  <div className="mt-3 flex gap-2 text-xs text-slate-500">
                    Duplicate intent: <Badge tone="red">YES {data.srps.duplicates.YES || 0}</Badge> <Badge tone="amber">POTENTIAL {data.srps.duplicates.POTENTIAL || 0}</Badge>
                  </div>
                </Card>
                <Card title="Breadcrumb audit actions">
                  <Bars data={data.audit.by_action} order={["KEEP", "MOVE", "FLATTEN", "MOVE + CREATE PARENT", "CREATE PARENT", "CREATE CHILD", "CONSOLIDATE", "REVIEW"]} />
                </Card>
                <Card title="Taxonomy gaps">
                  <Bars data={data.gaps.by_type} order={["MISSING PARENT", "MISSING CHILD", "BOTH MISSING", "MISPLACED EXISTING CATEGORY", "DUPLICATE", "SRP-ONLY GAP"]} />
                </Card>
                <Card title="Competitor vs current">
                  <Bars data={data.mappings} />
                </Card>
              </div>
              <Card title="Competitor crawls">
                {data.competitors.length === 0 ? (
                  <div className="text-sm text-slate-500">
                    No competitors yet. <Link to="/crawl" className="text-indigo-600">Add MOMO / PChome start URLs →</Link>
                  </div>
                ) : (
                  <table className="w-full text-sm">
                    <thead className="text-left text-[11px] uppercase text-slate-500">
                      <tr><th className="py-1">Competitor</th><th>Status</th><th>Processed</th><th>Discovered</th><th>Errors</th><th>Categories</th></tr>
                    </thead>
                    <tbody>
                      {data.competitors.map((c) => (
                        <tr key={c.competitor} className="border-t border-slate-100">
                          <td className="py-1.5 font-medium">{c.competitor}</td>
                          <td><StatusBadge value={c.status} /></td>
                          <td className="tabular-nums">{c.processed}</td>
                          <td className="tabular-nums">{c.discovered}</td>
                          <td className="tabular-nums">{c.errors}</td>
                          <td className="tabular-nums">{c.categories}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </Card>
              <Card title="Recent jobs">
                <div className="space-y-1.5">
                  {data.recent_jobs.length === 0 && <div className="text-sm text-slate-500">No jobs yet.</div>}
                  {data.recent_jobs.map((j) => (
                    <JobProgress key={j.id} job={j} compact />
                  ))}
                </div>
              </Card>
            </div>
          </div>
        </div>
      )}
    </NeedProject>
  );
}
