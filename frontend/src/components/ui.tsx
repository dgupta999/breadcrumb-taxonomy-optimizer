import clsx from "clsx";
import { X } from "lucide-react";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import { useEffect } from "react";

export const cn = clsx;

type Variant = "primary" | "secondary" | "ghost" | "danger" | "success" | "outline";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-indigo-600 text-white hover:bg-indigo-700 disabled:bg-indigo-300",
  secondary: "bg-slate-100 text-slate-800 hover:bg-slate-200 disabled:text-slate-400",
  outline: "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 disabled:text-slate-400",
  ghost: "text-slate-600 hover:bg-slate-100",
  danger: "bg-rose-600 text-white hover:bg-rose-700 disabled:bg-rose-300",
  success: "bg-emerald-600 text-white hover:bg-emerald-700 disabled:bg-emerald-300",
};

export function Button({ variant = "primary", size = "md", className, ...p }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" | "xs" }) {
  return (
    <button
      {...p}
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors disabled:cursor-not-allowed whitespace-nowrap",
        size === "md" && "px-3.5 py-2 text-sm",
        size === "sm" && "px-2.5 py-1.5 text-xs",
        size === "xs" && "px-2 py-1 text-[11px]",
        VARIANTS[variant],
        className,
      )}
    />
  );
}

export function Card({ title, actions, children, className, subtitle }: { title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn("rounded-xl border border-slate-200 bg-white shadow-sm", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-5 py-3.5">
          <div>
            {title && <h2 className="text-sm font-semibold text-slate-800">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

const TONES: Record<string, string> = {
  green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  amber: "bg-amber-50 text-amber-800 ring-amber-200",
  red: "bg-rose-50 text-rose-700 ring-rose-200",
  blue: "bg-sky-50 text-sky-700 ring-sky-200",
  indigo: "bg-indigo-50 text-indigo-700 ring-indigo-200",
  violet: "bg-violet-50 text-violet-700 ring-violet-200",
  gray: "bg-slate-100 text-slate-600 ring-slate-200",
};

export function Badge({ tone = "gray", children, className, title }: { tone?: keyof typeof TONES | string; children: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset", TONES[tone] || TONES.gray, className)}>
      {children}
    </span>
  );
}

const STATUS_TONE: Record<string, string> = {
  AUTO_APPROVED: "green", APPROVED: "green", COMPLETED: "green", KEEP: "gray", HIGH: "red", EXISTING: "green",
  NEEDS_REVIEW: "amber", MEDIUM: "amber", RUNNING: "blue", QUEUED: "gray", CANCEL_REQUESTED: "amber",
  LOW_CONFIDENCE: "red", NO_MATCH: "red", REJECTED: "red", FAILED: "red", LOW: "gray", CANCELLED: "gray",
  NEW: "indigo", MISSING: "red", "SRP ONLY": "violet", DUPLICATE: "red", "EXISTING BUT MISPLACED": "amber",
  MOVE: "indigo", FLATTEN: "blue", "CREATE PARENT": "violet", "CREATE CHILD": "violet", "MOVE + CREATE PARENT": "violet",
  CONSOLIDATE: "red", REVIEW: "amber", YES: "red", POTENTIAL: "amber", NO: "gray", NONE: "gray",
  "EXACT MATCH": "green", "SEMANTIC MATCH": "green", "COMPETITOR MORE SPECIFIC": "violet", "COMPETITOR MORE GENERAL": "blue",
  "MISSING FROM MY TAXONOMY": "red", AMBIGUOUS: "amber", CATEGORY: "green", SUBCATEGORY: "green", PRODUCT: "gray",
  "MISSING CHILD": "violet", "MISSING PARENT": "violet", "BOTH MISSING": "red", "MISPLACED EXISTING CATEGORY": "amber",
  "SRP-ONLY GAP": "blue",
};

export function StatusBadge({ value, className }: { value?: string | null; className?: string }) {
  if (!value) return <span className="text-slate-300">—</span>;
  return (
    <Badge tone={STATUS_TONE[value] || "gray"} className={className}>
      {value.replace(/_/g, " ")}
    </Badge>
  );
}

export function ConfidencePill({ value }: { value?: number | null }) {
  if (value === null || value === undefined) return <span className="text-slate-300">—</span>;
  const tone = value >= 90 ? "bg-emerald-500" : value >= 70 ? "bg-amber-500" : "bg-rose-500";
  return (
    <span className="inline-flex items-center gap-1.5 text-xs tabular-nums text-slate-700">
      <span className="h-1.5 w-10 overflow-hidden rounded-full bg-slate-200">
        <span className={cn("block h-full", tone)} style={{ width: `${Math.max(4, Math.min(100, value))}%` }} />
      </span>
      {value}
    </span>
  );
}

export function Input(p: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...p} className={cn("w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-100", p.className)} />;
}

export function Textarea(p: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...p} className={cn("w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-100", p.className)} />;
}

export function Select({ className, ...p }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...p} className={cn("rounded-md border border-slate-300 bg-white px-2.5 py-2 text-sm focus:border-indigo-500 focus:outline-none", className)} />;
}

export function Label({ children, required }: { children: ReactNode; required?: boolean }) {
  return (
    <label className="mb-1 block text-xs font-medium text-slate-600">
      {children}
      {required && <span className="ml-0.5 text-rose-500">*</span>}
    </label>
  );
}

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    if (open) window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-4 pt-16" onMouseDown={onClose}>
      <div className={cn("w-full rounded-xl bg-white shadow-xl", wide ? "max-w-3xl" : "max-w-lg")} onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
          <h3 className="text-sm font-semibold">{title}</h3>
          <button onClick={onClose} className="rounded p-1 text-slate-400 hover:bg-slate-100" aria-label="Close">
            <X size={16} />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-4 py-10 text-center text-sm text-slate-500">{children}</div>;
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div className={cn("mt-1 text-2xl font-semibold tabular-nums", tone)}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

export function PageHeader({ title, step, description, actions }: { title: string; step?: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        {step && <div className="text-[11px] font-semibold uppercase tracking-wider text-indigo-600">{step}</div>}
        <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-slate-500">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Crumb({ path, highlight, className }: { path?: string | null; highlight?: string[]; className?: string }) {
  if (!path) return <span className="text-slate-300">—</span>;
  const parts = path.split(" > ");
  const hl = new Set(highlight || []);
  return (
    <span className={cn("inline-flex flex-wrap items-center gap-x-1 text-xs leading-5", className)}>
      {parts.map((p, i) => (
        <span key={i} className="inline-flex items-center gap-1">
          {i > 0 && <span className="text-slate-300">›</span>}
          <span className={cn(i === parts.length - 1 ? "font-medium text-slate-800" : "text-slate-500", hl.has(p) && "rounded bg-amber-100 px-1 text-amber-900")}>{p}</span>
        </span>
      ))}
    </span>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <span className={cn("inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-r-transparent", className)} />;
}
