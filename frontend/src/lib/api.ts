// Thin client for the FastAPI backend.
const BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") || "";
const ENV_TOKEN = import.meta.env.VITE_API_TOKEN as string | undefined;
const TOKEN_KEY = "bto.token";

export function getToken(): string | undefined {
  try {
    return localStorage.getItem(TOKEN_KEY) || ENV_TOKEN;
  } catch {
    return ENV_TOKEN;
  }
}

export function setToken(t: string | null) {
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable */
  }
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function headers(extra?: Record<string, string>): Record<string, string> {
  const h: Record<string, string> = { ...(extra || {}) };
  const token = getToken();
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

function qs(params?: Record<string, unknown>): string {
  if (!params) return "";
  const u = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v === undefined || v === null || v === "" || (Array.isArray(v) && v.length === 0)) return;
    u.set(k, Array.isArray(v) ? v.join(",") : String(v));
  });
  const s = u.toString();
  return s ? `?${s}` : "";
}

async function handle<T>(r: Response): Promise<T> {
  if (r.status === 401) window.dispatchEvent(new Event("bto:unauthorized"));
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* ignore */
    }
    throw new ApiError(r.status, msg);
  }
  return r.json() as Promise<T>;
}

export const api = {
  get: <T,>(path: string, params?: Record<string, unknown>) =>
    fetch(`${BASE}/api${path}${qs(params)}`, { headers: headers() }).then((r) => handle<T>(r)),
  post: <T,>(path: string, body?: unknown) =>
    fetch(`${BASE}/api${path}`, {
      method: "POST",
      headers: headers({ "Content-Type": "application/json" }),
      body: body === undefined ? undefined : JSON.stringify(body),
    }).then((r) => handle<T>(r)),
  put: <T,>(path: string, body?: unknown) =>
    fetch(`${BASE}/api${path}`, {
      method: "PUT",
      headers: headers({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
    }).then((r) => handle<T>(r)),
  patch: <T,>(path: string, body?: unknown) =>
    fetch(`${BASE}/api${path}`, {
      method: "PATCH",
      headers: headers({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
    }).then((r) => handle<T>(r)),
  del: <T,>(path: string) => fetch(`${BASE}/api${path}`, { method: "DELETE", headers: headers() }).then((r) => handle<T>(r)),
  upload: <T,>(path: string, form: FormData) =>
    fetch(`${BASE}/api${path}`, { method: "POST", headers: headers(), body: form }).then((r) => handle<T>(r)),
  async download(path: string, params?: Record<string, unknown>) {
    const r = await fetch(`${BASE}/api${path}${qs(params)}`, { headers: headers() });
    if (r.status === 401) window.dispatchEvent(new Event("bto:unauthorized"));
    if (!r.ok) throw new ApiError(r.status, await r.text());
    const blob = await r.blob();
    const cd = r.headers.get("Content-Disposition") || "";
    const m = /filename\*=UTF-8''([^;]+)/.exec(cd) || /filename="?([^";]+)"?/.exec(cd);
    const name = m ? decodeURIComponent(m[1]) : "export";
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  },
};

export type Paged<T> = { items: T[]; total: number; limit: number; offset: number };
