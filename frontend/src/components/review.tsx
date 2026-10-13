import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, X } from "lucide-react";
import { api } from "@/lib/api";
import type { CategoryNode, EntityType } from "@/lib/types";
import { useProject } from "@/lib/project";
import { NodePicker } from "./common";
import { Button, Input, Label, Modal, Spinner } from "./ui";

const LABELS: Record<string, string> = {
  APPROVE: "Approve",
  REJECT: "Reject",
  CHANGE_CATEGORY: "Change Category",
  CHANGE_PARENT: "Change Parent",
  MARK_DUPLICATE: "Mark Duplicate",
  MARK_TAXONOMY_GAP: "Mark Taxonomy Gap",
  CREATE_PARENT: "Create Parent",
  CREATE_CHILD: "Create Child",
  MOVE_EXISTING: "Move Existing Category",
  KEEP_EXISTING: "Keep Existing Breadcrumb",
};

const MENU: Record<EntityType, string[]> = {
  srp: ["CHANGE_CATEGORY", "MARK_DUPLICATE", "MARK_TAXONOMY_GAP", "CREATE_CHILD", "KEEP_EXISTING"],
  audit: ["CHANGE_PARENT", "MOVE_EXISTING", "CREATE_PARENT", "CREATE_CHILD", "MARK_DUPLICATE", "KEEP_EXISTING"],
  gap: ["CHANGE_PARENT", "CREATE_PARENT", "CREATE_CHILD", "MOVE_EXISTING", "MARK_DUPLICATE", "KEEP_EXISTING"],
  competitor_mapping: ["CHANGE_CATEGORY", "MARK_DUPLICATE", "MARK_TAXONOMY_GAP"],
};

const NEEDS_NODE = new Set(["CHANGE_CATEGORY", "CHANGE_PARENT", "MOVE_EXISTING"]);
const OPTIONAL_NODE: Record<string, string> = { MARK_DUPLICATE: "Choose the existing category it duplicates" };
const NEEDS_TEXT: Record<string, { field: string; label: string }> = {
  CREATE_PARENT: { field: "parent_name", label: "New parent category name (CN)" },
  CREATE_CHILD: { field: "child_name", label: "New child category name (CN)" },
};

export function useReview() {
  const { projectId } = useProject();
  const qc = useQueryClient();
  return async (entity_type: EntityType, ids: number[], action: string, payload: Record<string, unknown> = {}) => {
    await api.post(`/projects/${projectId}/review`, { entity_type, entity_ids: ids, action, payload, reviewer: localStorageName() });
    await qc.invalidateQueries();
  };
}

function localStorageName(): string {
  try {
    return localStorage.getItem("bto.reviewer") || "reviewer";
  } catch {
    return "reviewer";
  }
}

export function ReviewActions({ entityType, ids, compact, defaultName }: { entityType: EntityType; ids: number[]; compact?: boolean; defaultName?: string }) {
  const review = useReview();
  const [busy, setBusy] = useState<string | null>(null);
  const [menu, setMenu] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [node, setNode] = useState<CategoryNode | null>(null);
  const [picker, setPicker] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const run = async (action: string, payload: Record<string, unknown> = {}) => {
    setBusy(action);
    setErr(null);
    try {
      await review(entityType, ids, action, payload);
      setPending(null);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const choose = (action: string) => {
    setMenu(false);
    if (NEEDS_NODE.has(action)) {
      setPending(action);
      setPicker(true);
    } else if (NEEDS_TEXT[action] || OPTIONAL_NODE[action]) {
      setText(defaultName || "");
      setNode(null);
      setPending(action);
    } else run(action);
  };

  return (
    <div className="relative inline-flex flex-col items-start gap-1">
      <div className="inline-flex items-center gap-1">
        <Button size="xs" variant="success" onClick={() => run("APPROVE")} disabled={!!busy || ids.length === 0} title="Approve">
          {busy === "APPROVE" ? <Spinner /> : <Check size={12} />} {!compact && "Approve"}
        </Button>
        <Button size="xs" variant="outline" onClick={() => run("REJECT")} disabled={!!busy || ids.length === 0} title="Reject">
          {busy === "REJECT" ? <Spinner /> : <X size={12} />} {!compact && "Reject"}
        </Button>
        <Button size="xs" variant="ghost" onClick={() => setMenu(!menu)} disabled={ids.length === 0}>
          More <ChevronDown size={12} />
        </Button>
      </div>
      {menu && (
        <div className="absolute right-0 top-7 z-30 w-56 rounded-md border border-slate-200 bg-white py-1 shadow-lg" onMouseLeave={() => setMenu(false)}>
          {MENU[entityType].map((a) => (
            <button key={a} onClick={() => choose(a)} className="block w-full px-3 py-1.5 text-left text-xs hover:bg-indigo-50">
              {LABELS[a]}
            </button>
          ))}
        </div>
      )}
      {err && <div className="max-w-[220px] text-[11px] text-rose-600">{err}</div>}
      <NodePicker
        open={picker && !!pending && NEEDS_NODE.has(pending)}
        onClose={() => {
          setPicker(false);
          setPending(null);
        }}
        title={pending ? LABELS[pending] : "Choose category"}
        onPick={(n) => pending && run(pending, { node_id: n.id })}
      />
      <Modal open={!!pending && !picker && !NEEDS_NODE.has(pending)} onClose={() => setPending(null)} title={pending ? LABELS[pending] : ""}>
        {pending && NEEDS_TEXT[pending] && (
          <div className="mb-3">
            <Label required>{NEEDS_TEXT[pending].label}</Label>
            <Input value={text} onChange={(e) => setText(e.target.value)} autoFocus />
          </div>
        )}
        {pending && (
          <div className="mb-4">
            <Label required={!!OPTIONAL_NODE[pending] && entityType !== "srp"}>
              {OPTIONAL_NODE[pending] || (pending === "CREATE_PARENT" ? "Place new parent under (optional — defaults to current parent)" : "Place under existing category (optional)")}
            </Label>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={() => setPicker(true)}>
                {node ? node.name_cn : "Choose category…"}
              </Button>
              {node && <span className="text-xs text-slate-500">{node.breadcrumb_cn}</span>}
            </div>
          </div>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setPending(null)}>
            Cancel
          </Button>
          <Button
            onClick={() => pending && run(pending, { ...(NEEDS_TEXT[pending] ? { [NEEDS_TEXT[pending].field]: text } : {}), ...(node ? { node_id: node.id } : {}) })}
            disabled={!!busy || (!!pending && !!NEEDS_TEXT[pending] && !text.trim())}
          >
            {busy ? <Spinner /> : null} Save decision
          </Button>
        </div>
        <NodePicker open={picker && !!pending && !NEEDS_NODE.has(pending)} onClose={() => setPicker(false)} title="Choose category" onPick={(n) => setNode(n)} />
      </Modal>
    </div>
  );
}
