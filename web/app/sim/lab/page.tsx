"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { toast } from "sonner";

import { KeyValues } from "@/components/kv";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, bearer, post, useApi, useStream } from "@/lib/api";
import { department, priority } from "@/lib/format";

const SAMPLES = [
  { label: "Singlish, no internet", text: "mata internet eka wada karanne naha, mona wenne kiyala danne naha" },
  { label: "Sinhala, bill", text: "මේ මාසේ බිල වැඩි ඇයි? මම කලින් ගෙව්වා" },
  { label: "Tamil, red light", text: "என் ரவுட்டரில் சிவப்பு விளக்கு எரிகிறது, இணையம் இல்லை" },
  { label: "Tanglish, slow evenings", text: "enakku internet romba slow irukku, ippo evening la mudiyala" },
  { label: "English, double charge", text: "I was charged twice for the router fee on my last invoice" },
];
const LANGS = [{ value: "", label: "Detect it" }, { value: "si", label: "Sinhala" }, { value: "ta", label: "Tamil" },
  { value: "en", label: "English" }];
/** Problems on the customer's own side, set up on their account before the message is sent. */
const SIDE = [
  { value: "", label: "None, as the account stands" },
  { value: "drop_cpe", label: "Router unplugged or powered off" },
  { value: "firmware_crashloop", label: "Router stuck restarting" },
  { value: "line_degradation", label: "Weak fibre signal at the premises" },
  { value: "fup_exceeded", label: "Data allowance used up" },
  { value: "suspend_account", label: "Account paused for non payment" },
];

type Event = { at: number; kind: string; text: string };
type Case = { case: { id: string; department: string | null; priority_level: number | null; band: string | null;
  state: string; language: string | null }; stages: { stage: string; status: string; ms: number | null }[];
  grounding: { headline: string; findings: { headline: string }[] } | null;
  drafts: { status: string; text_en: string; text_out: string | null; reasons: string[] }[] };

