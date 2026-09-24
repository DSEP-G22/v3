"use client";

import { PaperclipIcon, StarIcon } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { cn } from "@/lib/utils";

export type TicketRow = {
  id: string;
  subject: string | null;
  category: string | null;
  status: "open" | "answered" | "closed";
  created_at: string;
  updated_at: string;
  rating: number | null;
  messages: number;
  attachments: number;
  last_body: string | null;
  last_author: string | null;
};

const STATUS = {
  open: { word: "Waiting on us", dot: "bg-primary", glow: "shadow-primary/50", pulse: true },
  answered: { word: "Answered", dot: "bg-highlight", glow: "shadow-highlight/60", pulse: false },
  closed: { word: "Closed", dot: "bg-muted-foreground/50", glow: "shadow-transparent", pulse: false },
} as const;

function month(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", year: "numeric" });
}

/**
 * Past tickets as a river: a glowing line through time, one node per ticket, sized by how much
 * was said and coloured by where it stands. Hover or focus a node to preview it; the preview
 * and the plain list below link to the ticket.
 */
export function TicketRiver({ tickets }: { tickets: TicketRow[] }) {
  const ordered = useMemo(() => [...tickets].sort((a, b) => a.created_at.localeCompare(b.created_at)), [tickets]);
  const [focus, setFocus] = useState<string | null>(ordered.at(-1)?.id ?? null);
  const current = ordered.find((t) => t.id === focus) ?? ordered.at(-1);

  return (
    <div className="space-y-4">
      <div className="snap-row relative overflow-x-auto rounded-2xl border bg-linear-to-b from-secondary/60 to-card px-6 pt-10 pb-6">
        <div className="relative flex min-w-max items-center gap-10 pr-6">
          <span aria-hidden className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-linear-to-r from-lilac via-primary to-highlight opacity-70" />
          {ordered.map((t, i) => {
            const s = STATUS[t.status] ?? STATUS.open;
            const size = Math.min(44, 18 + t.messages * 3);
            const showMonth = i === 0 || month(ordered[i - 1].created_at) !== month(t.created_at);
            return (
              <div key={t.id} className="relative flex flex-col items-center">
                {showMonth && (
                  <span className="absolute -top-9 text-[11px] font-medium whitespace-nowrap text-muted-foreground">{month(t.created_at)}</span>
                )}
                <Link href={`/app/tickets/${t.id}`} aria-label={`${t.subject}, ${s.word}`}
                      onMouseEnter={() => setFocus(t.id)} onFocus={() => setFocus(t.id)}
                      className={cn("relative grid place-items-center rounded-full border-4 border-card shadow-lg transition-transform duration-300 hover:scale-125 focus-visible:scale-125",
                        s.dot, s.glow, focus === t.id && "scale-125 ring-4 ring-primary/20")}
                      style={{ width: size, height: size }}>
                  {s.pulse && <span aria-hidden className="absolute inset-0 animate-ping rounded-full bg-primary/40" />}
                  {t.rating != null && <StarIcon className="relative size-3 fill-current text-white" />}
                </Link>
              </div>
            );
          })}
        </div>
      </div>

      {current && (
        <Link href={`/app/tickets/${current.id}`}
              className="group block rounded-2xl border bg-card p-4 transition-shadow hover:shadow-lg hover:shadow-primary/10">
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span className={cn("size-2 rounded-full", STATUS[current.status]?.dot)} />
            {STATUS[current.status]?.word}
            <span aria-hidden>·</span>
            Opened {new Date(current.created_at).toLocaleDateString()}
            {current.attachments > 0 && <span className="inline-flex items-center gap-1"><PaperclipIcon className="size-3" />{current.attachments}</span>}
            {current.rating != null && <span className="inline-flex items-center gap-0.5 text-highlight-foreground">{Array.from({ length: current.rating }, (_, i) => <StarIcon key={i} className="size-3 fill-highlight text-highlight" />)}</span>}
          </div>
          <p className="mt-1 font-medium group-hover:text-primary">{current.subject}</p>
          {current.last_body && (
            <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">
              {current.last_author === "customer" ? "You: " : "Lanka Link: "}{current.last_body}
            </p>
          )}
        </Link>
      )}
    </div>
  );
}
