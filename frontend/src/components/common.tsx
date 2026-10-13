import { Fragment, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronLeft, ChevronRight, ChevronRight as Caret, Download, FileSpreadsheet, Search } from "lucide-react";
import { api, type Paged } from "@/lib/api";
import type { CategoryNode, LinkChange, TreeNode } from "@/lib/types";
import { useProject } from "@/lib/project";
import { Badge, Button, Crumb, Input, Modal, Spinner, StatusBadge, cn } from "./ui";

export function ExportButtons({ exportKey, label }: { exportKey: string; label?: string }) {
  const { projectId } = useProject();
  const [busy, setBusy] = useState<string | null>(null);
  const go = async (format: "xlsx" | "csv") => {
    setBusy(format);
    try {
      await api.download(`/projects/${projectId}/exports/${exportKey}`, { format });
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="inline-flex items-center gap-1.5">
      {label && <span className="mr-1 text-xs text-slate-500">{label}</span>}
      <Button variant="outline" size="sm" onClick={() => go("xlsx")} disabled={!projectId || !!busy}>
        {busy === "xlsx" ? <Spinner /> : <FileSpreadsheet size={13} className="text-emerald-600" />} XLSX
      </Button>
      <Button variant="outline" size="sm" onClick={() => go("csv")} disabled={!projectId || !!busy}>
        {busy === "csv" ? <Spinner /> : <Download size={13} />} CSV
      </Button>
    </div>
  );
}

/** Searchable picker over the CURRENT taxonomy (only existing nodes can be chosen). */
export function NodePicker({ open, onClose, onPick, title }: { open: boolean; onClose: () => void; onPick: (n: CategoryNode) => void; title: string }) {
  const { projectId } = useProject();
  const [q, setQ] = useState("");
  const { data, isFetching } = useQuery({
    queryKey: ["node-search", projectId, q],
    queryFn: () => api.get<Paged<CategoryNode>>(`/projects/${projectId}/categories`, { q, limit: 50 }),
    enabled: open && !!projectId,
  });
  return (
    <Modal open={open} onClose={onClose} title={title} wide>
      <div className="relative mb-3">
        <Search size={14} className="absolute left-3 top-3 text-slate-400" />
        <Input autoFocus placeholder="Search category name, breadcrumb or URL…" value={q} onChange={(e) => setQ(e.target.value)} className="pl-8" />
      </div>
      <div className="max-h-[50vh] overflow-y-auto divide-y divide-slate-100 rounded-md border border-slate-200">
        {isFetching && <div className="p-3 text-xs text-slate-500"><Spinner /> searching…</div>}
        {data?.items
          .filter((n) => !n.is_root)
          .map((n) => (
            <button key={n.id} className="block w-full px-3 py-2 text-left hover:bg-indigo-50" onClick={() => { onPick(n); onClose(); }}>
              <div className="text-sm font-medium">
                {n.name_cn} {n.name_en && <span className="text-xs font-normal text-slate-500">· {n.name_en}</span>}
                {n.is_inferred && <Badge className="ml-2">breadcrumb-only</Badge>}
              </div>
              <Crumb path={n.breadcrumb_cn} />
            </button>
          ))}
        {data && data.items.length === 0 && <div className="p-3 text-sm text-slate-500">No categories match.</div>}
      </div>
    </Modal>
  );
}

export function Pager({ total, limit, offset, onChange }: { total: number; limit: number; offset: number; onChange: (o: number) => void }) {
  if (total <= limit) return <div className="text-xs text-slate-500">{total} rows</div>;
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.ceil(total / limit);
  return (
    <div className="flex items-center gap-2 text-xs text-slate-600">
      <span>
        {offset + 1}–{Math.min(total, offset + limit)} of {total}
      </span>
      <Button variant="outline" size="xs" disabled={page <= 1} onClick={() => onChange(Math.max(0, offset - limit))}>
        <ChevronLeft size={12} />
      </Button>
      <span>
        {page}/{pages}
      </span>
      <Button variant="outline" size="xs" disabled={page >= pages} onClick={() => onChange(offset + limit)}>
        <ChevronRight size={12} />
      </Button>
    </div>
  );
}

export type Column<T> = { key: string; header: ReactNode; render: (row: T) => ReactNode; className?: string };

export function DataTable<T extends { id: number }>({
  rows,
  columns,
  loading,
  empty,
  selectable,
  selected,
  onSelect,
  expand,
}: {
  rows: T[];
  columns: Column<T>[];
  loading?: boolean;
  empty?: ReactNode;
  selectable?: boolean;
  selected?: Set<number>;
  onSelect?: (s: Set<number>) => void;
  expand?: (row: T) => ReactNode;
}) {
  const [open, setOpen] = useState<Set<number>>(new Set());
  const toggle = (id: number) => {
    const n = new Set(open);
    n.has(id) ? n.delete(id) : n.add(id);
    setOpen(n);
  };
  const allSel = selectable && rows.length > 0 && rows.every((r) => selected?.has(r.id));
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="sticky top-0 bg-slate-50">
          <tr>
            {expand && <th className="w-6" />}
            {selectable && (
              <th className="w-8 px-2">
                <input
                  type="checkbox"
                  checked={!!allSel}
                  onChange={() => onSelect?.(allSel ? new Set() : new Set(rows.map((r) => r.id)))}
                />
              </th>
            )}
            {columns.map((c) => (
              <th key={c.key} className={cn("whitespace-nowrap px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-slate-500", c.className)}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white">
          {loading && (
            <tr>
              <td colSpan={columns.length + 2} className="px-3 py-6 text-center text-slate-500">
                <Spinner /> Loading…
              </td>
            </tr>
          )}
          {!loading && rows.length === 0 && (
            <tr>
              <td colSpan={columns.length + 2} className="px-3 py-8 text-center text-sm text-slate-500">
                {empty || "No rows"}
              </td>
            </tr>
          )}
          {rows.map((r) => (
            <Fragment key={r.id}>
              <tr className={cn("align-top hover:bg-slate-50/70", selected?.has(r.id) && "bg-indigo-50/50")}>
                {expand && (
                  <td className="pl-2 pt-2.5">
                    <button onClick={() => toggle(r.id)} className="text-slate-400 hover:text-slate-700" aria-label="Expand">
                      {open.has(r.id) ? <ChevronDown size={14} /> : <Caret size={14} />}
                    </button>
                  </td>
                )}
                {selectable && (
                  <td className="px-2 pt-2.5">
                    <input
                      type="checkbox"
                      checked={!!selected?.has(r.id)}
                      onChange={() => {
                        const n = new Set(selected);
                        n.has(r.id) ? n.delete(r.id) : n.add(r.id);
                        onSelect?.(n);
                      }}
                    />
                  </td>
                )}
                {columns.map((c) => (
                  <td key={c.key} className={cn("px-3 py-2", c.className)}>
                    {c.render(r)}
                  </td>
                ))}
              </tr>
              {expand && open.has(r.id) && (
                <tr className="bg-slate-50/60">
                  <td colSpan={columns.length + 2} className="px-6 py-3">
                    {expand(r)}
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Tree({ nodes, render }: { nodes: TreeNode[]; render?: (n: TreeNode) => ReactNode }) {
  return (
    <ul className="space-y-0.5">
      {nodes.map((n) => (
        <TreeItem key={n.id} node={n} render={render} depth={0} />
      ))}
    </ul>
  );
}

function TreeItem({ node, render, depth }: { node: TreeNode; render?: (n: TreeNode) => ReactNode; depth: number }) {
  const [open, setOpen] = useState(depth < 2);
  const has = node.children.length > 0;
  return (
    <li>
      <div className="flex items-center gap-1.5 rounded px-1 py-0.5 hover:bg-slate-50" style={{ paddingLeft: depth * 18 }}>
        <button className={cn("w-4 text-slate-400", !has && "invisible")} onClick={() => setOpen(!open)}>
          {open ? <ChevronDown size={14} /> : <Caret size={14} />}
        </button>
        <span className={cn("text-sm", node.is_inferred ? "italic text-slate-500" : "text-slate-800")}>{node.name_cn ?? node.name}</span>
        {node.name_en && <span className="text-xs text-slate-400">{node.name_en}</span>}
        {has && <span className="text-[11px] text-slate-400">({node.children.length})</span>}
        {render?.(node)}
      </div>
      {open && has && (
        <ul>
          {node.children.map((c) => (
            <TreeItem key={c.id} node={c} render={render} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}

export function LinkingImpact({ removed, added, level, explanation }: { removed: (LinkChange | string)[]; added: (LinkChange | string)[]; level?: string | null; explanation?: string | null }) {
  const label = (x: LinkChange | string) => (typeof x === "string" ? x : x.label);
  return (
    <div className="space-y-1 text-xs">
      <div className="flex items-center gap-2">
        <span className="text-slate-500">Internal linking:</span> <StatusBadge value={level || "NONE"} />
      </div>
      {removed.length > 0 && (
        <div className="flex flex-wrap items-center gap-1">
          <span className="text-slate-500">Links removed</span>
          {removed.map((x, i) => (
            <Badge key={i} tone={typeof x !== "string" && x.irrelevant ? "red" : "gray"} className="line-through decoration-rose-400">
              {label(x)}
            </Badge>
          ))}
        </div>
      )}
      {added.length > 0 && (
        <div className="flex flex-wrap items-center gap-1">
          <span className="text-slate-500">Links added</span>
          {added.map((x, i) => (
            <Badge key={i} tone="green">
              + {label(x)}
              {typeof x !== "string" && x.new_page ? " (new page)" : ""}
            </Badge>
          ))}
        </div>
      )}
      {explanation && <div className="text-slate-600">{explanation}</div>}
    </div>
  );
}

export function FilterChips({ options, value, onChange, label }: { options: string[]; value: string[]; onChange: (v: string[]) => void; label?: string }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {label && <span className="mr-1 text-xs font-medium text-slate-500">{label}</span>}
      {options.map((o) => {
        const on = value.includes(o);
        return (
          <button
            key={o}
            onClick={() => onChange(on ? value.filter((v) => v !== o) : [...value, o])}
            className={cn(
              "rounded-full border px-2.5 py-0.5 text-[11px] font-medium transition-colors",
              on ? "border-indigo-500 bg-indigo-50 text-indigo-700" : "border-slate-200 bg-white text-slate-600 hover:border-slate-300",
            )}
          >
            {o.replace(/_/g, " ")}
          </button>
        );
      })}
    </div>
  );
}

export function SearchBox({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <div className="relative w-64">
      <Search size={14} className="absolute left-2.5 top-2.5 text-slate-400" />
      <Input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder || "Search…"} className="py-1.5 pl-8" />
    </div>
  );
}

export function NeedProject({ children }: { children: ReactNode }) {
  const { projectId } = useProject();
  if (!projectId)
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-white p-10 text-center">
        <p className="text-sm text-slate-600">Create or select a project first.</p>
        <a href="/projects" className="mt-3 inline-block text-sm font-medium text-indigo-600">
          Go to Projects →
        </a>
      </div>
    );
  return <>{children}</>;
}
