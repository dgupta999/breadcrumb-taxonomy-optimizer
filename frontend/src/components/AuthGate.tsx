import { useEffect, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { BookOpenCheck, Lock } from "lucide-react";
import { api, setToken } from "@/lib/api";
import { Button, Input, Spinner } from "./ui";

/** Shows a team-password screen when the backend has API_TOKEN set. */
export default function AuthGate({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [state, setState] = useState<"checking" | "ok" | "login">("checking");
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const check = async () => {
    try {
      await api.get("/auth/check");
      setState("ok");
      return true;
    } catch {
      setState("login");
      return false;
    }
  };

  useEffect(() => {
    check();
    const onUnauth = () => setState("login");
    window.addEventListener("bto:unauthorized", onUnauth);
    return () => window.removeEventListener("bto:unauthorized", onUnauth);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    setToken(pw.trim());
    if (await check()) {
      qc.invalidateQueries();
    } else {
      setToken(null);
      setErr("Incorrect team password.");
    }
  };

  if (state === "ok") return <>{children}</>;
  if (state === "checking")
    return (
      <div className="flex min-h-screen items-center justify-center text-slate-500">
        <Spinner />
      </div>
    );
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="mb-5 flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-600 text-white">
            <BookOpenCheck size={18} />
          </div>
          <div>
            <div className="text-sm font-semibold">Breadcrumb Taxonomy Optimizer</div>
            <div className="text-xs text-slate-500">Internal SEO tool</div>
          </div>
        </div>
        <label className="mb-1 block text-xs font-medium text-slate-600">Team password</label>
        <Input type="password" autoFocus value={pw} onChange={(e) => setPw(e.target.value)} placeholder="Ask your team lead" />
        {err && <div className="mt-2 text-xs text-rose-600">{err}</div>}
        <Button className="mt-4 w-full" type="submit" disabled={!pw.trim()}>
          <Lock size={14} /> Sign in
        </Button>
      </form>
    </div>
  );
}
