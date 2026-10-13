import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, FileSpreadsheet } from "lucide-react";
import { api } from "@/lib/api";
import { ExportButtons, MasterButtons, NeedProject } from "@/components/common";
import { Card, Input, Label, PageHeader } from "@/components/ui";

const DESC: Record<string, string> = {
  competitor_gap_pages: "Every new page to create (or existing page to move) with its breadcrumb in Coupang's hierarchy.",
  current_taxonomy_tree: "Parsed hierarchy of your current categories.",
  breadcrumb_audit: "Every category: issues, action, recommended breadcrumb, quality score, linking impact.",
  srp_breadcrumb_mapping: "Every SRP with matched category, CN/EN breadcrumb, confidence, duplicate intent.",
  srp_review_queue: "SRPs needing review with top candidates.",
  competitor_crawl_raw: "Every uploaded competitor URL with breadcrumb and page type.",
  competitor_clean_categories: "Only competitor category pages.",
  competitor_taxonomy_tree: "Reconstructed competitor hierarchy.",
  competitor_vs_current: "Competitor categories classified against your taxonomy.",
  taxonomy_gap_analysis: "All gaps with SRP validation, evidence and scoring.",
  parent_child_gap_analysis: "One row per child with parent/child status.",
  breadcrumb_optimization_recommendations: "Audit + gap recommendations ranked by linking improvement.",
  final_approved_taxonomy: "Taxonomy with approved changes applied.",
  final_approved_srp_mapping: "Approved SRP mappings with final breadcrumbs.",
};

export default function ExportsPage() {
  const [category, setCategory] = useState("");
  const [open, setOpen] = useState(false);
  const { data } = useQuery({ queryKey: ["export-catalog"], queryFn: () => api.get<{ key: string; title: string; number: number }[]>("/exports") });
  return (
    <NeedProject>
      <PageHeader step="Step 15" title="Master Excel" description="One workbook with everything: existing category pages, new pages to create, and SRP pages — each marked EXISTING / NEW / MOVE / MERGE / DUPLICATE, with current and final breadcrumbs (CN/EN), competitor coverage, search volume and the action. Rows follow the final hierarchy." />
      <Card>
        <div className="flex flex-wrap items-end gap-3">
          <div className="w-72">
            <Label>Category (optional — leave empty for the whole taxonomy)</Label>
            <Input value={category} onChange={(e) => setCategory(e.target.value)} placeholder="e.g. 3C, 電腦周邊, 滑鼠" />
          </div>
          <MasterButtons category={category.trim() || undefined} label={category.trim() ? `Download master — ${category.trim()}` : "Download master — all categories"} />
        </div>
        <ul className="mt-4 grid gap-1 text-xs text-slate-600 md:grid-cols-2">
          <li><b>Row Type</b>: Category or SRP</li>
          <li><b>Status</b>: EXISTING · NEW · EXISTING → MOVE · EXISTING → MERGE · SRP DUPLICATE · SRP → NEW CATEGORY …</li>
          <li><b>Tree</b>: indented final hierarchy — SRPs (🔎) sit under their category</li>
          <li><b>Current vs Final breadcrumb</b> (CN and EN), final parent and level</li>
          <li><b>Competitors</b> that have the page, with their breadcrumbs</li>
          <li><b>Search volume, SRP count, priority, confidence, action</b>; plus a Summary sheet</li>
        </ul>
      </Card>

      <button onClick={() => setOpen(!open)} className="mt-6 flex items-center gap-1 text-sm font-medium text-slate-600 hover:text-slate-900">
        {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />} Individual exports (advanced)
      </button>
      {open && (
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          {data?.map((e) => (
            <div key={e.key} className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2">
              <div className="flex items-start gap-2">
                <FileSpreadsheet size={15} className="mt-0.5 shrink-0 text-emerald-600" />
                <div>
                  <div className="text-xs font-semibold">{e.title}</div>
                  <div className="text-[11px] text-slate-500">{DESC[e.key]}</div>
                </div>
              </div>
              <ExportButtons exportKey={e.key} />
            </div>
          ))}
        </div>
      )}
    </NeedProject>
  );
}
