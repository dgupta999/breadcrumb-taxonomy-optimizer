import { NavLink, Outlet } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  BookOpenCheck, Boxes, ClipboardCheck, Download, FolderKanban, GitCompare, GitFork, History, LayoutDashboard, ListTree,
  Network, Replace, Route, ScanSearch, ShieldCheck, Target, Upload,
} from "lucide-react";
import { api, getToken, setToken } from "@/lib/api";
import { useProject } from "@/lib/project";
import { cn } from "./ui";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/projects", label: "Projects", icon: FolderKanban },
  { to: "/focus", label: "Category Focus", icon: Target },
  { to: "/upload", label: "Upload Taxonomy", icon: Upload },
  { to: "/srp", label: "SRP Mapping", icon: Route },
  { to: "/audit", label: "Breadcrumb Audit", icon: ScanSearch },
  { to: "/crawl", label: "Competitor Crawl", icon: Network },
  { to: "/competitor-taxonomy", label: "Competitor Taxonomy", icon: ListTree },
  { to: "/competitor-mapping", label: "Competitor Mapping", icon: GitCompare },
  { to: "/gaps", label: "Taxonomy Gaps", icon: Boxes },
  { to: "/parent-child", label: "Parent / Child Gaps", icon: GitFork },
  { to: "/synonyms", label: "Synonyms", icon: Replace },
  { to: "/rules", label: "Approved Rules", icon: ShieldCheck },
  { to: "/review", label: "Review Queue", icon: ClipboardCheck },
  { to: "/exports", label: "Exports", icon: Download },
  { to: "/history", label: "History", icon: History },
];

export default function Layout() {
  const { projects, projectId, setProjectId } = useProject();
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: () => api.get<{ llm_available: boolean; database: string }>("/health"), staleTime: 60000 });
  const { data: queue } = useQuery({
    queryKey: ["review-count", projectId],
    queryFn: () => api.get<{ total: number }>(`/projects/${projectId}/review-queue`, { limit: 2000 }),
    enabled: !!projectId,
    staleTime: 15000,
  });
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 flex h-screen w-60 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="flex items-center gap-2 px-4 pb-3 pt-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-white">
            <BookOpenCheck size={17} />
          </div>
          <div className="leading-tight">
            <div className="text-[13px] font-semibold">Breadcrumb Taxonomy</div>
            <div className="text-[11px] text-slate-500">Optimizer · internal SEO</div>
          </div>
        </div>
        <div className="px-3 pb-3">
          <select
            value={projectId ?? ""}
            onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : null)}
            className="w-full rounded-md border border-slate-300 bg-slate-50 px-2 py-1.5 text-xs font-medium"
          >
            {projects.length === 0 && <option value="">No projects yet</option>}
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-4">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] font-medium",
                  isActive ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-slate-50 hover:text-slate-900",
                )
              }
            >
              <Icon size={15} />
              <span className="flex-1">{label}</span>
              {to === "/review" && !!queue?.total && <span className="rounded-full bg-amber-100 px-1.5 text-[10px] font-semibold text-amber-800">{queue.total}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-slate-100 px-4 py-2.5 text-[11px] text-slate-500">
          LLM fallback: {health ? (health.llm_available ? <span className="text-emerald-600">on</span> : <span>off (rules only)</span>) : "…"}
          <br />
          DB: {health?.database ?? "…"}
          {getToken() && (
            <button className="ml-2 text-indigo-600 hover:underline" onClick={() => { setToken(null); window.location.reload(); }}>
              Sign out
            </button>
          )}
        </div>
      </aside>
      <main className="min-w-0 flex-1 px-8 py-6">
        <Outlet />
      </main>
    </div>
  );
}
