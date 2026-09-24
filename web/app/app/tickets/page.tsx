"use client";

import { PlusIcon, TicketIcon } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { Carousel } from "@/components/fx/carousel";
import { NoticeCard, type Notice } from "@/components/notice-card";
import { TicketRiver, type TicketRow } from "@/components/ticket-river";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useApi, useEvents } from "@/lib/api";
import { cn } from "@/lib/utils";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "open", label: "Waiting on us" },
  { key: "answered", label: "Answered" },
  { key: "closed", label: "Closed" },
] as const;

export default function Tickets() {
  const { data, loading, reload } = useApi<{ tickets: TicketRow[] }>("/app/tickets");
  const notices = useApi<{ notices: Notice[] }>("/app/notices");
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["key"]>("all");
  useEvents((kind) => (kind === "ticket" || kind === "message") && void reload());

  const shown = useMemo(
    () => (data?.tickets ?? []).filter((t) => filter === "all" || t.status === filter),
    [data, filter],
  );

  return (
    <div className="space-y-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Support</h1>
          <p className="text-muted-foreground">Everything you have asked us, and every answer.</p>
        </div>
        <Link href="/app/tickets/new" className={buttonVariants({ size: "lg", className: "shadow-md shadow-primary/25" })}>
          <PlusIcon /> New ticket
        </Link>
      </div>

      {!!notices.data?.notices.length && (
        <section aria-labelledby="known" className="space-y-3">
          <h2 id="known" className="font-medium">We already know about</h2>
          <Carousel label="Known issues on our side">
            {notices.data.notices.map((n, i) => <NoticeCard key={i} n={n} />)}
          </Carousel>
        </section>
      )}

      <section aria-labelledby="past" className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="past" className="font-medium">Your tickets</h2>
          <div className="flex gap-1 rounded-full border bg-card p-1 text-sm" role="tablist" aria-label="Filter">
            {FILTERS.map((f) => (
              <button key={f.key} type="button" role="tab" aria-selected={filter === f.key} onClick={() => setFilter(f.key)}
                      className={cn("rounded-full px-3 py-1 transition-colors", filter === f.key ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")}>
                {f.label}
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <Skeleton className="h-48 rounded-2xl" />
        ) : !data?.tickets.length ? (
          <div className="grid place-items-center gap-3 rounded-2xl border border-dashed py-16 text-center">
            <span className="grid size-12 place-items-center rounded-2xl bg-primary/10 text-primary"><TicketIcon /></span>
            <p className="font-medium">No tickets yet</p>
            <p className="max-w-sm text-sm text-muted-foreground">If something is not right, open a ticket. You can add a photo of your router or a voice note.</p>
            <Link href="/app/tickets/new" className={buttonVariants()}>Open a ticket</Link>
          </div>
        ) : shown.length ? (
          <>
            <TicketRiver tickets={shown} />
            <ul className="divide-y rounded-2xl border bg-card">
              {shown.map((t) => (
                <li key={t.id}>
                  <Link href={`/app/tickets/${t.id}`} className="flex items-center gap-3 px-4 py-3 hover:bg-muted/50">
                    <span className={cn("size-2 shrink-0 rounded-full", t.status === "open" ? "bg-primary" : t.status === "answered" ? "bg-highlight" : "bg-muted-foreground/40")} />
                    <span className="min-w-0 flex-1 truncate">{t.subject}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">{new Date(t.updated_at).toLocaleDateString()}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">Nothing matches that filter.</p>
        )}
      </section>
    </div>
  );
}
