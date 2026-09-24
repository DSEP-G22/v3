"use client";

import { PlusIcon, SearchIcon, TicketIcon } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { Carousel } from "@/components/fx/carousel";
import { NoticeCard, type Notice } from "@/components/notice-card";
import { TicketList, type TicketRow } from "@/components/ticket-list";
import { buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useApi, useEvents } from "@/lib/api";
import { cn } from "@/lib/utils";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "open", label: "Waiting on us" },
  { key: "answered", label: "Answered" },
  { key: "closed", label: "Closed" },
] as const;
/** Tickets shown at first; more on request, so a long history stays a short page. */
const PAGE = 20;

export default function Tickets() {
  const { data, loading, reload } = useApi<{ tickets: TicketRow[] }>("/app/tickets");
  const notices = useApi<{ notices: Notice[] }>("/app/notices");
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["key"]>("all");
  const [q, setQ] = useState("");
  const [limit, setLimit] = useState(PAGE);
  useEvents((kind) => (kind === "ticket" || kind === "message") && void reload());

  const all = useMemo(() => data?.tickets ?? [], [data]);
  const count = (key: string) => (key === "all" ? all.length : all.filter((t) => t.status === key).length);
  const shown = useMemo(() => {
    const words = q.trim().toLowerCase();
    return all.filter((t) => (filter === "all" || t.status === filter)
      && (!words || `${t.subject ?? ""} ${t.last_body ?? ""}`.toLowerCase().includes(words)));
  }, [all, filter, q]);

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Support</h1>
          <p className="text-muted-foreground">Everything you have asked us, and every answer.</p>
        </div>
        <Link href="/app/tickets/new" className={buttonVariants({ size: "lg", className: "max-sm:w-full" })}>
          <PlusIcon /> New ticket
        </Link>
      </div>

      {!!notices.data?.notices.length && (
        <section aria-labelledby="known" className="space-y-3">
          <h2 id="known" className="text-sm font-medium text-muted-foreground">We already know about</h2>
          <Carousel label="Known issues on our side">
            {notices.data.notices.map((n, i) => <NoticeCard key={i} n={n} />)}
          </Carousel>
        </section>
      )}

      <section aria-labelledby="past" className="space-y-4">
        <h2 id="past" className="sr-only">Your tickets</h2>
        {!loading && !!all.length && (
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="-mx-4 overflow-x-auto px-4 scrollbar-none sm:mx-0 sm:px-0">
              <div className="flex w-max gap-1 rounded-full border bg-card p-1 text-sm" role="tablist" aria-label="Filter">
                {FILTERS.map((f) => (
                  <button key={f.key} type="button" role="tab" aria-selected={filter === f.key} onClick={() => { setFilter(f.key); setLimit(PAGE); }}
                          className={cn("flex items-center gap-1.5 rounded-full px-3 py-1.5 whitespace-nowrap transition-colors",
                            filter === f.key ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")}>
                    {f.label}
                    <span className={cn("rounded-full px-1.5 text-xs tabular-nums", filter === f.key ? "bg-primary-foreground/20" : "bg-muted")}>{count(f.key)}</span>
                  </button>
                ))}
              </div>
            </div>
            <div className="relative sm:w-64">
              <SearchIcon aria-hidden className="pointer-events-none absolute top-1/2 left-3 z-10 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={q} onChange={(e) => { setQ(e.target.value); setLimit(PAGE); }} placeholder="Search your tickets" aria-label="Search your tickets"
                     className="h-9 rounded-full pl-9" />
            </div>
          </div>
        )}

        {loading ? (
          <div className="space-y-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-24 rounded-2xl" />)}</div>
        ) : !all.length ? (
          <div className="grid place-items-center gap-3 rounded-2xl border border-dashed py-16 text-center">
            <span className="grid size-12 place-items-center rounded-2xl bg-primary/10 text-primary"><TicketIcon /></span>
            <p className="font-medium">No tickets yet</p>
            <p className="max-w-sm text-sm text-muted-foreground">If something is not right, open a ticket. You can add a photo of your router or a voice note.</p>
            <Link href="/app/tickets/new" className={buttonVariants()}>Open a ticket</Link>
          </div>
        ) : shown.length ? (
          <>
            <TicketList tickets={shown} limit={limit} />
            {shown.length > limit && (
              <button type="button" onClick={() => setLimit((l) => l + PAGE)}
                      className="w-full rounded-2xl border border-dashed py-3 text-sm text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground">
                Show {Math.min(PAGE, shown.length - limit)} more of {shown.length - limit}
              </button>
            )}
          </>
        ) : (
          <div className="rounded-2xl border border-dashed py-12 text-center text-sm text-muted-foreground">
            Nothing matches. <button type="button" className="font-medium text-primary hover:underline" onClick={() => { setFilter("all"); setQ(""); }}>Show every ticket</button>
          </div>
        )}
      </section>
    </div>
  );
}
