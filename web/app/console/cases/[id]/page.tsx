"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { SentAttachment, type Att } from "@/components/authed-media";
import { KeyValues } from "@/components/kv";
import { PriorityPair, type SidePriority } from "@/components/priority-pair";
import { StatusDot } from "@/components/status-dot";
import { UnifiedTicket, type Bundle, type Stages } from "@/components/unified-ticket";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { api, post, useApi, useStream } from "@/lib/api";
import { department, priority, STATE_WORD } from "@/lib/format";

type Msg = { id: string; author_kind: string; body: string; body_en?: string | null; lang?: string | null;
  created_at: string; attachments: Att[] };
type Finding = { signal: string; severity: string; headline: string; detail: string; side?: "customer" | "provider" };
type Draft = { revision: number; text_en: string; text_out: string | null; language: string; status: string;
  reasons: string[]; findings: { rule: string; message: string; severity: string }[];
  action: { action_id: string; description: string; parameters: Record<string, unknown> } | null };
type CaseDetail = {
  customer: string;
  case: { id: string; state: string; department: string | null; priority_level: number | null; band: string | null;
    revision: number; language: string | null; summary: string | null };
  stages: { stage: string; status: string; ms: number | null; revision: number }[];
  conversation: { messages: Msg[] } | null;
  drafts: Draft[];
  grounding: { headline: string; findings: Finding[]; cause?: Cause; priority: { reasons: { detail: string; move: number }[] };
    customer_priority: SidePriority; provider_priority: SidePriority;
    sla_display: string; completeness: Record<string, unknown> } | null;
  payload: { stages: Stages } | null;
  bundle: Bundle | null;
  transcripts?: Record<string, Heard>;
};
type Cause = { side: "customer" | "provider" | "both" | "unclear"; summary: string };
type Heard = { text?: string; text_en?: string; language?: string; confidence?: number; low_confidence?: boolean;
  failed?: boolean; note?: string };

const LANGS = [
  { value: "si", label: "Sinhala" }, { value: "si-Latn", label: "Singlish" },
  { value: "ta", label: "Tamil" }, { value: "ta-Latn", label: "Tanglish" },
];
const LANG_WORD: Record<string, string> = { en: "English", si: "Sinhala", ta: "Tamil", "si-Latn": "Singlish", "ta-Latn": "Tanglish" };

const SEND_BACK = ["Facts are wrong", "Tone needs work", "Wrong action", "Needs a person to call"];
const SEVERITY_TONE = { cause: "bad", risk: "warn", context: "idle" } as const;
const CAUSE_WORD = { customer: "Their side", provider: "Our side", both: "Both sides", unclear: "Not yet clear" } as const;
const SEVERITY_WORD: Record<string, string> = { cause: "Cause", risk: "Could contribute", context: "Good to know" };

