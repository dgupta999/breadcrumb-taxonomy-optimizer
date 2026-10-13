import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Competitor, TreeNode } from "@/lib/types";
import { useProject } from "@/lib/project";
import { ExportButtons, NeedProject, Tree } from "@/components/common";
import { JobRunner } from "@/components/jobs";
import { Card, PageHeader, StatusBadge } from "@/components/ui";

export default function CompetitorTaxonomy() {
  const { projectId } = useProject();
  const comps = useQuery({ queryKey: ["competitors", projectId], queryFn: () => api.get<Competitor[]>(`/projects/${projectId}/competitors`), enabled: !!projectId });
  const [cid, setCid] = useState<number | null>(null);
  const active = cid ?? comps.data?.[0]?.id ?? null;
  const tree = useQuery({
    queryKey: ["comp-tree", projectId, active],
    queryFn: () => api.get<TreeNode[]>(`/projects/${projectId}/competitor-categories/tree`, { competitor_id: active }),
    enabled: !!projectId && !!active,
  });
  return (
    <NeedProject>
      <PageHeader
        step="Step 8"
        title="Competitor taxonomy trees"
        description="Hierarchy priority: breadcrumb → parent/child crawl relationship → parent anchor text → H1 → URL structure. Trees are rebuilt automatically after each crawl. Badges show how each node compares with your taxonomy (after Competitor Mapping)."
        actions={
          <>
            <JobRunner jobType="BUILD_COMPETITOR_TREE" label="Rebuild trees" variant="outline" />
            <ExportButtons exportKey="competitor_taxonomy_tree" />
          </>
        }
      />
      <div className="mb-4 flex flex-wrap gap-2">
        {comps.data?.map((c) => (
          <button
            key={c.id}
            onClick={() => setCid(c.id)}
            className={`rounded-full border px-3 py-1 text-sm ${active === c.id ? "border-indigo-500 bg-indigo-50 text-indigo-700" : "border-slate-200 bg-white text-slate-600"}`}
          >
            {c.name} <span className="text-xs text-slate-400">({c.categories})</span>
          </button>
        ))}
      </div>
      <Card title="Hierarchy">
        {!active && <div className="text-sm text-slate-500">Add and crawl a competitor first.</div>}
        {tree.data && tree.data.length === 0 && <div className="text-sm text-slate-500">No category pages yet — run the crawl.</div>}
        {tree.data && tree.data.length > 0 && (
          <Tree
            nodes={tree.data}
            render={(n) => (
              <>
                {n.match_type && <StatusBadge value={n.match_type} />}
                {n.url && (
                  <a href={n.url} target="_blank" rel="noreferrer" className="text-[11px] text-indigo-500 hover:underline">
                    ↗
                  </a>
                )}
                {n.source && n.source !== "breadcrumb" && <span className="text-[10px] text-slate-400">via {n.source}</span>}
              </>
            )}
          />
        )}
      </Card>
    </NeedProject>
  );
}
