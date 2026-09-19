"use client";

import { ShieldCheckIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { FocusLayer, originOf, type Origin } from "@/components/fx/focus-layer";
import { Button } from "@/components/ui/button";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { api, post, useApi } from "@/lib/api";
import { cn } from "@/lib/utils";

type Role = { role: string; summary: string; allowed: string[]; impl: string; model_version: string;
  generation: number; probe_status: string; probe_detail: string; probe_ms: number | null };
type Health = { status: "up" | "down" | "off"; ms: number | null; detail: Record<string, unknown> };
type MapData = { services: Record<string, Health>; roles: Role[] };
type Check = { check: string; status: string; ms: number | null; detail: Record<string, unknown> };
type Verdict = { status: "active" | "inactive" | "off"; checks: Check[] };
type Event = { id: string; role: string; from_binding: string; to_binding: string; actor: string; reason: string; at: string };

/** The pipeline, left to right. Ids match the gateway's NODES. */
const STAGES: { id: string; label: string; service: string; role?: string; model: string; col: number; row: number; does: string }[] = [
  { id: "intake", label: "Intake", service: "inquiry", model: "Validation rules", col: 0, row: 1.5, does: "Stores the ticket, its photos and voice notes, and opens a case." },
  { id: "speech", label: "Speech", service: "audio", role: "speech", model: "faster-whisper small", col: 1.3, row: 0, does: "Transcribes voice notes in the language they were spoken, then hands the text to translation." },
  { id: "translate", label: "Translate in", service: "translation", role: "mt_in", model: "NLLB 600M", col: 2.6, row: 0.75, does: "Reads everything the customer said into English: what they typed and what speech transcribed, in Sinhala, Tamil, Singlish or Tanglish." },
  { id: "vision", label: "Photo", service: "image", model: "Router classifier (ONNX)", col: 1.3, row: 2, does: "Recognises which part of the router a photo shows and which lights are lit." },
  { id: "prefetch", label: "Account", service: "business", model: "Account and network record", col: 1.3, row: 3, does: "Fetches the customer's line, bill and area in parallel." },
  { id: "fusion", label: "Fusion", service: "orchestrator", model: "Rules", col: 4, row: 1.5, does: "Joins every branch into one unified ticket, within each branch's time budget." },
  // The reasoning half returns along a second row, right to left, so the map uses the page's height.
  { id: "triage", label: "Triage", service: "triage", model: "TriageModel (MiniLM + 18 signals)", col: 4, row: 4.4, does: "Routes to a department and scores the customer side priority." },
  { id: "diagnose", label: "Diagnose", service: "knowledge", role: "llm_diagnose", model: "MiniLM retrieval + LLM", col: 3, row: 4.4, does: "Retrieves procedures and names the likely fault." },
  { id: "grounding", label: "Grounding", service: "grounding", model: "Rules on the record", col: 2, row: 4.4, does: "Assembles the one bundle the writer may use and scores our side." },
  { id: "draft", label: "Draft", service: "response", role: "llm_draft", model: "LLM", col: 1, row: 4.4, does: "Writes the reply, checks every sentence, releases or holds it." },
  { id: "translate_out", label: "Translate out", service: "translation", role: "mt_out", model: "NLLB 600M, LLM fallback", col: 0, row: 4.4, does: "Puts the reply into the language the customer wrote in. When translation is not running, the LLM translates." },
];
/** Translation sits on the one multilingual input: typed text, and speech after transcription. */
const LINKS: [string, string][] = [
  ["in", "intake"], ["intake", "speech"], ["intake", "translate"], ["speech", "translate"], ["intake", "vision"],
  ["intake", "prefetch"], ["translate", "fusion"], ["vision", "fusion"], ["prefetch", "fusion"], ["fusion", "triage"],
  ["triage", "diagnose"], ["diagnose", "grounding"], ["grounding", "draft"], ["draft", "translate_out"], ["translate_out", "out"],
];
const W = 170;
const H = 84;
const GX = 210;
const GY = 112;
const pos = (col: number, row: number) => ({ x: 70 + col * GX, y: 30 + row * GY });
const ENDS = { in: { x: 16, y: pos(0, 1.5).y }, out: { x: 16, y: pos(0, 4.4).y } };
const CONTENT_W = 70 + 4 * GX + W + 30;
const CONTENT_H = 30 + 4.4 * GY + H + 30;

/** A node's box, and a curve between two: sideways when they sit side by side, downward when stacked. */
function box(id: string) {
  if (id === "in" || id === "out") return { ...ENDS[id], w: 24 };
  const s = STAGES.find((x) => x.id === id)!;
  return { ...pos(s.col, s.row), w: W };
}
function curve(a: ReturnType<typeof box>, b: ReturnType<typeof box>) {
  if (Math.abs(a.x - b.x) < 10) {
    const x = a.x + a.w / 2;
    return `M ${x} ${a.y + H} C ${x} ${a.y + H + 60}, ${x} ${b.y - 60}, ${x} ${b.y}`;
  }
  const dir = b.x > a.x ? 1 : -1;
  const x1 = dir > 0 ? a.x + a.w : a.x;
  const x2 = dir > 0 ? b.x : b.x + b.w;
  const y1 = a.y + H / 2;
  const y2 = b.y + H / 2;
  return `M ${x1} ${y1} C ${x1 + 40 * dir} ${y1}, ${x2 - 40 * dir} ${y2}, ${x2} ${y2}`;
}

/** Model ids each implementation accepts; the first is filled in when you switch to it. */
const MODELS: Record<string, string[]> = {
  ollama: ["gpt-oss:120b-cloud", "gpt-oss:20b-cloud"],
  gemini: ["gemini-3.6-flash", "gemini-2.5-flash", "gemini-2.5-pro"],
  stub: ["stub-generator-1"],
  rules: ["rules"],
  nllb: ["facebook/nllb-200-distilled-600M"],
  google: ["google-translate"],
  passthrough: ["none"],
  whisper: ["faster-whisper-small-int8"],
};

const TONE = { active: "bg-success", inactive: "bg-destructive", off: "bg-muted-foreground/40", unknown: "bg-warning" } as const;
const WORD = { active: "Active", inactive: "Not answering", off: "Not running", unknown: "Not verified" } as const;

export default function Models() {
  const { data, loading, reload } = useApi<MapData>("/admin/models/map");
  const history = useApi<{ events: Event[] }>("/admin/models/history");
  const [sel, setSel] = useState<{ id: string; origin: Origin } | null>(null);
  const [verdicts, setVerdicts] = useState<Record<string, Verdict>>({});
  const [checking, setChecking] = useState<Set<string>>(new Set());
  const [edit, setEdit] = useState<{ impl: string; model_version: string; reason: string } | null>(null);
  // The map spreads across the page: scaled to the available width, no box and no scrollbar.
  const frame = useRef<HTMLDivElement>(null);
  const [fit, setFit] = useState({ scale: 1, offset: 0 });
  useEffect(() => {
    const el = frame.current;
    if (!el) return;
    const measure = () => {
      const scale = Math.min(1.4, el.clientWidth / CONTENT_W);
      setFit({ scale, offset: (el.clientWidth - CONTENT_W * scale) / 2 });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [loading]);

  const role = (id?: string) => data?.roles.find((r) => r.role === id);
  const state = (id: string): keyof typeof WORD => {
    if (verdicts[id]) return verdicts[id].status;
    const s = STAGES.find((x) => x.id === id)!;
    const h = data?.services[s.service];
    if (!h) return "unknown";
    return h.status === "off" ? "off" : h.status === "down" ? "inactive" : "unknown";
  };

  async function verify(id: string) {
    setChecking((c) => new Set(c).add(id));
    try {
      const v = await post<Verdict>(`/admin/models/verify/${id}`);
      setVerdicts((m) => ({ ...m, [id]: v }));
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setChecking((c) => { const n = new Set(c); n.delete(id); return n; });
    }
  }

  async function verifyAll() {
    for (const s of STAGES) await verify(s.id); // in pipeline order, so the map lights up left to right
    void reload();
  }

  async function save(r: Role) {
    if (!edit) return;
    try {
      await api(`/admin/models/${r.role}`, { method: "PUT", body: JSON.stringify({ ...edit, params: {} }) });
      toast.success("Switched. It takes effect on the next case, no restart. Checking it now.");
      setEdit(null);
      setVerdicts((m) => { const n = { ...m }; delete n[sel!.id]; return n; });
      void history.reload();
      // Services rebind within a couple of seconds; then prove the new model actually answers.
      setTimeout(() => { void verify(sel!.id).then(() => reload()); }, 2500);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  const stage = STAGES.find((s) => s.id === sel?.id);
  const bound = role(stage?.role);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Models</h1>
          <p className="text-sm text-muted-foreground">Every stage, the service it runs on and the model inside it. Click one to verify or rebind it.</p>
        </div>
        <Button onClick={verifyAll} disabled={checking.size > 0}><ShieldCheckIcon /> {checking.size ? "Verifying" : "Verify every model"}</Button>
      </div>

      {loading ? <Skeleton className="h-96 rounded-2xl" /> : (
        <div ref={frame} className="relative -mx-4 overflow-hidden md:-mx-6"
             style={{ height: CONTENT_H * fit.scale, background: "radial-gradient(ellipse 62% 48% at 50% 45%, color-mix(in oklch, var(--primary) 14%, transparent), transparent 100%)" }}>
          <div className="relative origin-top-left" style={{ width: CONTENT_W, height: CONTENT_H, transform: `translateX(${fit.offset}px) scale(${fit.scale})` }}>
            <svg className="absolute inset-0 size-full" aria-hidden>
              {LINKS.map(([a, b], i) => {
                const d = curve(box(a), box(b));
                const live = a !== "in" && b !== "out" ? state(a) === "active" && state(b) === "active" : false;
                return (
                  <g key={`${a}-${b}`}>
                    <path d={d} fill="none" strokeWidth={1.5} className={live ? "stroke-success/50" : "stroke-primary/30"} />
                    <path d={d} fill="none" strokeWidth={2.5} pathLength={100} className="link-pulse"
                          stroke={live ? "color-mix(in oklch, var(--success) 40%, white)" : "color-mix(in oklch, var(--primary) 45%, white)"}
                          style={{ "--pulse-dur": "6s", "--pulse-delay": `${i * 0.35}s` } as React.CSSProperties} />
                  </g>
                );
              })}
            </svg>
            {(["in", "out"] as const).map((k) => (
              <div key={k} className="absolute grid size-6 place-items-center rounded-full bg-primary text-[9px] font-semibold text-primary-foreground"
                   style={{ left: ENDS[k].x, top: ENDS[k].y + H / 2 - 12 }} title={k === "in" ? "Customer message" : "Reply to customer"}>
                {k === "in" ? "IN" : "OUT"}
              </div>
            ))}
            {STAGES.map((s) => {
              const p = pos(s.col, s.row);
              const st = state(s.id);
              const r = role(s.role);
              return (
                <button key={s.id} type="button" onClick={(e) => { setEdit(null); setSel({ id: s.id, origin: originOf(e) }); }}
                        className={cn("group absolute flex flex-col justify-between rounded-2xl border bg-card/90 p-3 text-left shadow-sm backdrop-blur transition-all duration-300 hover:-translate-y-1 hover:border-primary/60 hover:shadow-lg hover:shadow-primary/15",
                          checking.has(s.id) && "animate-pulse ring-4 ring-primary/20")}
                        style={{ left: p.x, top: p.y, width: W, height: H }}>
                  <span className="flex items-center justify-between gap-2">
                    <span className="text-sm font-semibold">{s.label}</span>
                    <span className="relative flex size-2.5" title={WORD[st]}>
                      {st === "active" && <span className="absolute inline-flex size-full animate-ping rounded-full bg-success/60" />}
                      <span className={cn("relative inline-flex size-2.5 rounded-full", TONE[st])} />
                    </span>
                  </span>
                  <span className="truncate font-mono text-[11px] text-muted-foreground">{r ? `${r.impl}:${r.model_version}` : s.model}</span>
                  <span className="text-[11px] text-muted-foreground">{s.service} · {WORD[st]}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      <section>
        <h2 className="mb-2 font-medium">History</h2>
        <ul className="space-y-1 text-sm">
          {history.data?.events.slice(0, 10).map((e) => (
            <li key={e.id} className="text-muted-foreground">
              <span className="text-foreground">{e.role.replace(/_/g, " ")}</span> {e.from_binding} to {e.to_binding}, by {e.actor}
              {e.reason && `: ${e.reason}`} ({new Date(e.at).toLocaleString()})
            </li>
          ))}
          {!history.data?.events.length && <li className="text-muted-foreground">No changes yet.</li>}
        </ul>
      </section>

      <FocusLayer open={!!stage} origin={sel?.origin ?? null} onClose={() => setSel(null)} width={400}
                  title={stage?.label ?? ""} subtitle={stage ? `${stage.service} service` : undefined}>
        {stage && (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">{stage.does}</p>
            <div className="rounded-xl border p-3 text-sm">
              <p className="text-xs text-muted-foreground">Model</p>
              <p className="font-mono text-xs">{bound ? `${bound.impl}:${bound.model_version}` : stage.model}</p>
              {bound && <p className="mt-1 text-xs text-muted-foreground">{bound.summary} Generation {bound.generation}.</p>}
            </div>

            <div className="space-y-2">
              <Button className="w-full" onClick={() => verify(stage.id)} disabled={checking.has(stage.id)}>
                <ShieldCheckIcon /> {checking.has(stage.id) ? "Verifying" : "Verify it is active"}
              </Button>
              {verdicts[stage.id] && (
                <ul className="space-y-1.5">
                  {verdicts[stage.id].checks.map((c) => (
                    <li key={c.check} className="rounded-lg border p-2 text-xs">
                      <span className="flex items-center justify-between gap-2">
                        <span className="flex items-center gap-1.5 font-medium">
                          <span className={cn("size-2 rounded-full", c.status === "up" ? "bg-success" : c.status === "off" ? "bg-muted-foreground/40" : "bg-destructive")} />
                          {c.check}
                        </span>
                        {c.ms != null && <span className="tabular-nums text-muted-foreground">{c.ms} ms</span>}
                      </span>
                      <span className="mt-1 block break-words text-muted-foreground">
                        {Object.entries(c.detail).filter(([, v]) => v != null && typeof v !== "object").map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`).join(", ")}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {bound && (edit ? (
              <FieldGroup>
                <Field>
                  <FieldLabel>Implementation</FieldLabel>
                  <Select value={edit.impl} items={bound.allowed.map((a) => ({ value: a, label: a }))}
                          onValueChange={(v) => {
                            const impl = String(v);
                            // A new implementation needs one of its own model ids, not the old one's.
                            const model = impl === bound.impl ? bound.model_version : MODELS[impl]?.[0] ?? edit.model_version;
                            setEdit({ ...edit, impl, model_version: model });
                          }}>
                    <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                    <SelectContent>{bound.allowed.map((a) => <SelectItem key={a} value={a}>{a}</SelectItem>)}</SelectContent>
                  </Select>
                </Field>
                <Field>
                  <FieldLabel htmlFor="mv">Model</FieldLabel>
                  <Input id="mv" list="mv-options" value={edit.model_version} onChange={(e) => setEdit({ ...edit, model_version: e.target.value })} />
                  <datalist id="mv-options">{(MODELS[edit.impl] ?? []).map((m) => <option key={m} value={m} />)}</datalist>
                </Field>
                <Field>
                  <FieldLabel htmlFor="why">Reason</FieldLabel>
                  <Input id="why" value={edit.reason} onChange={(e) => setEdit({ ...edit, reason: e.target.value })} placeholder="Why you are changing it" />
                </Field>
                <div className="flex gap-2">
                  <Button onClick={() => save(bound)}>Save</Button>
                  <Button variant="ghost" onClick={() => setEdit(null)}>Cancel</Button>
                </div>
              </FieldGroup>
            ) : (
              <Button variant="outline" className="w-full" onClick={() => setEdit({ impl: bound.impl, model_version: bound.model_version, reason: "" })}>
                Switch this model
              </Button>
            ))}
          </div>
        )}
      </FocusLayer>
    </div>
  );
}
