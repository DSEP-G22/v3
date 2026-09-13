"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { PriorityPair, type SidePriority } from "@/components/priority-pair";
import { StatusDot } from "@/components/status-dot";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useApi } from "@/lib/api";
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

  // Fresh whenever the agent comes back to the tab; no background polling.
  useEffect(() => {
    const onFocus = () => void reload();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [reload]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-xl font-semibold tracking-tight">Inbox</h1>
        <Button variant="ghost" size="sm" onClick={() => void reload()}>
          Refresh
        </Button>
      </div>
      <Tabs value={tab} onValueChange={(v) => setTab(String(v))}>
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
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
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
                <TableRow key={c.id} className="cursor-pointer" onClick={() => router.push(`/console/cases/${c.id}`)}>
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
      )}
    </div>
  );
}
