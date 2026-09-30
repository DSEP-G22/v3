"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { PriorityPair, type SidePriority } from "@/components/priority-pair";
import { StatusDot } from "@/components/status-dot";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { post, useApi } from "@/lib/api";
import { department, priority, STATE_WORD, waiting } from "@/lib/format";

type Row = {
  id: string;
  customer: string;
  summary: string | null;
  department: string | null;
  priority_level: number | null;
  band: string | null;
  customer_priority: SidePriority;
  provider_priority: SidePriority;
  state: string;
  opened_at: string;
};
type Queue = { cases: Row[]; counts: { needs_approval: number; open: number; all: number } };

const TABS = [
  { value: "needs_approval", label: "Needs approval" },
  { value: "open", label: "Open" },
  { value: "all", label: "All" },
] as const;

export default function Inbox() {
  const router = useRouter();
  const [tab, setTab] = useState<string>("needs_approval");
  const { data, loading, reload } = useApi<Queue>(`/console/cases?tab=${tab}`);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [clearing, setClearing] = useState(false);
  const shown = data?.cases ?? [];
  const allPicked = shown.length > 0 && shown.every((c) => picked.has(c.id));

  function toggle(id: string) {
    setPicked((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  }

  // Test and junk requests leave every tab; the customer is not told, and a new message opens a new case.
  async function clear(ids: string[]) {
    if (!ids.length || !confirm(`Clear ${ids.length === 1 ? "this case" : `${ids.length} cases`} from the inbox?`)) return;
    setClearing(true);
    try {
      const r = await post<{ dismissed: string[] }>("/console/cases/dismiss", { ids });
      toast.success(`Cleared ${r.dismissed.length} ${r.dismissed.length === 1 ? "case" : "cases"}`);
      setPicked(new Set());
      await reload();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setClearing(false);
    }
  }

  // Fresh whenever the agent comes back to the tab; no background polling.
  useEffect(() => {
    const onFocus = () => void reload();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [reload]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <h1 className="text-xl font-semibold tracking-tight">Inbox</h1>
        <div className="flex flex-wrap items-center gap-2">
          {picked.size > 0 && (
            <Button variant="destructive" size="sm" disabled={clearing} onClick={() => void clear([...picked])}>
              Clear {picked.size} selected
            </Button>
          )}
          <Button variant="outline" size="sm" disabled={clearing || !shown.length}
                  onClick={() => void clear(shown.map((c) => c.id))}>
            Clear all shown
          </Button>
          <Button variant="ghost" size="sm" onClick={() => void reload()}>
            Refresh
          </Button>
        </div>
      </div>
      <Tabs value={tab} onValueChange={(v) => { setTab(String(v)); setPicked(new Set()); }}>
        <TabsList>
          {TABS.map((t) => (
            <TabsTrigger key={t.value} value={t.value}>
              {t.label}
              {data && <span className="ml-1.5 text-muted-foreground tabular-nums">{data.counts[t.value]}</span>}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      {loading ? (
        <Skeleton className="h-72" />
      ) : !data?.cases.length ? (
        <p className="py-16 text-center text-muted-foreground">
          {tab === "needs_approval" ? "Nothing is waiting for approval." : "No cases here."}
        </p>
      ) : (
        <>
        {/* A phone gets one card per case; the table needs a wider screen. */}
        <ul className="space-y-2 md:hidden">
          {data.cases.map((c) => (
            <li key={c.id} className="flex items-start gap-2">
              <input type="checkbox" checked={picked.has(c.id)} onChange={() => toggle(c.id)}
                     aria-label={`Select ${c.id}`} className="mt-4 size-4 shrink-0 accent-primary" />
              <button type="button" onClick={() => router.push(`/console/cases/${c.id}`)}
                      className="min-w-0 flex-1 space-y-2 rounded-xl border bg-card p-3 text-left transition-colors active:bg-muted">
                <span className="flex items-start justify-between gap-3">
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{c.customer}</span>
                    <span className="block text-xs text-muted-foreground">{c.id}, waiting {waiting(c.opened_at)}</span>
                  </span>
                  <span className="shrink-0 text-right font-medium tabular-nums">{priority(c.priority_level, c.band)}</span>
                </span>
                <span className="line-clamp-2 block">{c.summary ?? "Reading the message"}</span>
                <span className="flex flex-wrap items-center gap-2">
                  <Badge variant="secondary">{department(c.department)}</Badge>
                  <StatusDot tone={c.state === "AWAITING_APPROVAL" ? "warn" : c.state === "RESOLVED" ? "ok" : "info"}
                             label={STATE_WORD[c.state] ?? c.state} />
                  <PriorityPair customer={c.customer_priority} provider={c.provider_priority} className="ml-auto" />
                </span>
              </button>
            </li>
          ))}
        </ul>
        <div className="hidden rounded-lg border md:block">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8">
                  <input type="checkbox" checked={allPicked} aria-label="Select every case shown" className="size-4 accent-primary"
                         onChange={() => setPicked(allPicked ? new Set() : new Set(shown.map((c) => c.id)))} />
                </TableHead>
                <TableHead>Customer</TableHead>
                <TableHead>Summary</TableHead>
                <TableHead>Department</TableHead>
                <TableHead>Priority</TableHead>
                <TableHead>Waiting</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.cases.map((c) => (
                <TableRow key={c.id} className="cursor-pointer" data-state={picked.has(c.id) ? "selected" : undefined}
                          onClick={() => router.push(`/console/cases/${c.id}`)}>
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={picked.has(c.id)} onChange={() => toggle(c.id)}
                           aria-label={`Select ${c.id}`} className="size-4 accent-primary" />
                  </TableCell>
                  <TableCell className="font-medium">
                    {c.customer}
                    <span className="block text-xs font-normal text-muted-foreground">{c.id}</span>
                  </TableCell>
                  <TableCell className="max-w-80 truncate">{c.summary ?? "Reading the message"}</TableCell>
                  <TableCell>
                    <Badge variant="secondary">{department(c.department)}</Badge>
                  </TableCell>
                  <TableCell>
                    <span className="block font-medium tabular-nums">{priority(c.priority_level, c.band)}</span>
                    <PriorityPair customer={c.customer_priority} provider={c.provider_priority} className="mt-0.5" />
                  </TableCell>
                  <TableCell className="tabular-nums text-muted-foreground">{waiting(c.opened_at)}</TableCell>
                  <TableCell>
                    <StatusDot
                      tone={c.state === "AWAITING_APPROVAL" ? "warn" : c.state === "RESOLVED" ? "ok" : "info"}
                      label={STATE_WORD[c.state] ?? c.state}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        </>
      )}
    </div>
  );
}
