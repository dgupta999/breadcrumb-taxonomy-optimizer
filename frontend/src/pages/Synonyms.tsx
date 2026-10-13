import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Pencil, Plus, Trash2 } from "lucide-react";
import { api, type Paged } from "@/lib/api";
import type { CategoryNode, Synonym } from "@/lib/types";
import { useProject } from "@/lib/project";
import { DataTable, FilterChips, NeedProject, NodePicker, Pager, SearchBox } from "@/components/common";
import { Badge, Button, Card, Input, Label, Modal, PageHeader } from "@/components/ui";
import { Uploader } from "./Upload";

type Form = { id?: number; alias: string; canonical: string; preferred_node_id?: number | null; preferred_category_name?: string | null; notes?: string | null; approved_by?: string | null };

export default function SynonymsPage() {
  const { projectId } = useProject();
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [src, setSrc] = useState<string[]>([]);
  const [offset, setOffset] = useState(0);
  const [form, setForm] = useState<Form | null>(null);
  const [picker, setPicker] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const { data, isLoading } = useQuery({
    queryKey: ["synonyms", projectId, q, src, offset],
    queryFn: () => api.get<Paged<Synonym>>(`/projects/${projectId}/synonyms`, { q, source: src, offset, limit: 100 }),
    enabled: !!projectId,
  });
  const save = async () => {
    if (!form) return;
    setErr(null);
    try {
      const body = { alias: form.alias, canonical: form.canonical, preferred_node_id: form.preferred_node_id || null, preferred_category_name: form.preferred_category_name || null, notes: form.notes || null, approved_by: form.approved_by || null };
      if (form.id) await api.put(`/projects/${projectId}/synonyms/${form.id}`, body);
      else await api.post(`/projects/${projectId}/synonyms`, body);
      setForm(null);
      qc.invalidateQueries({ queryKey: ["synonyms"] });
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const remove = async (s: Synonym) => {
    if (!confirm(`Delete synonym "${s.alias}"?`)) return;
    await api.del(`/projects/${projectId}/synonyms/${s.id}`);
    qc.invalidateQueries({ queryKey: ["synonyms"] });
  };
  return (
    <NeedProject>
      <PageHeader
        title="Synonyms & concepts"
        description="Alias → canonical concept (筆電 → 筆記型電腦, wifi分享器 → 無線路由器). Human-approved synonyms override defaults and AI. Re-run SRP mapping after changes."
        actions={
          <>
            <Button variant="outline" onClick={() => setImportOpen(true)}>Import</Button>
            <Button variant="outline" onClick={() => api.download(`/projects/${projectId}/synonyms/export`, { format: "xlsx" })}><Download size={14} /> Export XLSX</Button>
            <Button variant="outline" onClick={() => api.download(`/projects/${projectId}/synonyms/export`, { format: "csv" })}>CSV</Button>
            <Button onClick={() => setForm({ alias: "", canonical: "" })}><Plus size={14} /> Add synonym</Button>
          </>
        }
      />
      <Card>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-4">
            <SearchBox value={q} onChange={(v) => { setQ(v); setOffset(0); }} />
            <FilterChips label="Source" options={["HUMAN", "DEFAULT"]} value={src} onChange={(v) => { setSrc(v); setOffset(0); }} />
          </div>
          {data && <Pager total={data.total} limit={data.limit} offset={offset} onChange={setOffset} />}
        </div>
        <DataTable
          rows={data?.items || []}
          loading={isLoading}
          columns={[
            { key: "a", header: "Alias", render: (s) => <span className="font-medium">{s.alias}</span> },
            { key: "c", header: "Canonical concept", render: (s) => s.canonical },
            { key: "p", header: "Preferred category", render: (s) => s.preferred_category_name ? <span>{s.preferred_category_name} <span className="text-xs text-slate-400">#{s.preferred_node_id}</span></span> : "—" },
            { key: "n", header: "Notes", render: (s) => <span className="text-xs text-slate-600">{s.notes}</span> },
            { key: "b", header: "Approved by", render: (s) => <span className="text-xs">{s.approved_by}</span> },
            { key: "s", header: "Source", render: (s) => <Badge tone={s.source === "HUMAN" ? "green" : "gray"}>{s.source}</Badge> },
            {
              key: "x",
              header: "",
              render: (s) => (
                <div className="flex gap-1">
                  <Button size="xs" variant="ghost" onClick={() => setForm({ ...s })}><Pencil size={12} /></Button>
                  <Button size="xs" variant="ghost" onClick={() => remove(s)}><Trash2 size={12} /></Button>
                </div>
              ),
            },
          ]}
        />
      </Card>
      <Modal open={!!form} onClose={() => setForm(null)} title={form?.id ? "Edit synonym" : "Add synonym"}>
        {form && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <div><Label required>Alias</Label><Input value={form.alias} onChange={(e) => setForm({ ...form, alias: e.target.value })} placeholder="wifi router" /></div>
              <div><Label required>Canonical concept</Label><Input value={form.canonical} onChange={(e) => setForm({ ...form, canonical: e.target.value })} placeholder="無線路由器" /></div>
            </div>
            <div>
              <Label>Preferred category (optional)</Label>
              <div className="flex items-center gap-2">
                <Button variant="outline" size="sm" onClick={() => setPicker(true)}>{form.preferred_category_name || "Choose category…"}</Button>
                {form.preferred_node_id && <Button variant="ghost" size="sm" onClick={() => setForm({ ...form, preferred_node_id: null, preferred_category_name: null })}>clear</Button>}
              </div>
            </div>
            <div><Label>Notes</Label><Input value={form.notes || ""} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></div>
            <div><Label>Approved by</Label><Input value={form.approved_by || ""} onChange={(e) => setForm({ ...form, approved_by: e.target.value })} /></div>
            {err && <div className="text-xs text-rose-600">{err}</div>}
            <div className="flex justify-end gap-2"><Button variant="ghost" onClick={() => setForm(null)}>Cancel</Button><Button onClick={save} disabled={!form.alias || !form.canonical}>Save</Button></div>
            <NodePicker open={picker} onClose={() => setPicker(false)} title="Preferred category" onPick={(n: CategoryNode) => setForm({ ...form, preferred_node_id: n.id, preferred_category_name: n.name_cn })} />
          </div>
        )}
      </Modal>
      <Modal open={importOpen} onClose={() => { setImportOpen(false); qc.invalidateQueries({ queryKey: ["synonyms"] }); }} title="Import synonyms" wide>
        <Uploader kind="SYNONYMS" title="Synonym file" description="Columns: Alias, Canonical Concept, Preferred Category ID, Preferred Category Name, Notes, Approved By. Imported rows are treated as human-approved." />
      </Modal>
    </NeedProject>
  );
}
