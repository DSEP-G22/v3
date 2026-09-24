import { CheckIcon, ChevronRightIcon, ClockIcon, MessageSquareReplyIcon, PaperclipIcon, StarIcon } from "lucide-react";
import Link from "next/link";

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

export const STATUS = {
  open: { word: "Waiting on us", icon: ClockIcon, tone: "bg-primary/10 text-primary" },
  answered: { word: "Answered", icon: MessageSquareReplyIcon, tone: "bg-success/15 text-success" },
  closed: { word: "Closed", icon: CheckIcon, tone: "bg-muted text-muted-foreground" },
} as const;

const CATEGORY: Record<string, string> = {
  connection: "Connection", equipment: "Router and cables", billing: "Billing", plan: "My plan", other: "Something else",
};

/** "5 min ago", "3 h ago", "yesterday", then the date. */
function ago(iso: string) {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (mins < 60) return rtf.format(-Math.max(0, mins), "minute");
  if (mins < 24 * 60) return rtf.format(-Math.round(mins / 60), "hour");
  if (mins < 7 * 24 * 60) return rtf.format(-Math.round(mins / 1440), "day");
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** Tickets as an inbox: newest activity first, where each stands, and the last word on it. */
export function TicketList({ tickets, limit = Infinity }: { tickets: TicketRow[]; limit?: number }) {
  const rows = [...tickets].sort((a, b) => b.updated_at.localeCompare(a.updated_at)).slice(0, limit);
  return (
    <ul className="divide-y overflow-hidden rounded-2xl border bg-card">
      {rows.map((t) => {
        const s = STATUS[t.status] ?? STATUS.open;
        const fresh = t.status === "answered";
        return (
          <li key={t.id}>
            <Link href={`/app/tickets/${t.id}`} aria-label={`${t.subject ?? "Ticket"}, ${s.word}`}
                  className="group flex items-start gap-3 px-4 py-4 transition-colors hover:bg-muted/40 focus-visible:bg-muted/40 focus-visible:outline-none sm:gap-4 sm:px-5">
              <span className={cn("mt-0.5 grid size-9 shrink-0 place-items-center rounded-full", s.tone)}>
                <s.icon className="size-4" aria-hidden />
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-baseline justify-between gap-3">
                  <span className={cn("truncate", fresh ? "font-semibold" : "font-medium")}>{t.subject ?? "Untitled ticket"}</span>
                  <time dateTime={t.updated_at} className="shrink-0 text-xs text-muted-foreground">{ago(t.updated_at)}</time>
                </span>
                {/* The last word, unless it only repeats the subject (a one message ticket). */}
                {t.last_body && t.last_body.trim() !== t.subject?.trim() && (
                  <span className={cn("mt-0.5 line-clamp-1 text-sm", fresh ? "text-foreground/80" : "text-muted-foreground")}>
                    <span className="font-medium">{t.last_author === "customer" ? "You" : "Lanka Link"}:</span> {t.last_body}
                  </span>
                )}
                <span className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                  <span className={cn("rounded-full px-2 py-0.5 font-medium", s.tone)}>{s.word}</span>
                  {t.category && <span>{CATEGORY[t.category] ?? t.category}</span>}
                  <span>{t.messages} {t.messages === 1 ? "message" : "messages"}</span>
                  {t.attachments > 0 && <span className="inline-flex items-center gap-1"><PaperclipIcon className="size-3" aria-hidden />{t.attachments}</span>}
                  {t.rating != null && (
                    <span className="inline-flex items-center gap-0.5" aria-label={`Rated ${t.rating} of 5`}>
                      {Array.from({ length: 5 }, (_, i) => <StarIcon key={i} aria-hidden className={cn("size-3", i < t.rating! ? "fill-primary text-primary" : "text-muted-foreground/40")} />)}
                    </span>
                  )}
                </span>
              </span>
              <ChevronRightIcon aria-hidden className="mt-2 size-4 shrink-0 text-muted-foreground/50 transition-transform group-hover:translate-x-0.5 group-hover:text-foreground max-sm:hidden" />
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
