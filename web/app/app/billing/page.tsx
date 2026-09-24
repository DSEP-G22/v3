"use client";

import { ArrowDownLeftIcon, ArrowRightIcon, ArrowUpRightIcon, ClockIcon, LockIcon, ReceiptTextIcon, WifiIcon } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { FocusLayer, originOf, type Origin } from "@/components/fx/focus-layer";
import { PayDialog } from "@/components/pay-dialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { post, useApi, useEvents } from "@/lib/api";
import { cn } from "@/lib/utils";

type Invoice = { invoice_no: string; period_display: string; issued_display: string; due_display: string;
  total: number | null; total_display: string; status: string; status_display: string };
type Activity = { posted_display: string; description: string; kind: string; debit_display: string;
  credit_display: string; balance_after_display: string };
type Billing = {
  summary: { state: string; headline: string; outstanding_display?: string; due_display?: string;
    last_payment_display?: string; autopay?: boolean };
  invoices: Invoice[];
  activity: Activity[];
  change_display?: string;
  latest: { found: boolean; invoice_no?: string;
    lines?: { description: string; amount_display: string; is_unusual: boolean; unusual_reason?: string }[] };
};
type Paying = { origin: Origin; title: string; start: () => Promise<{ intent_id: string; amount_display: string }> };

const OPEN = new Set(["unpaid", "overdue", "partial"]);
const TABS = [{ id: "overview", label: "Overview" }, { id: "activity", label: "Activity" }, { id: "invoices", label: "Invoices" }] as const;
type Tab = (typeof TABS)[number]["id"];

