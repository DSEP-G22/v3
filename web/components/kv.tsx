"use client";

import { toast } from "sonner";

import { Button } from "@/components/ui/button";

/** Humanised key/value detail with a Copy JSON button. Never raw JSON on screen. */
export function KeyValues({ data }: { data: Record<string, unknown> }) {
  const rows = Object.entries(data).filter(([, v]) => v !== null && v !== undefined && v !== "");
  return (
    <div className="space-y-2">
      <dl className="grid grid-cols-[minmax(8rem,auto)_1fr] gap-x-4 gap-y-1.5 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-muted-foreground">{k.replace(/_/g, " ")}</dt>
            <dd className="break-words">{human(v)}</dd>
          </div>
        ))}
      </dl>
      <Button
        variant="ghost"
        size="xs"
        onClick={() => {
          void navigator.clipboard.writeText(JSON.stringify(data, null, 2));
          toast.success("Copied");
        }}
      >
        Copy JSON
      </Button>
    </div>
  );
}

function human(v: unknown): string {
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (Array.isArray(v)) return v.length ? v.map((x) => (typeof x === "object" ? summary(x) : String(x))).join(", ") : "None";
  if (typeof v === "object") return summary(v);
  return String(v);
}

function summary(o: unknown): string {
  const entries = Object.entries(o as Record<string, unknown>).filter(([, x]) => typeof x !== "object");
  return entries.slice(0, 4).map(([k, x]) => `${k.replace(/_/g, " ")} ${x}`).join(", ");
}
