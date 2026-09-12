"use client";

import { useState } from "react";

import { KeyValues } from "@/components/kv";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApi } from "@/lib/api";
import { department, priority, STATE_WORD } from "@/lib/format";

type Row = { id: string; summary: string | null; department: string | null; priority_level: number | null;
  band: string | null; state: string; opened_at: string };
type Trace = {
  case: Row & { revision: number };
  stages: { stage: string; status: string; ms: number | null; revision: number; at: string }[];
  bundle: { department: string; priority: { level: number; band: string }; completeness: Record<string, unknown>;
    org_facts: { tool: string }[]; diagnosis: Record<string, unknown> | null } | null;
};

export default function Traces() {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const list = useApi<{ cases: Row[] }>(`/admin/traces?q=${encodeURIComponent(q)}`);
  const trace = useApi<Trace>(open ? `/admin/traces/${open}` : null);
  const max = Math.max(1, ...(trace.data?.stages.map((s) => s.ms ?? 0) ?? [1]));

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold tracking-tight">Traces</h1>
      <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by case or summary" className="max-w-sm" />
      {list.loading ? <Skeleton className="h-60" /> : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Case</TableHead>
                <TableHead>Summary</TableHead>
                <TableHead>Department</TableHead>
                <TableHead>Priority</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.data?.cases.map((c) => (
                <TableRow key={c.id} className="cursor-pointer" onClick={() => setOpen(c.id)}>
                  <TableCell className="font-medium">{c.id}</TableCell>
                  <TableCell className="max-w-80 truncate">{c.summary}</TableCell>
                  <TableCell>{department(c.department)}</TableCell>
                  <TableCell>{priority(c.priority_level, c.band)}</TableCell>
                  <TableCell>{STATE_WORD[c.state] ?? c.state}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <Sheet open={open !== null} onOpenChange={(o) => !o && setOpen(null)}>
        <SheetContent className="sm:max-w-xl">
          <SheetHeader>
            <SheetTitle>{open}</SheetTitle>
            <SheetDescription>Every stage, in order, with its time.</SheetDescription>
          </SheetHeader>
          {trace.loading || !trace.data ? <Skeleton className="m-4 h-60" /> : (
            <div className="space-y-6 overflow-y-auto px-4 pb-6">
              <ul className="space-y-1.5">
                {trace.data.stages.map((s, i) => (
                  <li key={i} className="grid grid-cols-[8rem_1fr_4rem] items-center gap-2 text-sm">
                    <span>{s.stage.replace(/_/g, " ")}</span>
                    <span className="h-2 rounded-full bg-muted">
                      <span className={`block h-2 rounded-full ${s.status === "done" ? "bg-primary" : "bg-destructive"}`}
                            style={{ width: `${Math.max(2, ((s.ms ?? 0) / max) * 100)}%` }} />
                    </span>
                    <span className="text-right tabular-nums text-muted-foreground">{s.ms != null ? `${s.ms} ms` : s.status}</span>
                  </li>
                ))}
              </ul>
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
