"use client";

import { AudioLinesIcon, BrainIcon, CameraIcon, FileTextIcon, GaugeIcon, TagsIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type Cls = { label: string; p: number };
type Visual = { summary?: string; confidence?: number; classes?: Cls[]; leds?: { colour: string }[] } | null;
type Transcript = { text?: string; text_en?: string; language?: string; confidence?: number } | null;
export type Bundle = {
  payload: { original_text: string; text_en: string; language: string; reply_language: string; fused_text: string;
    flags: string[]; partial: boolean;
    visual_summaries: { attachment_id: string; summary_text: string; confidence: number; led_states: { colour: string }[] }[];
    transcripts: { text: string; text_en: string; language: string; confidence: number; low_confidence: boolean }[] };
  triage: { department: string; base_level: number; routed_by: string; sentiment: string;
    signals: Record<string, unknown>; customer_priority: Record<string, unknown> };
  diagnosis: { intent: string; fault: string | null; confidence: number; rationale: string; via: string;
    citations: { chunk_id: string }[] } | null;
  completeness: { required: string[]; present: string[]; missing: string[]; degraded: string[] };
};
export type Stages = { visual?: Visual[]; transcripts?: Transcript[] } | string | null;

const LANG: Record<string, string> = { en: "English", si: "Sinhala", ta: "Tamil", "si-Latn": "Singlish", "ta-Latn": "Tanglish", und: "Unknown" };

function Row({ icon: Icon, title, children }: { icon: typeof FileTextIcon; title: string; children: ReactNode }) {
  return (
    <section className="grid grid-cols-[1.25rem_1fr] gap-x-3 gap-y-1 border-b py-3 last:border-0">
      <Icon className="mt-0.5 size-4 text-primary" />
      <div className="min-w-0 space-y-1.5">
        <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{title}</h3>
        {children}
      </div>
    </section>
  );
}

function Bar({ label, p }: Cls) {
  return (
    <div className="grid grid-cols-[9rem_1fr_3rem] items-center gap-2 text-xs">
      <span className="truncate">{label.replace(/[-_]/g, " ")}</span>
      <span className="h-1.5 overflow-hidden rounded-full bg-muted">
        <span className="block h-full rounded-full bg-linear-to-r from-primary to-highlight" style={{ width: `${Math.round(p * 100)}%` }} />
      </span>
      <span className="text-right tabular-nums text-muted-foreground">{Math.round(p * 100)}%</span>
    </div>
  );
}

function Chip({ on, children }: { on?: boolean; children: ReactNode }) {
  return <span className={cn("rounded-md px-1.5 py-0.5 text-xs", on ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground")}>{children}</span>;
}

/**
 * The unified ticket as the pipeline built it: the request in every modality, what each model
 * identified, the signals, the triage and the diagnosis. Everything the draft was written from.
 */
export function UnifiedTicket({ bundle, stages }: { bundle: Bundle | null; stages: Stages }) {
  if (!bundle) return <p className="text-sm text-muted-foreground">The ticket is still being read.</p>;
  const st = typeof stages === "string" ? (JSON.parse(stages) as { visual?: Visual[]; transcripts?: Transcript[] }) : stages ?? {};
  const p = bundle.payload;
  const s = bundle.triage.signals ?? {};
  const cp = bundle.triage.customer_priority ?? {};
  const visuals = (st.visual ?? []).filter(Boolean) as NonNullable<Visual>[];
  const voices = p.transcripts;
  const modality = [p.original_text && "text", voices.length && "voice", (visuals.length || p.visual_summaries.length) && "photo"].filter(Boolean).join(" + ");

  return (
    <div className="text-sm">
      <Row icon={FileTextIcon} title="Request">
        <div className="flex flex-wrap gap-1.5">
          <Chip on>{modality || "text"}</Chip>
          <Chip on>{LANG[p.language] ?? p.language}</Chip>
          <Chip>replies in {LANG[p.reply_language] ?? p.reply_language}</Chip>
          {p.partial && <Chip>partial: a stage missed its budget</Chip>}
          {p.flags.map((f) => <Chip key={f}>{f.replace(/_/g, " ")}</Chip>)}
        </div>
        {p.original_text && <p className="whitespace-pre-line">{p.original_text}</p>}
        {p.text_en && p.text_en !== p.original_text && <p className="text-muted-foreground">English: {p.text_en}</p>}
      </Row>

      {(visuals.length > 0 || p.visual_summaries.length > 0) && (
        <Row icon={CameraIcon} title="Photos, identified components">
          {(visuals.length ? visuals : p.visual_summaries.map((v) => ({ summary: v.summary_text, confidence: v.confidence, classes: [], leds: v.led_states }))).map((v, i) => (
            <div key={i} className="space-y-1.5 rounded-lg border p-2">
              <p>{v.summary}</p>
              {v.classes?.map((c) => <Bar key={c.label} {...c} />)}
              {!!v.leds?.length && <p className="text-xs text-muted-foreground">Lit indicators: {v.leds.map((l) => l.colour).join(", ")}</p>}
            </div>
          ))}
        </Row>
      )}

      {voices.length > 0 && (
        <Row icon={AudioLinesIcon} title="Voice notes">
          {voices.map((t, i) => (
            <p key={i}>
              <span className="text-muted-foreground">{LANG[t.language] ?? t.language}, {Math.round(t.confidence * 100)}% sure: </span>
              {t.text}{t.text_en !== t.text && <span className="block text-muted-foreground">English: {t.text_en}</span>}
            </p>
          ))}
        </Row>
      )}

      <Row icon={TagsIcon} title="Signals">
        <div className="flex flex-wrap gap-1.5">
          <Chip on={s.sentiment !== "neutral"}>sentiment {String(s.sentiment ?? bundle.triage.sentiment)}</Chip>
          <Chip on={!!s.service_down}>service down</Chip>
          <Chip on={!!s.payment_related}>payment</Chip>
          <Chip on={!!s.repeat_contact}>repeat contact</Chip>
          <Chip on={s.outage_scope !== "single"}>scope {String(s.outage_scope ?? "single")}</Chip>
          {(s.urgency_keywords as string[] | undefined)?.map((k) => <Chip key={k} on>{k}</Chip>)}
          {(s.error_codes as string[] | undefined)?.map((k) => <Chip key={k} on>{k}</Chip>)}
        </div>
      </Row>

      <Row icon={GaugeIcon} title="Triage">
        <p>
          {bundle.triage.department.replace(/_/g, " ")}, routed by {bundle.triage.routed_by || "rules"}.
          {cp.intent ? ` Intent read as ${String(cp.intent).replace(/_/g, " ")}.` : ""}
        </p>
        {cp.level != null && (
          <p className="text-muted-foreground">
            TriageModel: {String(cp.band)} urgency, level {String(cp.level)}, score {String(cp.score)} of 100
            {cp.confidence != null ? `, ${Math.round(Number(cp.confidence) * 100)}% sure` : ""}.
          </p>
        )}
      </Row>

      <Row icon={BrainIcon} title="Diagnosis">
        {bundle.diagnosis ? (
          <>
            <p>
              {bundle.diagnosis.fault ? bundle.diagnosis.fault.replace(/^fault_/, "").replace(/_/g, " ") : "No fault named"}
              <span className="text-muted-foreground">, {Math.round(bundle.diagnosis.confidence * 100)}% confidence, via {bundle.diagnosis.via}</span>
            </p>
            {bundle.diagnosis.rationale && <p className="text-muted-foreground">{bundle.diagnosis.rationale}</p>}
          </>
        ) : <p className="text-muted-foreground">No diagnosis was produced.</p>}
        <p className="text-xs text-muted-foreground">
          Record sections present: {bundle.completeness.present.join(", ") || "none"}
          {bundle.completeness.missing.length ? `; missing: ${bundle.completeness.missing.join(", ")}` : ""}.
        </p>
      </Row>

      <details className="pt-2">
        <summary className="cursor-pointer text-xs text-muted-foreground">Fused text, as every stage read it</summary>
        <pre className="mt-2 overflow-x-auto rounded-lg bg-muted/60 p-2 font-mono text-xs whitespace-pre-wrap">{p.fused_text}</pre>
      </details>
    </div>
  );
}
