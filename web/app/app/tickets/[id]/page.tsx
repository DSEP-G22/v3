"use client";

import { ArrowLeftIcon, CheckIcon } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { SentAttachment, type Att } from "@/components/authed-media";
import { NoticeCard, type Notice } from "@/components/notice-card";
import { TicketComposer } from "@/components/ticket-composer";
import { TicketFeedback } from "@/components/ticket-feedback";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, bearer, post, useApi, useEvents } from "@/lib/api";
import { cn } from "@/lib/utils";

type Msg = {
  id: string;
  conversation_id: string;
  author_kind: "customer" | "assistant" | "agent" | "system";
  body: string;
  body_en?: string | null;
  lang?: string | null;
  created_at: string;
  attachments: Att[];
};
type Ticket = {
  ticket: { id: string; subject: string; category: string | null; status: "open" | "answered" | "closed";
    created_at: string; rating: number | null; feedback: string | null; open_case_id: string | null };
  messages: Msg[];
  stage: string | null;
};

const STEPS = ["Received", "Checking your account", "With our team", "Answered"];

function stepOf(t: Ticket, live: string | null): number {
  if (t.ticket.status !== "open") return 3;
  const s = live ?? t.stage;
  if (s === "With our team" || s === "Writing a reply") return 2;
  if (s === "Checking your account" || s === "Reading your message") return 1;
  return 0;
}

function Reply({ m }: { m: Msg }) {
  const [english, setEnglish] = useState(false);
  const translated = m.lang && m.lang !== "en" && m.body_en;
  return (
    <div className="space-y-1">
      <p className="whitespace-pre-line">{english && m.body_en ? m.body_en : m.body}</p>
      {translated && (
        <button type="button" className="text-xs text-muted-foreground underline underline-offset-4" onClick={() => setEnglish((v) => !v)}>
          {english ? "Show translation" : "Show original (English)"}
        </button>
      )}
    </div>
  );
}

export default function TicketPage() {
  const { id } = useParams<{ id: string }>();
  const { data, loading, error, reload } = useApi<Ticket>(`/app/tickets/${id}`);
  const notices = useApi<{ notices: Notice[] }>("/app/notices");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [live, setLive] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (data) setMessages(data.messages);
  }, [data]);

  useEvents((kind, payload) => {
    const p = payload as Record<string, unknown>;
    if (kind === "message") {
      const m = p.message as Msg;
      if (m.conversation_id !== id) return;
      setMessages((ms) => (ms.some((x) => x.id === m.id) ? ms : [...ms, m]));
      if (m.author_kind !== "customer") { setLive(null); void reload(); }
    } else if (kind === "stage") {
      const chip = p.chip as string;
      setLive(chip === "held" ? "With our team" : chip === "writing" ? "Writing a reply" : "Checking your account");
    } else if (kind === "ticket" && p.id === id) void reload();
  });

  async function reply(form: FormData) {
    setBusy(true);
    form.set("conversation_id", id);
    try {
      const t = await bearer();
      const r = await fetch("/api/app/messages", { method: "POST", body: form, headers: t ? { authorization: `Bearer ${t}` } : {} });
      const body = await r.json();
      if (!r.ok) throw new ApiError(r.status, body.detail ?? "We could not send that. Try again.");
      setMessages((ms) => [...ms, body.message, ...(body.reply ? [body.reply] : [])]);
      setLive("Checking your account");
      void reload();
      return true;
    } catch (e) {
      toast.error((e as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function solved() {
    await post(`/app/tickets/${id}/close`).catch((e) => toast.error((e as Error).message));
    toast.success("Glad that is sorted.");
    void reload();
  }

  if (loading) return <Skeleton className="h-[60svh] rounded-2xl" />;
  if (error || !data) return <p className="text-muted-foreground">{error?.message ?? "We could not find that ticket."}</p>;

  const t = data.ticket;
  const step = stepOf(data, live);

  return (
    <div className="space-y-6">
      <Link href="/app/tickets" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeftIcon className="size-4" /> Support
      </Link>

      <header className="space-y-4 rounded-2xl border bg-linear-to-br from-primary/10 via-card to-highlight/10 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-xl font-semibold tracking-tight">{t.subject}</h1>
            <p className="text-sm text-muted-foreground">
              Opened {new Date(t.created_at).toLocaleString()}{t.category ? `, ${t.category}` : ""}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={t.status === "open" ? "default" : "secondary"}>
              {t.status === "open" ? "Waiting on us" : t.status === "answered" ? "Answered" : "Closed"}
            </Badge>
            {t.status !== "closed" && <Button size="sm" variant="outline" onClick={solved}>Solved</Button>}
          </div>
        </div>
        <ol className="grid grid-cols-4 gap-2" aria-label="Progress">
          {STEPS.map((s, i) => (
            <li key={s} className="space-y-1.5">
              <div className={cn("h-1.5 rounded-full transition-colors duration-700", i <= step ? "bg-primary" : "bg-muted",
                i === step && t.status === "open" && "animate-pulse")} />
              <p className={cn("flex items-center gap-1 text-xs", i <= step ? "text-foreground" : "text-muted-foreground")}>
                {i < step && <CheckIcon className="size-3 text-primary" />}{s}
              </p>
            </li>
          ))}
        </ol>
      </header>

      {!!notices.data?.notices.length && t.status !== "closed" && (
        <div className="grid gap-3 sm:grid-cols-2">
          {notices.data.notices.map((n, i) => <NoticeCard key={i} n={n} />)}
        </div>
      )}

      <ol className="space-y-4">
        {messages.map((m) => {
          const mine = m.author_kind === "customer";
          return (
            <li key={m.id} className={cn("rounded-2xl border p-4", mine ? "bg-card" : "border-primary/20 bg-primary/5")}>
              <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
                <span className={cn("grid size-6 place-items-center rounded-full text-[10px] font-semibold",
                  mine ? "bg-secondary text-secondary-foreground" : "bg-primary text-primary-foreground")}>
                  {mine ? "You" : "LL"}
                </span>
                <span className="font-medium text-foreground">{mine ? "You" : "Lanka Link"}</span>
                <span>{new Date(m.created_at).toLocaleString()}</span>
              </div>
              {mine ? <p className="whitespace-pre-line">{m.body}</p> : <Reply m={m} />}
              {m.attachments?.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {m.attachments.map((a) => <SentAttachment key={a.id} att={a} />)}
                </div>
              )}
            </li>
          );
        })}
        {t.status === "open" && step === 2 && (
          <li className="rounded-2xl border border-dashed p-4 text-sm text-muted-foreground" role="status">
            One of our team is checking your answer. You can add more details below in the meantime.
          </li>
        )}
      </ol>

      {t.status !== "open" && (
        <TicketFeedback ticketId={t.id} rating={t.rating} comment={t.feedback} onSaved={reload} />
      )}

      <section aria-label="Reply" className="space-y-2">
        <h2 className="text-sm font-medium">{t.status === "closed" ? "Reopen with a reply" : "Add to this ticket"}</h2>
        <TicketComposer onSubmit={reply} busy={busy} submitLabel="Send" placeholder="Write a reply, or add a photo or voice note" />
      </section>
    </div>
  );
}
