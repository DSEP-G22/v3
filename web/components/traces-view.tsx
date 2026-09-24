"use client";

import { animate, stagger } from "animejs";
import { SearchIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Count } from "@/components/fx/reveal";
import { KeyValues } from "@/components/kv";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApi } from "@/lib/api";
import { department, priority, STATE_WORD } from "@/lib/format";
import { cn } from "@/lib/utils";

type Row = { id: string; summary: string | null; department: string | null; priority_level: number | null;
  band: string | null; state: string; opened_at: string };
type Trace = {
  case: Row & { revision: number };
  stages: { stage: string; status: string; ms: number | null; revision: number; at: string }[];
  bundle: { department: string; priority: { level: number; band: string }; completeness: Record<string, unknown>;
    org_facts: { tool: string }[]; diagnosis: Record<string, unknown> | null } | null;
};

const ms = (n: number) => `${Math.round(n).toLocaleString()} ms`;

/** Every customer request, searchable, each opening its stage-by-stage trace. */
export function TracesView({ base, title }: { base: string; title: string }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const list = useApi<{ cases: Row[] }>(`${base}?q=${encodeURIComponent(q)}`);
  const trace = useApi<Trace>(open ? `${base}/${open}` : null);
  const max = Math.max(1, ...(trace.data?.stages.map((s) => s.ms ?? 0) ?? [1]));
  const total = trace.data?.stages.reduce((t, s) => t + (s.ms ?? 0), 0) ?? 0;

  // The stage bars grow out one after another, like the request moving through the pipeline.
  const bars = useRef<HTMLOListElement>(null);
  useEffect(() => {
    if (!bars.current || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    animate(bars.current.querySelectorAll("[data-bar]"), { scaleX: [0, 1], duration: 900, delay: stagger(60), ease: "outExpo" });
    animate(bars.current.querySelectorAll("li"), { opacity: [0, 1], x: [-6, 0], duration: 600, delay: stagger(60), ease: "outQuad" });
  }, [trace.data]);

  return (
    <div className="space-y-6">
      <div>
        <p className="text-[11px] font-medium tracking-wider uppercase text-primary">Request processing</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">{title}</h1>
      </div>
      <div className="relative max-w-sm">
        <SearchIcon aria-hidden className="pointer-events-none absolute top-1/2 left-3.5 z-10 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by case or summary" aria-label="Search requests"
               className="h-10 rounded-full bg-background/60 pl-10 backdrop-blur" />
      </div>
      {list.loading ? <Skeleton className="h-60 rounded-2xl" /> : (
        <div className="overflow-hidden rounded-2xl border border-foreground/10 bg-card/60 backdrop-blur">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent [&_th]:text-[11px] [&_th]:font-medium [&_th]:tracking-wider [&_th]:uppercase [&_th]:text-muted-foreground">
                <TableHead className="pl-4">Case</TableHead>
                <TableHead>Summary</TableHead>
                <TableHead className="max-md:hidden">Department</TableHead>
                <TableHead className="max-sm:hidden">Priority</TableHead>
                <TableHead className="pr-4">Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.data?.cases.map((c) => (
                <TableRow key={c.id} data-state={open === c.id ? "selected" : undefined}
                          className="cursor-pointer transition-colors duration-300 data-[state=selected]:bg-primary/10 data-[state=selected]:shadow-[inset_2px_0_0_var(--primary)]"
                          onClick={() => setOpen(c.id)}>
                  <TableCell className="pl-4 font-medium">{c.id}</TableCell>
                  <TableCell className="max-w-32 truncate sm:max-w-48 md:max-w-80">{c.summary}</TableCell>
                  <TableCell className="max-md:hidden">{department(c.department)}</TableCell>
                  <TableCell className="max-sm:hidden">{priority(c.priority_level, c.band)}</TableCell>
                  <TableCell className="pr-4">
                    <span className="inline-flex items-center rounded-full border border-foreground/10 bg-muted/50 px-2 py-0.5 text-xs">{STATE_WORD[c.state] ?? c.state}</span>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {!list.data?.cases.length && <p className="p-6 text-center text-muted-foreground">No requests match.</p>}
        </div>
      )}

      <Sheet open={open !== null} onOpenChange={(o) => !o && setOpen(null)}>
        <SheetContent className="w-full sm:max-w-xl">
          <SheetHeader>
            <SheetTitle className="text-lg">{open}</SheetTitle>
            <SheetDescription>Every stage, in order, with its time.</SheetDescription>
          </SheetHeader>
          {trace.loading || !trace.data ? <Skeleton className="m-4 h-60 rounded-2xl" /> : (
            <div className="space-y-6 overflow-y-auto px-4 pb-6">
              <div className="flex items-end justify-between rounded-2xl border border-foreground/10 bg-muted/30 p-4">
                <div>
                  <p className="text-[11px] font-medium tracking-wider uppercase text-muted-foreground">Stage time, summed</p>
                  <p className="mt-2 text-2xl font-semibold tabular-nums leading-none"><Count value={total} format={ms} /></p>
                </div>
                <p className="text-right text-xs text-muted-foreground">{trace.data.stages.length} stages<br />revision {trace.data.case.revision}</p>
              </div>
              <ol ref={bars} className="space-y-2.5">
                {trace.data.stages.map((s, i) => (
                  <li key={i} className="grid grid-cols-[1.5rem_7rem_1fr_4.5rem] items-center gap-2 text-sm">
                    <span className="text-xs font-medium tabular-nums leading-none text-muted-foreground">{String(i + 1).padStart(2, "0")}</span>
                    <span className="truncate capitalize">{s.stage.replace(/_/g, " ")}</span>
                    <span className="h-2 overflow-hidden rounded-full bg-muted">
                      <span data-bar className={cn("block h-2 origin-left rounded-full",
                        s.status === "done" ? "bg-primary" : "bg-destructive")}
                            style={{ width: `${Math.max(2, ((s.ms ?? 0) / max) * 100)}%` }} />
                    </span>
                    <span className="text-right text-xs tabular-nums text-muted-foreground">{s.ms != null ? `${s.ms} ms` : s.status}</span>
                  </li>
                ))}
              </ol>
              {trace.data.bundle && (
                <KeyValues data={{
                  department: department(trace.data.bundle.department),
                  priority: priority(trace.data.bundle.priority.level, trace.data.bundle.priority.band),
                  facts_used: trace.data.bundle.org_facts.map((f) => f.tool.replace(/^get_/, "")),
                  diagnosed_fault: trace.data.bundle.diagnosis?.fault ?? "none",
                  ...trace.data.bundle.completeness,
                }} />
              )}
            </div>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
