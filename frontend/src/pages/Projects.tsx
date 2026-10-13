import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";
import { useProject } from "@/lib/project";
import { Badge, Button, Card, Input, Label, PageHeader } from "@/components/ui";

export default function Projects() {
  const { projects, projectId, setProjectId } = useProject();
  const qc = useQueryClient();
  const [form, setForm] = useState({ name: "", target_category: "3C", description: "", strong_search_volume: "1000", strong_product_count: "20" });
  const [err, setErr] = useState<string | null>(null);
  const create = async () => {
    setErr(null);
    try {
      const p = await api.post<Project>("/projects", {
        name: form.name,
        target_category: form.target_category,
        description: form.description,
        settings: { strong_search_volume: Number(form.strong_search_volume), strong_product_count: Number(form.strong_product_count) },
      });
      await qc.invalidateQueries({ queryKey: ["projects"] });
      setProjectId(p.id);
      setForm({ ...form, name: "", description: "" });
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const remove = async (p: Project) => {
    if (!confirm(`Delete project "${p.name}" and all its data? This cannot be undone.`)) return;
    await api.del(`/projects/${p.id}`);
    if (projectId === p.id) setProjectId(null);
    qc.invalidateQueries({ queryKey: ["projects"] });
  };
  return (
    <div>
      <PageHeader title="Projects" description="A project holds one site's current taxonomy, SRP data, competitor crawls, recommendations and review decisions." />
      <div className="grid gap-5 lg:grid-cols-3">
        <Card title="New project" className="lg:col-span-1">
          <div className="space-y-3">
            <div>
              <Label required>Name</Label>
              <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Coupang TW — 3C" />
            </div>
            <div>
              <Label>Target category</Label>
              <Input value={form.target_category} onChange={(e) => setForm({ ...form, target_category: e.target.value })} />
            </div>
            <div>
              <Label>Description</Label>
              <Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label>Strong search volume</Label>
                <Input type="number" value={form.strong_search_volume} onChange={(e) => setForm({ ...form, strong_search_volume: e.target.value })} />
              </div>
              <div>
                <Label>Strong product count</Label>
                <Input type="number" value={form.strong_product_count} onChange={(e) => setForm({ ...form, strong_product_count: e.target.value })} />
              </div>
            </div>
            <p className="text-xs text-slate-500">Thresholds used by gap scoring (+20 strong volume, +15 strong inventory).</p>
            {err && <div className="text-xs text-rose-600">{err}</div>}
            <Button onClick={create} disabled={!form.name.trim()}>
              <Plus size={14} /> Create project
            </Button>
          </div>
        </Card>
        <Card title="All projects" className="lg:col-span-2">
          <div className="divide-y divide-slate-100">
            {projects.length === 0 && <div className="text-sm text-slate-500">No projects yet.</div>}
            {projects.map((p) => (
              <div key={p.id} className="flex items-center justify-between py-2.5">
                <div>
                  <div className="text-sm font-medium">
                    {p.name} {p.id === projectId && <Badge tone="indigo">active</Badge>}
                  </div>
                  <div className="text-xs text-slate-500">
                    Target: {p.target_category || "—"} · Home label: {p.home_label_cn || "detected on import"} · created {new Date(p.created_at).toLocaleDateString()}
                  </div>
                </div>
                <div className="flex gap-2">
                  {p.id !== projectId && (
                    <Button variant="outline" size="sm" onClick={() => setProjectId(p.id)}>
                      Open
                    </Button>
                  )}
                  <Button variant="ghost" size="sm" onClick={() => remove(p)} title="Delete project">
                    <Trash2 size={13} />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
