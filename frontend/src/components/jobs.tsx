import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Square } from "lucide-react";
import { api } from "@/lib/api";
import type { Job } from "@/lib/types";
import type { Paged } from "@/lib/api";
import { useProject } from "@/lib/project";
import { Button, Spinner, StatusBadge, cn } from "./ui";

const ACTIVE = new Set(["QUEUED", "RUNNING", "CANCEL_REQUESTED"]);

export function useJob(jobId: number | null, onDone?: (j: Job) => void) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.get<Job>(`/jobs/${jobId}`),
    enabled: jobId !== null,
    refetchInterval: (query) => (query.state.data && !ACTIVE.has(query.state.data.status) ? false : 1500),
  });
  const [notified, setNotified] = useState<number | null>(null);
  useEffect(() => {
    const j = q.data;
    if (j && !ACTIVE.has(j.status) && notified !== j.id) {
      setNotified(j.id);
      qc.invalidateQueries({ predicate: (qq) => qq.queryKey[0] !== "job" });
      onDone?.(j);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q.data?.status, q.data?.id]);
  return q.data;
}

/** Latest job of a type for the current project (so progress survives page reloads). */
export function useLatestJob(jobType: string) {
  const { projectId } = useProject();
  return useQuery({
    queryKey: ["jobs", projectId, jobType],
    queryFn: () => api.get<Paged<Job>>(`/projects/${projectId}/jobs`, { job_type: jobType, limit: 1 }),
    enabled: !!projectId,
    select: (d) => d.items[0] as Job | undefined,
    refetchInterval: (query) => {
      const j = query.state.data?.items?.[0];
      return j && ACTIVE.has(j.status) ? 1500 : false;
    },
  });
}

export function JobProgress({ job, compact }: { job?: Job | null; compact?: boolean }) {
  if (!job) return null;
  const running = ACTIVE.has(job.status);
  const crawl = job.crawl;
  return (
    <div className={cn("rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs", compact && "py-1.5")}>
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge value={job.status} />
        <span className="font-medium text-slate-700">{job.job_type.replace(/_/g, " ")}</span>
        <span className="text-slate-400">#{job.id}</span>
        {running && <Spinner className="text-indigo-500" />}
        {job.total_items > 0 && (
          <span className="tabular-nums text-slate-600">
            {job.processed_items}/{job.total_items}
          </span>
        )}
        {crawl && (
          <span className="tabular-nums text-slate-600">
            processed {crawl.processed_urls} · discovered {crawl.discovered_urls} · errors {crawl.error_count}
            {crawl.skipped_robots ? ` · robots-blocked ${crawl.skipped_robots}` : ""}
          </span>
        )}
        {job.message && !crawl && <span className="text-slate-500">{job.message}</span>}
      </div>
      {running && (
        <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-200">
          <div className="h-full rounded-full bg-indigo-500 transition-all" style={{ width: `${Math.max(3, job.progress || 0)}%` }} />
        </div>
      )}
      {job.status === "FAILED" && <div className="mt-1 text-rose-600">{job.error_message}</div>}
    </div>
  );
}

/** Button that queues a job and shows its live progress underneath. */
export function JobRunner({
  jobType,
  label,
  params,
  disabled,
  variant = "primary",
  hint,
}: {
  jobType: string;
  label: string;
  params?: Record<string, unknown>;
  disabled?: boolean;
  variant?: "primary" | "secondary" | "outline";
  hint?: string;
}) {
  const { projectId } = useProject();
  const latest = useLatestJob(jobType);
  const [jobId, setJobId] = useState<number | null>(null);
  const live = useJob(jobId ?? latest.data?.id ?? null);
  const job = live ?? latest.data;
  const running = !!job && ACTIVE.has(job.status);
  const [err, setErr] = useState<string | null>(null);
  const start = async () => {
    setErr(null);
    try {
      const j = await api.post<Job>(`/projects/${projectId}/jobs`, { job_type: jobType, params: params || {} });
      setJobId(j.id);
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const cancel = async () => job && (await api.post(`/jobs/${job.id}/cancel`));
  return (
    <div className="flex min-w-[260px] flex-col gap-1.5">
      <div className="flex items-center gap-2">
        <Button variant={variant} onClick={start} disabled={disabled || running || !projectId} title={hint}>
          {running ? <Spinner /> : <Play size={14} />} {label}
        </Button>
        {running && (
          <Button variant="ghost" size="sm" onClick={cancel}>
            <Square size={12} /> Cancel
          </Button>
        )}
      </div>
      {job && <JobProgress job={job} compact />}
      {err && <div className="text-xs text-rose-600">{err}</div>}
    </div>
  );
}