export default function CasePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data, loading, reload } = useApi<CaseDetail>(`/console/cases/${id}`);
  const [text, setText] = useState("");
  const [live, setLive] = useState("");
  const [reason, setReason] = useState(SEND_BACK[0]);
  const [preview, setPreview] = useState<string | null>(null);
  const [previewLang, setPreviewLang] = useState<string | null>(null);
  const [translating, setTranslating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [lang, setLang] = useState<string | null>(null);
  const [rerunning, setRerunning] = useState(false);
  // Only this revision's draft: after a language re-run the old one no longer applies.
  const held = data?.drafts.find((d) => d.status === "held" && d.revision === data.case.revision);

  async function rerun() {
    if (!lang) return;
    setRerunning(true);
    try {
      await post(`/console/cases/${id}/language`, { language: lang });
      toast.success(`Re-running in ${LANG_WORD[lang]}. The reply updates here as it is drafted.`);
      setLive("");
      setPreview(null);
      await reload();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setRerunning(false);
    }
  }

  useEffect(() => {
    if (held) setText(held.text_en);
  }, [held]);

  // While the case is still drafting, show the model's raw tokens as they arrive.
  useStream(held || !data ? null : `/console/cases/${id}/stream`, (kind, payload) => {
    if (kind === "token") setLive((t) => t + String(payload));
    else if (kind === "held" || kind === "stage") void reload();
  });

  async function act(path: string, body?: unknown, done = "Done") {
    setBusy(true);
    try {
      await post(`/console/cases/${id}/${path}`, body);
      toast.success(done);
      router.push("/console");
    } catch (e) {
      toast.error((e as Error).message);
      setBusy(false);
    }
  }

  if (loading || !data) return <Skeleton className="h-[70svh]" />;
  const c = data.case;
  const messages = data.conversation?.messages ?? [];
  // Older cases stored no attachment ids with their transcripts; the unified ticket still has them.
  const heard: Record<string, Heard> = {
    ...Object.fromEntries((data.bundle?.payload.transcripts ?? []).map((t) => [(t as { attachment_id?: string }).attachment_id, t])),
    ...data.transcripts,
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link href="/console" className="text-sm text-muted-foreground hover:text-foreground">
            Inbox
          </Link>
          <h1 className="text-xl font-semibold tracking-tight">
            {data.customer} <span className="font-normal text-muted-foreground">{c.id}</span>
          </h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary">{department(c.department)}</Badge>
          <Badge variant="outline">Priority {priority(c.priority_level, c.band)}</Badge>
          <PriorityPair customer={data.grounding?.customer_priority ?? null} provider={data.grounding?.provider_priority ?? null} />
          <StatusDot tone={c.state === "AWAITING_APPROVAL" ? "warn" : "info"} label={STATE_WORD[c.state] ?? c.state} />
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_1.1fr]">
        <Card>
          <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
            <CardTitle>Conversation</CardTitle>
            {/* The detected language can be wrong (Singlish read as English, say): correct it and re-run. */}
            <div className="flex items-center gap-2 text-sm">
              <span className="text-muted-foreground">Language</span>
              <Select value={lang ?? c.language ?? "en"} onValueChange={(v) => setLang(String(v))}
                      items={Object.entries(LANG_WORD).map(([value, label]) => ({ value, label }))}>
                <SelectTrigger size="sm" className="w-32" aria-label="Customer's language"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {Object.entries(LANG_WORD).map(([v, label]) => (
                    <SelectItem key={v} value={v}>{label}{v === c.language ? " (current)" : ""}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button size="sm" variant="outline" disabled={rerunning || !lang || lang === c.language} onClick={rerun}>
                {rerunning ? "Re-running" : "Re-run translation"}
              </Button>
            </div>
          </CardHeader>
          <CardContent className="max-h-[70svh] space-y-3 overflow-y-auto">
            {messages.map((m) => (
              <div key={m.id} className={m.author_kind === "customer" ? "" : "ml-6 rounded-lg bg-muted/60 p-3"}>
                <p className="text-xs text-muted-foreground">
                  {m.author_kind === "customer" ? data.customer : "Lanka Link"} ·{" "}
                  {new Date(m.created_at).toLocaleString()}
                </p>
                <p className="whitespace-pre-line">{m.body}</p>
                {m.body_en && m.body_en !== m.body && (
                  <p className="mt-1 whitespace-pre-line text-sm text-muted-foreground">English: {m.body_en}</p>
                )}
                {m.attachments?.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {m.attachments.map((a) => (
                      <div key={a.id} className="space-y-1">
                        <SentAttachment att={a} alt="Photo from the customer" />
                        {a.kind === "audio" && <VoiceText t={heard[a.id]} />}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardDescription>What we found</CardDescription>
              <CardTitle className="text-base">{data.grounding?.headline ?? "Still checking the record."}</CardTitle>
            </CardHeader>
            {data.grounding && (
              <CardContent className="space-y-3">
                {data.grounding.cause && (
                  <p className="rounded-md bg-muted/60 p-2 text-sm">
                    <span className="mr-2 font-medium">{CAUSE_WORD[data.grounding.cause.side]}</span>
                    <span className="text-muted-foreground">{data.grounding.cause.summary}</span>
                  </p>
                )}
                {/* Every finding, split by where it comes from: their equipment, or our records. */}
                <div className="grid gap-3 sm:grid-cols-2">
                  {(["customer", "provider"] as const).map((side) => {
                    const items = data.grounding!.findings.filter((f) => (f.side ?? "provider") === side);
                    return (
                      <section key={side} className="rounded-lg border p-3">
                        <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                          {side === "customer" ? "Their side, equipment at the premises" : "Our side, account and network"}
                        </h3>
                        {items.length ? (
                          <ul className="space-y-2">
                            {items.map((f) => (
                              <li key={f.signal}>
                                <StatusDot tone={SEVERITY_TONE[f.severity as keyof typeof SEVERITY_TONE] ?? "idle"}
                                           label={`${SEVERITY_WORD[f.severity] ?? f.severity}: ${f.headline}`} />
                                <p className="ml-4 text-sm text-muted-foreground">{f.detail}</p>
                              </li>
                            ))}
                          </ul>
                        ) : <p className="text-sm text-muted-foreground">Nothing found.</p>}
                      </section>
                    );
                  })}
                </div>
              </CardContent>
            )}
          </Card>

          <Card>
            <CardHeader>
              <CardDescription>Unified ticket</CardDescription>
              <CardTitle className="text-base">What the pipeline understood</CardTitle>
            </CardHeader>
            <CardContent>
              <UnifiedTicket bundle={data.bundle} stages={data.payload?.stages ?? null} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardDescription>Suggested reply {held?.language && held.language !== "en" && `(sent in ${LANG_WORD[held.language] ?? held.language})`}</CardDescription>
              {held?.reasons?.length ? <CardTitle className="text-sm font-normal text-muted-foreground">{held.reasons[0]}</CardTitle> : null}
            </CardHeader>
            <CardContent className="space-y-3">
              {held ? (
                <Textarea value={text} onChange={(e) => setText(e.target.value)} rows={10} aria-label="Reply to send" />
              ) : (
                <p className="min-h-24 whitespace-pre-line text-sm text-muted-foreground">{live || "Drafting a reply."}</p>
              )}
              {held && (
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-xs text-muted-foreground">Translate:</span>
                    {[...(held.language !== "en" && !LANGS.some((l) => l.value === held.language) ? [] : []),
                      ...LANGS].map((l) => (
                      <Button key={l.value} size="xs" variant={previewLang === l.value ? "secondary" : "ghost"} disabled={translating}
                              onClick={async () => {
                                setTranslating(true);
                                setPreviewLang(l.value);
                                try {
                                  const r = await api<{ text: string }>(`/console/cases/${id}/preview?lang=${l.value}`);
                                  setPreview(r.text);
                                } catch (e) {
                                  toast.error((e as Error).message);
                                } finally {
                                  setTranslating(false);
                                }
                              }}>
                        {l.label}{l.value === held.language ? " (customer)" : ""}
                      </Button>
                    ))}
                  </div>
                  {translating && <p className="text-xs text-muted-foreground">Translating</p>}
                  {preview && !translating && (
                    <p className="rounded-md bg-muted/60 p-3 text-sm whitespace-pre-line">{preview}</p>
                  )}
                  {held.language !== "en" && (
                    <p className="text-xs text-muted-foreground">
                      On approval the customer receives this in {LANG_WORD[held.language] ?? held.language}.
                    </p>
                  )}
                </div>
              )}
              {held?.action && (
                <p className="text-sm">
                  <span className="text-muted-foreground">Will also do: </span>
                  {held.action.description || held.action.action_id.replace(/_/g, " ")}
                </p>
              )}
              {held && (
                <div className="flex flex-wrap items-center gap-2 pt-1">
                  <Button disabled={busy} onClick={() => act("approve", { text_en: text }, "Reply sent")}>
                    Approve and send
                  </Button>
                  <Select value={reason} onValueChange={(v) => setReason(String(v))} items={SEND_BACK.map((s) => ({ value: s, label: s }))}>
                    <SelectTrigger className="w-48"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {SEND_BACK.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                    </SelectContent>
                  </Select>
                  <Button variant="outline" disabled={busy} onClick={() => act("send-back", { reason }, "Sent back")}>
                    Send back
                  </Button>
                  <Button variant="ghost" disabled={busy} onClick={() => act("escalate", undefined, "Escalated")}>
                    Escalate
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>

          <Accordion>
            <AccordionItem value="details">
              <AccordionTrigger>Details</AccordionTrigger>
              <AccordionContent className="space-y-4">
                <section>
                  <h3 className="mb-1 text-sm font-medium">Stages</h3>
                  <ul className="text-sm">
                    {data.stages.map((s, i) => (
                      <li key={i} className="flex justify-between gap-4 border-b py-1 last:border-0">
                        <span>{s.stage.replace(/_/g, " ")} <span className="text-muted-foreground">rev {s.revision}</span></span>
                        <span className="tabular-nums text-muted-foreground">{s.status}{s.ms != null && `, ${s.ms} ms`}</span>
                      </li>
                    ))}
                  </ul>
                </section>
                {data.grounding && (
                  <section>
                    <h3 className="mb-1 text-sm font-medium">Why this priority</h3>
                    <div className="grid gap-3 sm:grid-cols-2">
                      {([["Customer side, triage model", data.grounding.customer_priority],
                         ["Our side, rules on the record", data.grounding.provider_priority]] as const).map(([label, p]) => (
                        <div key={label} className="rounded-lg border p-3">
                          <p className="text-xs font-medium">{label}{p ? `: ${p.level} ${p.band}` : ""}</p>
                          <ul className="mt-1 space-y-1 text-sm text-muted-foreground">
                            {(p?.reasons ?? []).map((r, i) => <li key={i}>{r.detail}</li>)}
                          </ul>
                        </div>
                      ))}
                    </div>
                    <p className="mt-2 text-sm">Service level: {data.grounding.sla_display}</p>
                    <div className="mt-2"><KeyValues data={data.grounding.completeness} /></div>
                  </section>
                )}
                {held?.findings?.length ? (
                  <section>
                    <h3 className="mb-1 text-sm font-medium">Compliance</h3>
                    <ul className="text-sm text-muted-foreground">
                      {held.findings.map((f, i) => <li key={i}>{f.message}</li>)}
                    </ul>
                  </section>
                ) : null}
              </AccordionContent>
            </AccordionItem>
          </Accordion>
          <Link href="/console" className={buttonVariants({ variant: "link", className: "px-0" })}>Back to inbox</Link>
        </div>
      </div>
    </div>
  );
}

/** What the speech model heard in one voice note, or why there is nothing to read. */
function VoiceText({ t }: { t: Heard | undefined }) {
  if (!t) return <p className="text-xs text-muted-foreground">No transcript yet.</p>;
  if (t.failed) return <p className="text-xs text-destructive">Could not transcribe this voice note in time.</p>;
  if (!t.text) return <p className="text-xs text-muted-foreground">{t.note ? `Not transcribed: ${t.note}.` : "No speech heard."}</p>;
  return (
    <div className="max-w-md rounded-md bg-muted/60 p-2 text-sm">
      <p className="text-xs text-muted-foreground">
        Transcript{t.language ? `, ${LANG_WORD[t.language] ?? t.language}` : ""}
        {t.confidence != null ? `, ${Math.round(t.confidence * 100)}% sure` : ""}
        {t.low_confidence ? " (low confidence)" : ""}
      </p>
      <p className="whitespace-pre-line">{t.text}</p>
      {t.text_en && t.text_en !== t.text && <p className="mt-1 whitespace-pre-line text-muted-foreground">English: {t.text_en}</p>}
    </div>
  );
}
