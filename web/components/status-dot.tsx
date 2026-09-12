import { cn } from "@/lib/utils";

const TONE = {
  ok: "bg-success",
  warn: "bg-warning",
  bad: "bg-destructive",
  info: "bg-info",
  idle: "bg-muted-foreground",
} as const;

export type Tone = keyof typeof TONE;

/** Color is never the only signal: always rendered next to its label. */
export function StatusDot({ tone, label, className }: { tone: Tone; label: string; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2 text-sm", className)}>
      <span aria-hidden className={cn("size-2 rounded-full", TONE[tone])} />
      {label}
    </span>
  );
}
