import { useQuery } from "@tanstack/react-query";
import { FileSpreadsheet } from "lucide-react";
import { api } from "@/lib/api";
import { ExportButtons, NeedProject } from "@/components/common";
import { Card, PageHeader } from "@/components/ui";

const DESC: Record<string, string> = {
  current_taxonomy_tree: "Parsed hierarchy of your current categories + indented tree view.",
  breadcrumb_audit: "Every category: issues, action, recommended breadcrumb, quality score breakdown, linking impact.",
  srp_breadcrumb_mapping: "Every SRP with core product, matched category, CN/EN breadcrumb, confidence, duplicate intent.",
  srp_review_queue: "SRPs needing review with top candidates and blank reviewer columns.",
  competitor_crawl_raw: "Every crawled URL: status, canonical, indexability, breadcrumb, page type, child links.",
  competitor_clean_categories: "Only CATEGORY / SUBCATEGORY pages used for taxonomy analysis.",
  competitor_taxonomy_tree: "Reconstructed competitor hierarchy with hierarchy source.",
  competitor_vs_current: "Competitor categories classified against your taxonomy + summary per competitor.",
  taxonomy_gap_analysis: "All gaps with SRP validation, competitor evidence, score breakdown, priority, linking impact.",
  parent_child_gap_analysis: "One row per child: parent/child status, existing + suggested CN/EN breadcrumbs, MOMO/PChome evidence.",
  breadcrumb_optimization_recommendations: "Combined audit + gap recommendations ranked by internal-linking improvement.",
  final_approved_taxonomy: "Your taxonomy with approved moves, new parents/children, flattening and consolidations applied.",
  final_approved_srp_mapping: "Approved + auto-approved SRP mappings with final breadcrumbs and indexing recommendation.",
};

export default function ExportsPage() {
  const { data } = useQuery({ queryKey: ["export-catalog"], queryFn: () => api.get<{ key: string; title: string; number: number }[]>("/exports") });
  return (
    <NeedProject>
      <PageHeader step="Step 15" title="Excel exports" description="Every stage downloads as XLSX (bold headers, autofilter, frozen first row) or CSV (UTF-8 with BOM so Chinese text opens correctly in Excel)." />
      <div className="grid gap-3 md:grid-cols-2">
        {data?.map((e) => (
          <Card key={e.key}>
            <div className="flex items-start justify-between gap-3">
              <div className="flex gap-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600"><FileSpreadsheet size={18} /></div>
                <div>
                  <div className="text-sm font-semibold">{e.number}. {e.title}.xlsx</div>
                  <div className="mt-0.5 text-xs text-slate-500">{DESC[e.key]}</div>
                </div>
              </div>
              <ExportButtons exportKey={e.key} />
            </div>
          </Card>
        ))}
      </div>
    </NeedProject>
  );
}
