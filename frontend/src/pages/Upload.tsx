import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FileUp } from "lucide-react";
import { api, type Paged } from "@/lib/api";
import type { CategoryNode, Job, TreeNode } from "@/lib/types";
import { useProject } from "@/lib/project";
import { DataTable, ExportButtons, NeedProject, Pager, SearchBox, Tree } from "@/components/common";
import { JobProgress, useJob } from "@/components/jobs";
import { Badge, Button, Card, Crumb, Label, PageHeader, Select } from "@/components/ui";

type Field = { field: string; label: string; required: boolean };
type UploadResp = { id: number; kind: string; filename: string; columns: string[]; row_count: number; mapping: Record<string, string | null>; sample: Record<string, string | null>[]; fields: Field[] };

export function Uploader({ kind, title, description, then }: { kind: "TAXONOMY" | "SRP" | "SYNONYMS"; title: string; description: string; then?: string[] }) {
  const { projectId } = useProject();
  const [up, setUp] = useState<UploadResp | null>(null);
  const [mapping, setMapping] = useState<Record<string, string | null>>({});
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [jobId, setJobId] = useState<number | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const job = useJob(jobId);

  const onFile = async (f: File) => {
    setErr(null);
    setDone(null);
    setBusy(true);
    const fd = new FormData();
    fd.append("kind", kind);
    fd.append("file", f);
    try {
      const r = await api.upload<UploadResp>(`/projects/${projectId}/uploads`, fd);
      setUp(r);
      setMapping(r.mapping);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const commit = async () => {
    if (!up) return;
    setErr(null);
    try {
      const r = await api.post<Job | { imported: { imported: number } }>(`/projects/${projectId}/uploads/${up.id}/commit`, {
        mapping,
        then: (then || []).map((t) => ({ job_type: t })),
      });
      if ("id" in r) setJobId(r.id);
      else setDone(`Imported ${r.imported.imported} rows`);
      setUp(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  return (
    <Card title={title} subtitle={description}>
      {!up && (
        <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-sm text-slate-600 hover:border-indigo-400 hover:bg-indigo-50/40">
          <FileUp size={22} className="text-slate-400" />
          <span>{busy ? "Reading file…" : "Choose a CSV or XLSX file"}</span>
          <input type="file" accept=".csv,.xlsx,.xlsm,.tsv,.txt" className="hidden" onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])} />
        </label>
      )}
      {up && (
        <div className="space-y-4">
          <div className="text-sm">
            <span className="font-medium">{up.filename}</span> · {up.row_count} rows · {up.columns.length} columns
          </div>
          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Column mapping</div>
            <div className="grid gap-x-4 gap-y-2.5 sm:grid-cols-2">
              {up.fields.map((f) => (
                <div key={f.field}>
                  <Label required={f.required}>{f.label}</Label>
                  <Select className="w-full" value={mapping[f.field] || ""} onChange={(e) => setMapping({ ...mapping, [f.field]: e.target.value || null })}>
                    <option value="">— not mapped —</option>
                    {up.columns.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </Select>
                </div>
              ))}
            </div>
          </div>
          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Preview</div>
            <div className="max-h-56 overflow-auto rounded border border-slate-200">
              <table className="min-w-full text-xs">
                <thead className="bg-slate-50">
                  <tr>
                    {up.columns.map((c) => (
                      <th key={c} className="whitespace-nowrap px-2 py-1.5 text-left font-semibold text-slate-600">
                        {c}
                        {Object.entries(mapping).some(([, v]) => v === c) && <Badge tone="indigo" className="ml-1">mapped</Badge>}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {up.sample.map((r, i) => (
                    <tr key={i} className="border-t border-slate-100">
                      {up.columns.map((c) => (
                        <td key={c} className="max-w-[260px] truncate whitespace-nowrap px-2 py-1">
                          {r[c] ?? ""}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <div className="flex gap-2">
            <Button onClick={commit}>Import {up.row_count} rows</Button>
            <Button variant="ghost" onClick={() => setUp(null)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
      {err && <div className="mt-3 text-sm text-rose-600">{err}</div>}
      {done && <div className="mt-3 text-sm text-emerald-700">{done}</div>}
      {job && (
        <div className="mt-3">
          <JobProgress job={job} />
          {job.status === "COMPLETED" && job.result && (
            <pre className="mt-2 max-h-40 overflow-auto rounded bg-slate-50 p-2 text-[11px] text-slate-600">{JSON.stringify(job.result, null, 1)}</pre>
          )}
        </div>
      )}
    </Card>
  );
}

export default function UploadPage() {
  const { projectId } = useProject();
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [view, setView] = useState<"tree" | "table">("tree");
  const tree = useQuery({ queryKey: ["tree", projectId], queryFn: () => api.get<TreeNode[]>(`/projects/${projectId}/categories/tree`), enabled: !!projectId && view === "tree" });
  const table = useQuery({
    queryKey: ["categories", projectId, q, offset],
    queryFn: () => api.get<Paged<CategoryNode>>(`/projects/${projectId}/categories`, { q, offset, limit: 100 }),
    enabled: !!projectId && view === "table",
  });
  return (
    <NeedProject>
      <PageHeader
        step="Steps 1–3"
        title="Upload taxonomy & SRP data"
        description="The uploaded category taxonomy is the source of truth for the current state. Breadcrumbs are parsed into a tree but never modified."
      />
      <div className="grid gap-5 xl:grid-cols-2">
        <Uploader
          kind="TAXONOMY"
          title="1 · Current category taxonomy"
          description="Required: Category URL, Category Name or H1, Breadcrumb. Optional: IDs, EN names/breadcrumbs, Parent, Product Count, Status."
        />
        <Uploader
          kind="SRP"
          title="2 · SRP / search-result page data"
          description="Required: SRP Keyword, SRP URL. Optional: H1, English Keyword, Search Volume, Product Count."
          then={["MAP_SRP"]}
        />
      </div>
      <Card
        className="mt-5"
        title="3 · Current taxonomy tree"
        subtitle="Italic nodes appear only inside breadcrumbs (no row of their own)."
        actions={
          <>
            <div className="flex rounded-md border border-slate-200 p-0.5 text-xs">
              {(["tree", "table"] as const).map((v) => (
                <button key={v} onClick={() => setView(v)} className={`rounded px-2.5 py-1 ${view === v ? "bg-slate-800 text-white" : "text-slate-600"}`}>
                  {v === "tree" ? "Tree" : "Table"}
                </button>
              ))}
            </div>
            <ExportButtons exportKey="current_taxonomy_tree" />
          </>
        }
      >
        {view === "tree" ? (
          tree.data && tree.data.length ? (
            <Tree nodes={tree.data} render={(n) => (n.product_count ? <span className="text-[11px] text-slate-400">· {n.product_count} products</span> : null)} />
          ) : (
            <div className="text-sm text-slate-500">Upload a taxonomy to build the tree.</div>
          )
        ) : (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <SearchBox value={q} onChange={(v) => { setQ(v); setOffset(0); }} placeholder="Search categories…" />
              {table.data && <Pager total={table.data.total} limit={table.data.limit} offset={offset} onChange={setOffset} />}
            </div>
            <DataTable
              rows={table.data?.items || []}
              loading={table.isLoading}
              columns={[
                { key: "name", header: "Category", render: (n) => <div><div className="font-medium">{n.name_cn}</div><div className="text-xs text-slate-500">{n.name_en}</div></div> },
                { key: "bc", header: "Breadcrumb CN / EN", render: (n) => <div><Crumb path={n.breadcrumb_cn} /><div className="text-[11px] text-slate-400">{n.breadcrumb_en}</div></div> },
                { key: "d", header: "Depth", render: (n) => n.depth },
                { key: "c", header: "Children", render: (n) => n.children_count },
                { key: "p", header: "Products", render: (n) => n.product_count ?? "—" },
                { key: "u", header: "URL", render: (n) => n.url ? <a href={n.url} target="_blank" rel="noreferrer" className="text-xs text-indigo-600 hover:underline">open</a> : <Badge>breadcrumb-only</Badge> },
              ]}
            />
          </div>
        )}
      </Card>
    </NeedProject>
  );
}
