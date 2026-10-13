import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import type { Project } from "./types";

type Ctx = { projectId: number | null; setProjectId: (id: number | null) => void; project?: Project; projects: Project[] };
const ProjectCtx = createContext<Ctx>({ projectId: null, setProjectId: () => {}, projects: [] });

const KEY = "bto.projectId";

function readStored(): number | null {
  try {
    const v = localStorage.getItem(KEY);
    return v ? Number(v) : null;
  } catch {
    return null;
  }
}

export function ProjectProvider({ children }: { children: ReactNode }) {
  const [projectId, setId] = useState<number | null>(readStored);
  const { data: projects = [] } = useQuery({ queryKey: ["projects"], queryFn: () => api.get<Project[]>("/projects") });
  useEffect(() => {
    if (projects.length && (projectId === null || !projects.some((p) => p.id === projectId))) setProjectId(projects[0].id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projects]);
  const setProjectId = (id: number | null) => {
    setId(id);
    try {
      if (id === null) localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, String(id));
    } catch {
      /* storage unavailable */
    }
  };
  const project = projects.find((p) => p.id === projectId);
  return <ProjectCtx.Provider value={{ projectId, setProjectId, project, projects }}>{children}</ProjectCtx.Provider>;
}

export const useProject = () => useContext(ProjectCtx);
