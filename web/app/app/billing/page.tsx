"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { StatusDot } from "@/components/status-dot";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { post, useApi, useEvents } from "@/lib/api";

type Invoice = {
  invoice_no: string;
  period_display: string;
  issued_display: string;
  due_display: string;
  total_display: string;
  status: string;
  status_display: string;
};
type Billing = {
  summary: { state: string; headline: string; due_display?: string };
  invoices: Invoice[];
  latest: {
    found: boolean;
    invoice_no?: string;
    lines?: { description: string; amount_display: string; is_unusual: boolean; unusual_reason?: string }[];
    total_display?: string;
  };
};

const OPEN = new Set(["unpaid", "overdue", "partial"]);

export default function BillingPage() {
  const router = useRouter();
  const { data, loading, error, reload } = useApi<Billing>("/app/billing");
  const [open, setOpen] = useState<Invoice | null>(null);
  const [paying, setPaying] = useState<string | null>(null);
  useEvents((kind) => kind === "account" && void reload());

  async function pay(invoiceNo: string) {
    setPaying(invoiceNo);
    try {
      const { intent_id } = await post<{ intent_id: string }>(`/app/invoices/${invoiceNo}/pay`);
      router.push(`/checkout/${intent_id}`);
    } catch (e) {
      toast.error((e as Error).message);
      setPaying(null);
    }
  }

  if (loading) return <Skeleton className="h-64" />;
  if (error || !data) return <p className="text-muted-foreground">{error?.message}</p>;

  const outstanding = data.invoices.filter((i) => OPEN.has(i.status));

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Billing</h1>
      <Card>
        <CardHeader>
          <CardDescription>
            <StatusDot
              tone={data.summary.state === "clear" ? "ok" : data.summary.state === "due" ? "info" : "bad"}
              label={data.summary.state === "clear" ? "Paid up" : data.summary.state === "due" ? "Due" : "Action needed"}
            />
          </CardDescription>
          <CardTitle className="text-xl">{data.summary.headline}</CardTitle>
          {outstanding[0] && (
            <CardAction>
              <Button onClick={() => pay(outstanding[0].invoice_no)} disabled={paying !== null}>
                {paying ? "Opening checkout" : "Pay now"}
              </Button>
            </CardAction>
          )}
        </CardHeader>
      </Card>

      <section aria-labelledby="invoices">
        <h2 id="invoices" className="mb-3 font-medium">
          Invoices
        </h2>
        {data.invoices.length ? (
          <div className="rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Issued</TableHead>
                  <TableHead className="hidden sm:table-cell">Period</TableHead>
                  <TableHead>Amount</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.invoices.map((i) => (
                  <TableRow key={i.invoice_no} className="cursor-pointer" onClick={() => setOpen(i)}>
                    <TableCell>{i.issued_display}</TableCell>
                    <TableCell className="hidden text-muted-foreground sm:table-cell">{i.period_display}</TableCell>
                    <TableCell>{i.total_display}</TableCell>
                    <TableCell>
                      <Badge variant={OPEN.has(i.status) ? "default" : "secondary"}>{i.status_display}</Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <p className="text-muted-foreground">Your first bill will appear here.</p>
        )}
      </section>

      <Sheet open={open !== null} onOpenChange={(o) => !o && setOpen(null)}>
        <SheetContent>
          {open && (
            <>
              <SheetHeader>
                <SheetTitle>{open.total_display}</SheetTitle>
                <SheetDescription>
                  Invoice {open.invoice_no}, {open.period_display}
                </SheetDescription>
              </SheetHeader>
              <div className="space-y-4 px-4">
                {data.latest.found && data.latest.invoice_no === open.invoice_no && (
                  <ul className="divide-y text-sm">
                    {data.latest.lines?.map((l, n) => (
                      <li key={n} className="flex justify-between gap-4 py-2">
                        <span>
                          {l.description}
                          {l.is_unusual && l.unusual_reason && (
                            <span className="block text-muted-foreground">{l.unusual_reason}</span>
                          )}
                        </span>
                        <span className="shrink-0">{l.amount_display}</span>
                      </li>
                    ))}
                  </ul>
                )}
                <p className="text-sm text-muted-foreground">Due {open.due_display}</p>
                {OPEN.has(open.status) && (
                  <Button className="w-full" onClick={() => pay(open.invoice_no)} disabled={paying !== null}>
                    Pay this invoice
                  </Button>
                )}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