function Lab() {
  const initial = useSearchParams().get("sub") ?? "SUB-100002";
  const people = useApi<{ subscribers: { subscriber_id: string; name: string }[] }>("/sim/subscribers?q=SUB-10000&limit=8");
  const runs = useApi<{ cases: { id: string; summary: string | null; state: string; subscriber_id: string }[] }>("/lab/runs");
  const [sub, setSub] = useState(initial);
  const [lang, setLang] = useState("");
  const [text, setText] = useState(SAMPLES[0].text);
  const [files, setFiles] = useState<FileList | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [caseId, setCaseId] = useState<string | null>(null);
  const [started, setStarted] = useState(0);
  const [issue, setIssue] = useState("");
  const [resetting, setResetting] = useState(false);

  async function reset() {
    setResetting(true);
    try {
      await post(`/sim/scenarios/reset_customer`, { subscriber_ref: sub });
      toast.success("Customer is healthy again: paid up, router online, line up.");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setResetting(false);
    }
  }
  const detail = useApi<Case>(caseId ? `/lab/cases/${caseId}` : null);

  useStream(`/lab/stream/${sub}`, (kind, payload) => {
    const p = payload as Record<string, unknown>;
    if (p?.case_id && typeof p.case_id === "string") setCaseId(p.case_id);
    const describe: Record<string, string> = {
      stage: `Stage: ${String(p.chip)}`, heard: `Heard: ${String(p.text)}`, language: `Language: ${String(p.language)}`,
      draft: `Sentence ${Number(p.index) + 1}: ${String(p.text)}`,
      message: `Reply released: ${String((p.message as { body?: string })?.body ?? "")}`,
    };
    setEvents((e) => [...e, { at: Date.now(), kind, text: describe[kind] ?? kind }]);
    if (kind === "message" || (kind === "stage" && p.chip === "held")) void detail.reload();
  });

  async function send() {
    setEvents([]);
    setCaseId(null);
    setStarted(Date.now());
    if (issue) {
      try {
        await post(`/sim/scenarios/${issue}`, { subscriber_ref: sub });
      } catch (e) {
        // Already in effect is fine: the customer is in the state the test needs.
        if (!(e instanceof ApiError && e.status === 422)) return toast.error((e as Error).message);
      }
      const label = SIDE.find((s) => s.value === issue)?.label ?? issue;
      setEvents([{ at: Date.now(), kind: "injected", text: `On the customer's side: ${label.toLowerCase()}` }]);
    }
    const form = new FormData();
    form.set("subscriber_ref", sub);
    form.set("text", text);
    if (lang) form.set("language", lang);
    Array.from(files ?? []).forEach((f) => form.append("files", f));
    const t = await bearer();
    const r = await fetch("/api/lab/inquiries", { method: "POST", body: form, headers: t ? { authorization: `Bearer ${t}` } : {} });
    if (!r.ok) return toast.error((await r.json().catch(() => ({}))).detail ?? "Could not send.");
    setEvents((ev) => [...ev, { at: Date.now(), kind: "sent", text: "Acknowledged" }]);
    void runs.reload();
  }

  const c = detail.data;
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold tracking-tight">Test lab</h1>
      <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
        <Card size="sm">
          <CardContent>
            <FieldGroup>
              <Field>
                <FieldLabel>Customer</FieldLabel>
                <Select value={sub} onValueChange={(v) => setSub(String(v))}
                        items={(people.data?.subscribers ?? []).map((p) => ({ value: p.subscriber_id, label: `${p.name}, ${p.subscriber_id}` }))}>
                  <SelectTrigger className="w-full"><SelectValue placeholder="Choose a customer" /></SelectTrigger>
                  <SelectContent>
                    {people.data?.subscribers.map((p) => (
                      <SelectItem key={p.subscriber_id} value={p.subscriber_id}>{p.name}, {p.subscriber_id}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field>
                <FieldLabel>Language</FieldLabel>
                <Select value={lang} onValueChange={(v) => setLang(String(v ?? ""))} items={LANGS}>
                  <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>{LANGS.map((l) => <SelectItem key={l.label} value={l.value}>{l.label}</SelectItem>)}</SelectContent>
                </Select>
              </Field>
              <Field>
                <FieldLabel>Problem on the customer&apos;s side</FieldLabel>
                <Select value={issue} onValueChange={(v) => setIssue(String(v ?? ""))} items={SIDE}>
                  <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>{SIDE.map((s) => <SelectItem key={s.label} value={s.value}>{s.label}</SelectItem>)}</SelectContent>
                </Select>
                <Button size="xs" variant="ghost" className="self-start" disabled={resetting} onClick={reset}>
                  {resetting ? "Resetting" : "Reset this customer to healthy"}
                </Button>
              </Field>
              <Field>
                <FieldLabel htmlFor="msg">Message</FieldLabel>
                <Textarea id="msg" rows={4} value={text} onChange={(e) => setText(e.target.value)} />
                <div className="flex flex-wrap gap-1">
                  {SAMPLES.map((s) => (
                    <Button key={s.label} size="xs" variant="ghost" onClick={() => setText(s.text)}>{s.label}</Button>
                  ))}
                </div>
              </Field>
              <Field>
                <FieldLabel htmlFor="files">Photo or voice note</FieldLabel>
                <Input id="files" type="file" accept="image/*,audio/*" multiple onChange={(e) => setFiles(e.target.files)} />
              </Field>
              <Button onClick={send}>Send test inquiry</Button>
            </FieldGroup>
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card size="sm">
            <CardHeader>
              <CardTitle>Live timeline</CardTitle>
              <CardDescription>{caseId ?? "Nothing sent yet"}</CardDescription>
            </CardHeader>
            <CardContent>
              <ol className="space-y-1 text-sm">
                {events.map((e, i) => (
                  <li key={i} className="grid grid-cols-[4rem_1fr] gap-2">
                    <span className="tabular-nums text-muted-foreground">+{((e.at - started) / 1000).toFixed(1)} s</span>
                    <span>{e.text}</span>
                  </li>
                ))}
              </ol>
            </CardContent>
          </Card>

          {c && (
            <Card size="sm">
              <CardHeader>
                <CardTitle>{department(c.case.department)}, priority {priority(c.case.priority_level, c.case.band)}</CardTitle>
                <CardDescription>{c.grounding?.headline}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div className="flex flex-wrap gap-1">
                  {c.stages.map((s, i) => (
                    <Badge key={i} variant={s.status === "done" ? "secondary" : "destructive"}>
                      {s.stage.replace(/_/g, " ")} {s.ms != null ? `${s.ms} ms` : s.status}
                    </Badge>
                  ))}
                </div>
                {c.drafts[0] && (
                  <>
                    <p className="whitespace-pre-line">{c.drafts[0].text_out ?? c.drafts[0].text_en}</p>
                    <KeyValues data={{ decision: c.drafts[0].status, reasons: c.drafts[0].reasons }} />
                  </>
                )}
              </CardContent>
            </Card>
          )}

          <Card size="sm">
            <CardHeader><CardTitle>Recent runs</CardTitle></CardHeader>
            <CardContent>
              <ul className="space-y-1 text-sm">
                {runs.data?.cases.map((r) => (
                  <li key={r.id}>
                    <button type="button" className="text-left hover:underline" onClick={() => setCaseId(r.id)}>
                      {r.id} <span className="text-muted-foreground">{r.subscriber_id}, {r.summary}</span>
                    </button>
                  </li>
                ))}
                {!runs.data?.cases.length && <li className="text-muted-foreground">No test runs yet.</li>}
              </ul>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

export default function LabPage() {
  return (
    <Suspense>
      <Lab />
    </Suspense>
  );
}
