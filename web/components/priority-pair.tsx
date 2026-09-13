import { cn } from "@/lib/utils";

export type SidePriority = { level: number; band: string; source?: string; score?: number | null;
  reasons?: { detail: string; move?: number }[] } | null;

const BAND = {
  critical: "bg-destructive text-white",
  high: "bg-warning/80 text-foreground",
  normal: "bg-primary/15 text-primary",
  low: "bg-muted text-muted-foreground",
} as const;

function Chip({ label, p }: { label: string; p: SidePriority }) {
  if (!p) return <span className="rounded-md bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">{label} not set</span>;
  return (
    <span className="inline-flex items-center gap-1 text-xs" title={`${label}: ${p.band}, from ${p.source ?? "rules"}`}>
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("rounded-md px-1.5 py-0.5 font-semibold tabular-nums", BAND[p.band as keyof typeof BAND] ?? BAND.normal)}>
        {p.level}
      </span>
    </span>
  );
}

/** The two separate priorities: the request (TriageModel) and our side (rules). */
export function PriorityPair({ customer, provider, className }: { customer: SidePriority; provider: SidePriority; className?: string }) {
  return (
    <span className={cn("inline-flex flex-wrap items-center gap-2", className)}>
      <Chip label="Customer" p={customer} />
      <Chip label="Our side" p={provider} />
    </span>
  );
}
