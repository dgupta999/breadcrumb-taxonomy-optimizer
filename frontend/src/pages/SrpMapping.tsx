import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Paged } from "@/lib/api";
import type { Srp } from "@/lib/types";
import { useProject } from "@/lib/project";
import { DataTable, ExportButtons, FilterChips, NeedProject, Pager, SearchBox } from "@/components/common";
import { JobRunner } from "@/components/jobs";
import { ReviewActions } from "@/components/review";
import { Badge, Card, ConfidencePill, Crumb, PageHeader, StatusBadge } from "@/components/ui";

const BANDS = ["AUTO_APPROVED", "NEEDS_REVIEW", "LOW_CONFIDENCE", "NO_MATCH"];
const REVIEW = ["APPROVED", "REJECTED", "NEEDS_REVIEW"];
const DUP = ["YES", "POTENTIAL"];

export default function SrpMapping() {
  const { projectId } = useProject();
  const [q, setQ] = useState("");
  const [band, setBand] = useState<string[]>([]);
  const [review, setReview] = useState<string[]>([]);
  const [dup, setDup] = useState<string[]>([]);
  const [gap, setGap] = useState(false);
  const [offset, setOffset] = useState(0);
  const [sel, setSel] = useState<Set<number>>(new Set());
  const { data, isLoading } = useQuery({
    queryKey: ["srps", projectId, q, band, review, dup, gap, offset],
    queryFn: () =>
      api.get<Paged<Srp>>(`/projects/${projectId}/srps`, { q, band, review_status: review, duplicate: dup, gap: gap || undefined, offset, limit: 100 }),
    enabled: !!projectId,
  });
  const reset = () => setOffset(0);
  return (
    <NeedProject>
      <PageHeader
        step="Step 5"
        title="SRP → category mapping"
        description="Normalize → extract core product & modifiers → apply approved synonyms → score candidates → choose the deepest valid category → inherit that category's existing breadcrumb and append the SRP H1. Human approvals override future runs."
        actions={<JobRunner jobType="MAP_SRP" label="Run SRP mapping" />}
      />
      <Card
        title="SRP breadcrumb mapping"
        actions={
          <>
            <ExportButtons exportKey="srp_breadcrumb_mapping" label="Mapping" />
            <ExportButtons exportKey="srp_review_queue" label="Review queue" />
          </>
        }
      >
        <div className="mb-3 flex flex-wrap items-center gap-x-5 gap-y-2">
          <SearchBox value={q} onChange={(v) => { setQ(v); reset(); }} placeholder="Search keyword / core product…" />
          <FilterChips label="Confidence" options={BANDS} value={band} onChange={(v) => { setBand(v); reset(); }} />
          <FilterChips label="Review" options={REVIEW} value={review} onChange={(v) => { setReview(v); reset(); }} />
          <FilterChips label="Duplicate SRP" options={DUP} value={dup} onChange={(v) => { setDup(v); reset(); }} />
          <FilterChips label="" options={["Taxonomy Gap"]} value={gap ? ["Taxonomy Gap"] : []} onChange={(v) => { setGap(v.length > 0); reset(); }} />
        </div>
        <div className="mb-2 flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs text-slate-500">
            {sel.size > 0 && (
              <>
                <span>{sel.size} selected</span> <ReviewActions entityType="srp" ids={[...sel]} />
              </>
            )}
          </div>
          {data && <Pager total={data.total} limit={data.limit} offset={offset} onChange={setOffset} />}
        </div>
        <DataTable
          rows={data?.items || []}
          loading={isLoading}
          selectable
          selected={sel}
          onSelect={setSel}
          empty="No SRPs yet — upload SRP data on the Upload page."
          expand={(s) => (
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-1 text-xs">
                <div><span className="text-slate-500">Reason:</span> {s.reason}</div>
                <div><span className="text-slate-500">Recommended action:</span> {s.recommended_action}</div>
                <div><span className="text-slate-500">Canonical concept:</span> {s.canonical_concept || "—"} · <span className="text-slate-500">Method:</span> {s.match_method}</div>
                <div><span className="text-slate-500">English:</span> {s.keyword_en || s.keyword_en_generated || "—"} <Badge>{s.en_source || "—"}</Badge></div>
                {s.url && <a className="text-indigo-600" href={s.url} target="_blank" rel="noreferrer">Open SRP ↗</a>}
              </div>
              <div>
                <div className="mb-1 text-xs font-semibold text-slate-500">Top candidates</div>
                <ol className="space-y-1.5">
                  {s.candidates.map((c) => (
                    <li key={c.node_id} className="text-xs">
                      <div className="flex items-center gap-2"><span className="font-medium">{c.name}</span><Badge>{c.score}</Badge></div>
                      <Crumb path={c.breadcrumb} />
                      <div className="text-[11px] text-slate-400">{c.signals.join(" · ")}</div>
                    </li>
                  ))}
                </ol>
              </div>
            </div>
          )}
          columns={[
            {
              key: "kw",
              header: "SRP keyword",
              render: (s) => (
                <div>
                  <div className="font-medium">{s.keyword}</div>
                  <div className="text-[11px] text-slate-500">vol {s.search_volume?.toLocaleString() ?? "—"} · {s.product_count ?? "—"} products</div>
                </div>
              ),
            },
            {
              key: "core",
              header: "Core / modifiers",
              render: (s) => (
                <div className="flex flex-wrap gap-1">
                  {s.core_product && <Badge tone="indigo">{s.core_product}</Badge>}
                  {s.modifiers.map((m) => <Badge key={m}>{m}</Badge>)}
                </div>
              ),
            },
            {
              key: "cat",
              header: "Matched category",
              render: (s) => (s.matched_category ? <span className="font-medium">{s.matched_category}</span> : <StatusBadge value="NO_MATCH" />),
            },
            {
              key: "bc",
              header: "Suggested SRP breadcrumb (CN / EN)",
              className: "min-w-[340px]",
              render: (s) => (
                <div>
                  <Crumb path={s.breadcrumb_cn} />
                  {s.breadcrumb_en && <div className="text-[11px] text-slate-400">{s.breadcrumb_en}</div>}
                </div>
              ),
            },
            { key: "conf", header: "Confidence", render: (s) => <div className="space-y-1"><ConfidencePill value={s.confidence} /><StatusBadge value={s.confidence_band} /></div> },
            { key: "dup", header: "Duplicate", render: (s) => <StatusBadge value={s.duplicate_intent} /> },
            { key: "st", header: "Review", render: (s) => <StatusBadge value={s.review_status} /> },
            { key: "act", header: "", render: (s) => <ReviewActions entityType="srp" ids={[s.id]} compact defaultName={s.h1 || s.keyword} /> },
          ]}
        />
      </Card>
    </NeedProject>
  );
}