/** Two stacked generic payment cards, tilted: the "wallet" in the balance panel. No brand on them. */
function Cards() {
  return (
    <div aria-hidden className="relative hidden h-40 w-64 shrink-0 [perspective:900px] sm:block">
      {[0, 1].map((i) => (
        <div key={i}
             className="absolute inset-0 rounded-2xl border border-white/20 p-4 shadow-2xl shadow-black/50 transition-transform duration-700"
             style={{
               transform: `translate(${i ? 28 : 0}px, ${i ? -18 : 0}px) rotateY(-24deg) rotateX(12deg) rotateZ(${i ? 8 : 2}deg)`,
               background: i
                 ? "linear-gradient(135deg, oklch(0.84 0.1 305), oklch(0.62 0.18 300) 55%, oklch(0.45 0.18 295))"
                 : "linear-gradient(135deg, oklch(0.74 0.12 305), oklch(0.52 0.18 298) 60%, oklch(0.36 0.14 295))",
               zIndex: i,
             }}>
          <div className="flex h-full flex-col justify-between text-white">
            <div className="flex items-center justify-between">
              {/* EMV chip */}
              <span className="grid h-6 w-8 grid-cols-3 gap-px overflow-hidden rounded-md bg-gradient-to-br from-amber-100 to-amber-400 p-[3px] opacity-90">
                {[0, 1, 2, 3, 4, 5].map((c) => <span key={c} className="rounded-[1px] bg-amber-600/30" />)}
              </span>
              <WifiIcon className="size-4 rotate-90 opacity-80" />
            </div>
            <div className="flex items-end justify-between text-xs">
              <span className="font-medium tracking-widest">•••• 4242</span>
              <span className="flex">
                <span className="size-5 rounded-full bg-white/70" />
                <span className="-ml-2 size-5 rounded-full bg-white/40" />
              </span>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

/** One ledger line, stacked so it never needs sideways scrolling. */
function ActivityRow({ a }: { a: Activity }) {
  const credit = !!a.credit_display;
  return (
    <li className="grid grid-cols-[auto_1fr_auto] items-center gap-3 py-3">
      <span className={cn("grid size-9 place-items-center rounded-full", credit ? "bg-success/10 text-success" : "bg-muted text-muted-foreground")}>
        {credit ? <ArrowDownLeftIcon className="size-4" /> : <ReceiptTextIcon className="size-4" />}
      </span>
      <span className="min-w-0">
        <span className="block truncate font-medium">{a.description}</span>
        <span className="block truncate text-xs text-muted-foreground">
          {a.posted_display} · {credit ? "Payment" : a.kind === "credit" ? "Credit" : "Charge"}
        </span>
      </span>
      <span className="text-right">
        <span className={cn("block whitespace-nowrap tabular-nums", credit && "text-success")}>
          {credit ? `+${a.credit_display}` : `-${a.debit_display}`}
        </span>
        <span className="block whitespace-nowrap text-xs text-muted-foreground tabular-nums">Balance {a.balance_after_display}</span>
      </span>
    </li>
  );
}

export default function BillingPage() {
  return <Suspense><Payments /></Suspense>;
}

function Payments() {
  const { data, loading, error, reload } = useApi<Billing>("/app/billing");
  // The section lives in the URL, so the header's Billing submenu can link straight to it.
  const router = useRouter();
  const asked = useSearchParams().get("tab");
  const tab: Tab = TABS.some((t) => t.id === asked) ? (asked as Tab) : "overview";
  const setTab = (t: Tab) => router.replace(`/app/billing?tab=${t}`, { scroll: false });
  const [detail, setDetail] = useState<{ invoice: Invoice; origin: Origin } | null>(null);
  const [paying, setPaying] = useState<Paying | null>(null);
  useEvents((kind) => kind === "account" && void reload());

  if (loading) return <Skeleton className="h-96 rounded-2xl" />;
  if (error || !data) return <p className="text-muted-foreground">{error?.message}</p>;

  const open = data.invoices.filter((i) => OPEN.has(i.status));
  const owes = data.summary.state !== "clear" && data.summary.state !== "unknown";
  const paid = data.invoices.filter((i) => i.status === "paid").length;
  const bars = [...data.invoices].reverse().slice(-18);
  const max = Math.max(1, ...bars.map((b) => b.total ?? 0));
  const oldest = [...open].sort((a, b) => a.due_display.localeCompare(b.due_display))[0];
  const payBalance = (origin: Origin) => setPaying({ origin, title: "Pay your balance", start: () => post("/app/balance/pay") });
  const payInvoice = (i: Invoice, origin: Origin) =>
    setPaying({ origin, title: `Pay invoice ${i.invoice_no}`, start: () => post(`/app/invoices/${i.invoice_no}/pay`) });

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-muted-foreground">Your account</p>
          <h1 className="text-2xl font-semibold tracking-tight">Payments</h1>
        </div>
        <nav aria-label="Billing sections" className="flex rounded-full border bg-background/40 p-1 text-sm backdrop-blur">
          {TABS.map((t) => (
            <button key={t.id} type="button" onClick={() => setTab(t.id)} aria-current={tab === t.id ? "page" : undefined}
                    className={cn("rounded-full px-3.5 py-1.5 transition-colors",
                      tab === t.id ? "bg-primary/15 font-medium text-primary" : "text-muted-foreground hover:text-foreground")}>
              {t.label}
            </button>
          ))}
        </nav>
      </div>

      {tab === "overview" && (
        <>
          <div className="grid gap-4 lg:grid-cols-[1.55fr_1fr]">
            <div className="grid gap-4">
              <section className="surface-3d dither relative flex flex-wrap items-center justify-between gap-6 overflow-hidden rounded-3xl p-6">
                <div aria-hidden className="pointer-events-none absolute -top-24 -left-16 size-80 rounded-full bg-primary/30 blur-3xl" />
                <div className="relative space-y-4">
                  <p className="text-sm text-muted-foreground">{owes ? "Balance due" : "Balance"}</p>
                  <p className="text-5xl font-semibold tracking-tight tabular-nums">{owes ? data.summary.outstanding_display : "LKR 0.00"}</p>
                  <p className="text-sm text-muted-foreground">
                    {owes ? `${data.summary.headline}${open.length > 1 ? `, across ${open.length} invoices` : ""}` : "You are all paid up."}
                  </p>
                  {owes && (
                    <Button className="rounded-full bg-lilac px-4 text-foreground hover:bg-lilac/80 dark:bg-[oklch(0.78_0.12_305)] dark:text-[oklch(0.2_0.04_295)]"
                            onClick={(e) => payBalance(originOf(e))}>
                      <ArrowUpRightIcon /> Pay balance
                    </Button>
                  )}
                </div>
                <Cards />
              </section>

              <section className="surface-3d rounded-3xl p-5">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <h2 className="font-medium">Upcoming payment</h2>
                  {oldest && <Button size="xs" variant="outline" className="rounded-full" onClick={(e) => payInvoice(oldest, originOf(e))}>Pay next</Button>}
                </div>
                <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
                  <div><dt className="text-xs text-muted-foreground">Next invoice</dt><dd className="mt-1 text-lg font-semibold tabular-nums">{oldest?.total_display ?? "None"}</dd></div>
                  <div><dt className="text-xs text-muted-foreground">Still owed</dt><dd className="mt-1 text-lg font-semibold tabular-nums">{data.summary.outstanding_display ?? "LKR 0.00"}</dd></div>
                  <div><dt className="text-xs text-muted-foreground">Open invoices</dt><dd className="mt-1 text-lg font-semibold tabular-nums">{open.length}</dd></div>
                  <div>
                    <dt className="text-xs text-muted-foreground">Date</dt>
                    <dd className="mt-1 flex items-center gap-1.5 text-sm">
                      <ClockIcon className="size-3.5 text-highlight" /> {oldest ? `Due ${oldest.due_display}` : "Nothing due"}
                    </dd>
                  </div>
                </dl>
              </section>
            </div>

            <div className="grid gap-4">
              <section className="surface-3d rounded-3xl p-5">
                <p className="text-sm text-muted-foreground">Invoices settled</p>
                <p className="mt-1 text-3xl font-semibold tabular-nums">
                  {paid}<span className="text-base font-normal text-muted-foreground"> / {data.invoices.length}</span>
                </p>
                <div className="mt-4 flex gap-1" aria-label={`${paid} of ${data.invoices.length} invoices paid`}>
                  {data.invoices.slice(0, 24).map((inv) => (
                    <span key={inv.invoice_no} className={cn("h-7 flex-1 rounded-sm",
                      inv.status === "paid" ? "bg-linear-to-t from-primary to-[oklch(0.78_0.12_305)]" : "bg-muted")} />
                  ))}
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  {data.invoices.length ? `${Math.round((paid / data.invoices.length) * 100)}% paid` : "No invoices yet"}
                  {data.summary.last_payment_display ? `, last payment ${data.summary.last_payment_display}` : ""}
                </p>
              </section>

              <section className="surface-3d rounded-3xl p-5">
                <p className="text-sm text-muted-foreground">Monthly bills</p>
                <p className="mt-1 text-3xl font-semibold tabular-nums">{data.invoices[0]?.total_display ?? "LKR 0.00"}</p>
                {data.change_display && <p className="text-xs text-muted-foreground">{data.change_display}</p>}
                <div className="mt-4 flex h-20 items-end gap-1">
                  {bars.map((b) => (
                    <span key={b.invoice_no} title={`${b.issued_display}: ${b.total_display}`}
                          className={cn("flex-1 rounded-t-sm transition-all hover:opacity-80",
                            OPEN.has(b.status) ? "bg-linear-to-t from-destructive/60 to-destructive" : "bg-linear-to-t from-primary/50 to-highlight")}
                          style={{ height: `${Math.max(6, ((b.total ?? 0) / max) * 100)}%` }} />
                  ))}
                </div>
              </section>

              <section className="surface-3d rounded-3xl p-5 text-sm">
                <p className="text-muted-foreground">How you pay</p>
                <p className="mt-1 font-medium">{data.summary.autopay ? "Autopay is on" : "You pay each bill yourself"}</p>
                <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
                  <LockIcon className="size-3 shrink-0" /> Card ending 4242 or LankaQR. Demo payments, no card details are collected.
                </p>
              </section>
            </div>
          </div>

          <section className="surface-3d rounded-3xl px-5 pt-5 pb-2">
            <div className="flex items-center justify-between gap-3">
              <h2 className="font-medium">Recent activity</h2>
              <Button size="xs" variant="ghost" onClick={() => setTab("activity")}>See all <ArrowRightIcon /></Button>
            </div>
            {data.activity.length ? (
              <ul className="divide-y divide-white/5 text-sm">{data.activity.slice(0, 4).map((a, i) => <ActivityRow key={i} a={a} />)}</ul>
            ) : <p className="py-4 text-sm text-muted-foreground">Nothing has happened on your account yet.</p>}
          </section>
        </>
      )}

      {tab === "activity" && (
        <section className="surface-3d rounded-3xl px-5 pt-5 pb-2">
          <h2 className="font-medium">Every charge and payment</h2>
          {data.activity.length ? (
            <ul className="divide-y divide-white/5 text-sm">{data.activity.map((a, i) => <ActivityRow key={i} a={a} />)}</ul>
          ) : <p className="py-4 text-sm text-muted-foreground">Nothing has happened on your account yet.</p>}
        </section>
      )}

      {tab === "invoices" && (
        <section aria-labelledby="invoices" className="surface-3d overflow-hidden rounded-3xl">
          <h2 id="invoices" className="px-5 pt-5 pb-2 font-medium">All invoices</h2>
          <ul className="divide-y divide-white/5">
            {data.invoices.map((i) => (
              <li key={i.invoice_no}>
                <button type="button" onClick={(e) => setDetail({ invoice: i, origin: originOf(e) })}
                        className="grid w-full grid-cols-[1fr_auto_auto] items-center gap-3 px-5 py-3 text-left text-sm hover:bg-white/[0.03]">
                  <span className="min-w-0">
                    <span className="block font-medium">{i.issued_display}</span>
                    <span className="block truncate text-xs text-muted-foreground">{i.period_display}</span>
                  </span>
                  <span className={cn("rounded-full border px-2 py-0.5 text-xs", OPEN.has(i.status) ? "border-destructive/30 text-destructive" : "border-success/30 text-success")}>
                    {i.status_display}
                  </span>
                  <span className="text-right whitespace-nowrap tabular-nums sm:w-28">{i.total_display}</span>
                </button>
              </li>
            ))}
            {!data.invoices.length && <li className="px-5 py-4 text-sm text-muted-foreground">Your first bill will appear here.</li>}
          </ul>
        </section>
      )}

      <FocusLayer open={detail !== null} origin={detail?.origin ?? null} onClose={() => setDetail(null)}
                  title={detail?.invoice.total_display ?? ""}
                  subtitle={detail ? `Invoice ${detail.invoice.invoice_no}, ${detail.invoice.period_display}` : undefined}>
        {detail && (
          <div className="space-y-4">
            {data.latest.found && data.latest.invoice_no === detail.invoice.invoice_no && (
              <ul className="divide-y text-sm">
                {data.latest.lines?.map((l, n) => (
                  <li key={n} className="flex justify-between gap-4 py-2">
                    <span>{l.description}{l.is_unusual && l.unusual_reason && <span className="block text-muted-foreground">{l.unusual_reason}</span>}</span>
                    <span className="shrink-0 tabular-nums">{l.amount_display}</span>
                  </li>
                ))}
              </ul>
            )}
            <p className="text-sm text-muted-foreground">Due {detail.invoice.due_display}. {detail.invoice.status_display}.</p>
            {OPEN.has(detail.invoice.status) && (
              <Button className="w-full" onClick={() => { const o = detail.origin; const inv = detail.invoice; setDetail(null); payInvoice(inv, o); }}>
                Pay this invoice
              </Button>
            )}
          </div>
        )}
      </FocusLayer>

      <PayDialog open={paying !== null} origin={paying?.origin ?? null} onClose={() => setPaying(null)}
                 title={paying?.title ?? ""} start={paying?.start ?? (() => Promise.reject(new Error("Nothing to pay.")))}
                 onPaid={() => void reload()} />
    </div>
  );
}
