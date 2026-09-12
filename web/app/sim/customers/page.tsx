"use client";

import Link from "next/link";
import { useState } from "react";
import { Line, LineChart, XAxis } from "recharts";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { post, useApi } from "@/lib/api";

type Sub = { subscriber_id: string; name: string; segment: string; real_customer: boolean; plan_code: string;
  account_status: string; balance_display: string; line_state: string | null; olt_id: string | null };
type Series = { usage: { date: string; gb: number }[]; line: { time: string; sync_mbps: number; latency_ms: number }[] };

const config = { sync_mbps: { label: "Sync (Mbps)", color: "var(--chart-1)" } } satisfies ChartConfig;
const QUICK = ["suspend_account", "restore_account", "drop_cpe", "line_degradation", "overdue_invoice", "fup_exceeded"];

export default function Customers() {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<Sub | null>(null);
  const list = useApi<{ subscribers: Sub[] }>(`/sim/subscribers?q=${encodeURIComponent(q)}&limit=100`);
  const series = useApi<Series>(open ? `/sim/subscribers/${open.subscriber_id}/series` : null);

  async function inject(name: string) {
    try {
      await post(`/sim/scenarios/${name}`, { subscriber_ref: open!.subscriber_id });
      toast.success("Injected");
      void list.reload();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold tracking-tight">Customers</h1>
      <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, email or SUB number" className="max-w-sm" />
      {list.loading ? <Skeleton className="h-72" /> : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Customer</TableHead>
                <TableHead>Plan</TableHead>
                <TableHead>Account</TableHead>
                <TableHead>Balance</TableHead>
                <TableHead>Line</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.data?.subscribers.map((s) => (
                <TableRow key={s.subscriber_id} className="cursor-pointer" onClick={() => setOpen(s)}>
                  <TableCell>
                    <span className="font-medium">{s.name}</span>
                    {s.real_customer && <Badge variant="secondary" className="ml-2">Signed up</Badge>}
                    <span className="block text-xs text-muted-foreground">{s.subscriber_id}</span>
                  </TableCell>
                  <TableCell>{s.plan_code}</TableCell>
                  <TableCell className="capitalize">{s.account_status}</TableCell>
                  <TableCell className="tabular-nums">{s.balance_display}</TableCell>
                  <TableCell className="capitalize">{s.line_state ?? "none"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <Sheet open={open !== null} onOpenChange={(o) => !o && setOpen(null)}>
        <SheetContent className="sm:max-w-lg">
          {open && (
            <>
              <SheetHeader>
                <SheetTitle>{open.name}</SheetTitle>
                <SheetDescription>
                  {open.subscriber_id}, {open.plan_code}, account {open.account_status}, {open.balance_display} owed.
                </SheetDescription>
              </SheetHeader>
              <div className="space-y-4 overflow-y-auto px-4 pb-6">
                {series.data?.line.length ? (
                  <ChartContainer config={config} className="aspect-auto h-40 w-full">
                    <LineChart data={series.data.line}>
                      <XAxis dataKey="time" hide />
                      <ChartTooltip content={<ChartTooltipContent />} />
                      <Line dataKey="sync_mbps" stroke="var(--color-sync_mbps)" dot={false} strokeWidth={2} />
                    </LineChart>
                  </ChartContainer>
                ) : <p className="text-muted-foreground">No line samples in the last two days.</p>}
                <div className="flex flex-wrap gap-2">
                  {QUICK.map((s) => (
                    <Button key={s} size="sm" variant="outline" onClick={() => inject(s)}>{s.replace(/_/g, " ")}</Button>
                  ))}
                </div>
                <Link href={`/sim/lab?sub=${open.subscriber_id}`} className={buttonVariants({ size: "sm" })}>
                  Send a test inquiry as this customer
                </Link>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
