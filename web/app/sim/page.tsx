"use client";

import { ActivityIcon, LocateFixedIcon, MinusIcon, PlusIcon, RadioTowerIcon, ServerIcon, TriangleAlertIcon, WrenchIcon, ZapIcon } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { FocusLayer, originOf, type Origin } from "@/components/fx/focus-layer";
import { Count } from "@/components/fx/reveal";
import { Sparkline } from "@/components/sparkline";
import { StatusDot, type Tone } from "@/components/status-dot";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { post, useApi, usePoll } from "@/lib/api";
import { cn } from "@/lib/utils";

type Olt = { olt_id: string; vendor: string; model: string; health: "healthy" | "busy" | "down"; utilisation_pct: number;
  sparkline: number[]; lines: number; lines_down: number };
type Exchange = { code: string; name: string; district: string; olts: Olt[] };
type Sub = { subscriber_id: string; name: string; segment: string; real_customer: boolean; plan_code: string;
  account_status: string; balance_display: string; line_state: string | null; olt_id: string | null };
type Kind = "core" | "district" | "exchange" | "olt" | "customer";
type Node = { id: string; kind: Kind; label: string; x: number; y: number; r: number; parent?: string;
  olt?: Olt; exchange?: Exchange; district?: string; sub?: Sub; health: "healthy" | "busy" | "down" };
type Edge = { id: string; from: string; to: string; kind: "backbone" | "trunk" | "uplink" | "drop"; olt?: Olt; exchange?: Exchange };

/** Customer actions from the graph: problems on their side, and the way back. */
const CUSTOMER_ACTIONS: [string, string][] = [
  ["reset_customer", "Make healthy"], ["drop_cpe", "Unplug the router"], ["restore_cpe", "Plug the router back"],
  ["firmware_crashloop", "Router restart loop"], ["line_degradation", "Weaken the signal"],
  ["fup_exceeded", "Use up the data"], ["suspend_account", "Pause for non payment"], ["restore_account", "Settle and restore"],
];

/** Fan an OLT's customers out beyond it, so every one of them is a node you can reach. */
function withCustomers(base: { nodes: Node[]; edges: Edge[] }, oltId: string | null, subs: Sub[]) {
  const olt = oltId ? base.nodes.find((n) => n.id === `o:${oltId}`) : undefined;
  if (!olt || !subs.length) return base;
  const a = Math.atan2(olt.y, olt.x);
  const n = subs.length;
  const spread = Math.min(1.7, 0.045 * n + 0.2);
  const nodes = [...base.nodes];
  const edges = [...base.edges];
  subs.forEach((s, i) => {
    const t = n === 1 ? 0.5 : i / (n - 1);
    const ang = a - spread / 2 + spread * t;
    const r = RING.olt + 64 + (i % 3) * 30;
    const health: Node["health"] = s.account_status === "suspended" || s.line_state === "down" ? "down"
      : s.line_state === "up" ? "healthy" : "busy";
    const id = `c:${s.subscriber_id}`;
    nodes.push({ id, kind: "customer", label: s.name, x: Math.cos(ang) * r, y: Math.sin(ang) * r, r: 4.5, parent: olt.id, sub: s, health });
    edges.push({ id: `${olt.id}-${id}`, from: olt.id, to: id, kind: "drop" });
  });
  return { nodes, edges };
}
type Selection = { type: "node"; node: Node; origin: Origin } | { type: "edge"; edge: Edge; origin: Origin };

const TONE: Record<string, Tone> = { healthy: "ok", busy: "warn", down: "bad" };
const WORD: Record<string, string> = { healthy: "Healthy", busy: "Busy", down: "Incident open" };
/** Colour token for each sphere and link end. */
const SPHERE: Record<string, string> = { healthy: "--success", busy: "--warning", down: "--destructive", core: "--primary", hub: "--chart-3" };
const STROKE: Record<string, string> = { healthy: "stroke-success", busy: "stroke-warning", down: "stroke-destructive" };
const RING = { district: 170, exchange: 330, olt: 470 };
/** The graph melts into the page on every side instead of stopping at a hard edge. */
const EDGE_FADE = "linear-gradient(to bottom, transparent, #000 14%, #000 86%, transparent), linear-gradient(to right, transparent, #000 8%, #000 92%, transparent)";
const worst = (hs: string[]) => (hs.includes("down") ? "down" : hs.includes("busy") ? "busy" : "healthy") as Node["health"];

/** Radial tree: the core in the middle, districts, exchanges and OLTs on rings, each wedge sized by its OLTs. */
function layout(exchanges: Exchange[]): { nodes: Node[]; edges: Edge[] } {
  const districts = [...new Set(exchanges.map((e) => e.district))].sort();
  const total = Math.max(1, exchanges.reduce((s, e) => s + Math.max(1, e.olts.length), 0));
  const polar = (a: number, r: number) => ({ x: Math.cos(a) * r, y: Math.sin(a) * r });
  const nodes: Node[] = [{ id: "core", kind: "core", label: "Lanka Link core", x: 0, y: 0, r: 26,
    health: worst(exchanges.flatMap((e) => e.olts.map((o) => o.health))) }];
  const edges: Edge[] = [];
  let cursor = -Math.PI / 2;
  for (const d of districts) {
    const exs = exchanges.filter((e) => e.district === d);
    const span = (exs.reduce((s, e) => s + Math.max(1, e.olts.length), 0) / total) * Math.PI * 2;
    const dId = `d:${d}`;
    nodes.push({ id: dId, kind: "district", label: d, ...polar(cursor + span / 2, RING.district), r: 16, parent: "core",
      district: d, health: worst(exs.flatMap((e) => e.olts.map((o) => o.health))) });
    edges.push({ id: `core-${dId}`, from: "core", to: dId, kind: "backbone" });
    let exCursor = cursor;
    for (const ex of exs) {
      const exSpan = (Math.max(1, ex.olts.length) / total) * Math.PI * 2;
      const eId = `e:${ex.code}`;
      nodes.push({ id: eId, kind: "exchange", label: ex.name, ...polar(exCursor + exSpan / 2, RING.exchange), r: 12,
        parent: dId, exchange: ex, health: worst(ex.olts.map((o) => o.health)) });
      edges.push({ id: `${dId}-${eId}`, from: dId, to: eId, kind: "trunk", exchange: ex });
      ex.olts.forEach((o, i) => {
        const a = exCursor + (exSpan * (i + 0.5)) / Math.max(1, ex.olts.length);
        const oId = `o:${o.olt_id}`;
        nodes.push({ id: oId, kind: "olt", label: o.olt_id, ...polar(a, RING.olt), r: 6 + Math.min(6, o.lines / 40),
          parent: eId, olt: o, exchange: ex, health: o.health });
        edges.push({ id: `${eId}-${oId}`, from: eId, to: oId, kind: "uplink", olt: o, exchange: ex });
      });
      exCursor += exSpan;
    }
    cursor += span;
  }
  return { nodes, edges };
}

function Stat({ label, value, icon: Icon, tone }: { label: string; value: number; icon: typeof ServerIcon; tone: string }) {
  return (
    <div className="rounded-2xl border border-foreground/10 bg-card/60 p-4 backdrop-blur">
      <p className="flex items-center gap-2 text-xs text-muted-foreground"><Icon className={cn("size-3.5", tone)} />{label}</p>
      <p className="mt-3 font-pixel text-4xl leading-none"><Count value={value} /></p>
    </div>
  );
}

export default function NetworkGraph() {
  const { data, loading, reload } = useApi<{ exchanges: Exchange[] }>("/sim/network");
  usePoll(reload, 5000);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [focusSub, setFocusSub] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const people = useApi<{ subscribers: Sub[] }>(expanded ? `/sim/subscribers?olt=${expanded}&limit=200` : null);
  const found = useApi<{ subscribers: Sub[] }>(q.trim().length >= 2 ? `/sim/subscribers?q=${encodeURIComponent(q.trim())}&limit=6` : null);
  const base = useMemo(() => layout(data?.exchanges ?? []), [data]);
  const shown = useMemo(() => {
    const all = people.data?.subscribers ?? [];
    const first = all.slice(0, 60);
    const focused = all.find((s) => s.subscriber_id === focusSub);
    return focused && !first.includes(focused) ? [...first, focused] : first;
  }, [people.data, focusSub]);
  const { nodes, edges } = useMemo(() => withCustomers(base, expanded, shown), [base, expanded, shown]);
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);

  const box = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const drag = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [sel, setSel] = useState<Selection | null>(null);
  const [busy, setBusy] = useState(false);

  const fit = useCallback(() => {
    const el = box.current;
    if (!el) return;
    const { width, height } = el.getBoundingClientRect();
    setView({ x: width / 2, y: height / 2, k: Math.min(width, height) / (2 * (RING.olt + 70)) });
  }, []);
  useEffect(() => { fit(); window.addEventListener("resize", fit); return () => window.removeEventListener("resize", fit); }, [fit, loading]);

  // Wheel zooms around the pointer; React's wheel listener is passive, so bind it by hand.
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const cx = e.clientX - r.left;
      const cy = e.clientY - r.top;
      setView((v) => {
        const k = Math.min(3.5, Math.max(0.35, v.k * Math.exp(-e.deltaY * 0.0015)));
        return { k, x: cx - ((cx - v.x) * k) / v.k, y: cy - ((cy - v.y) * k) / v.k };
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [loading]);

  // A searched customer: bring their node to the middle and open them.
  useEffect(() => {
    if (!focusSub) return;
    const node = byId.get(`c:${focusSub}`);
    const el = box.current;
    if (!node || !el) return;
    const r = el.getBoundingClientRect();
    setView((v) => {
      const k = Math.max(v.k, 1.4);
      return { k, x: r.width / 2 - node.x * k, y: r.height / 2 - node.y * k };
    });
    const t = setTimeout(() => {
      const target = el.querySelector(`[data-node="${node.id}"]`);
      if (target) setSel({ type: "node", node, origin: originOf({ currentTarget: target }) });
      setFocusSub(null);
    }, 120);
    return () => clearTimeout(t);
  }, [focusSub, byId]);

  const zoom = (f: number) => setView((v) => {
    const el = box.current!.getBoundingClientRect();
    const k = Math.min(3.5, Math.max(0.35, v.k * f));
    return { k, x: el.width / 2 - ((el.width / 2 - v.x) * k) / v.k, y: el.height / 2 - ((el.height / 2 - v.y) * k) / v.k };
  });

  // Hovering lights the path to the core and everything underneath; a selection keeps it lit
  // while its window is open.
  const picked = sel?.type === "node" ? sel.node.id : sel?.type === "edge" ? sel.edge.to : null;
  const focus = hover ?? picked;
  const lit = useMemo(() => {
    if (!focus) return null;
    const set = new Set<string>([focus]);
    for (let n = byId.get(focus); n?.parent; n = byId.get(n.parent)) set.add(n.parent);
    const down = (id: string) => nodes.filter((n) => n.parent === id).forEach((c) => { set.add(c.id); down(c.id); });
    down(focus);
    return set;
  }, [focus, byId, nodes]);
  const dim = (id: string) => lit !== null && !lit.has(id);

  async function act(name: string, body: Record<string, unknown>, done: string) {
    setBusy(true);
    try {
      await post(`/sim/scenarios/${name}`, body);
      toast.success(done);
      void reload();
      void people.reload();
      setSel(null);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const all = data?.exchanges.flatMap((e) => e.olts) ?? [];
  const count = (h: string) => all.filter((o) => o.health === h).length;
  const openNode = (node: Node, e: { clientX?: number; clientY?: number; currentTarget?: EventTarget | null }) => {
    if (drag.current?.moved) return;
    setSel({ type: "node", node, origin: originOf(e) });
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="pixel-label text-[15px] text-primary">Simulation</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">Network</h1>
          <p className="mt-1 text-sm text-muted-foreground">Drag to move, scroll to zoom, hover to trace a path, click any node or link to act on it.</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Exchanges" value={data?.exchanges.length ?? 0} icon={RadioTowerIcon} tone="text-primary" />
        <Stat label="Healthy OLTs" value={count("healthy")} icon={ServerIcon} tone="text-success" />
        <Stat label="Busy or down" value={count("busy") + count("down")} icon={TriangleAlertIcon} tone="text-warning" />
        <Stat label="Lines down" value={all.reduce((s, o) => s + o.lines_down, 0)} icon={ZapIcon} tone="text-destructive" />
      </div>

      <div className="relative z-20 flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-sm">
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a customer by name, email or SUB number"
                 aria-label="Find a customer" className="h-10 rounded-full bg-background/60 px-4 backdrop-blur" />
          {q.trim().length >= 2 && !!found.data?.subscribers.length && (
            <ul className="absolute mt-2 w-full overflow-hidden rounded-2xl border bg-popover/95 p-1 shadow-xl backdrop-blur-xl">
              {found.data.subscribers.map((s) => (
                <li key={s.subscriber_id}>
                  <button type="button" className="flex w-full items-center justify-between gap-2 rounded-xl px-3 py-2 text-left text-sm hover:bg-muted"
                          onClick={() => {
                            if (!s.olt_id) return toast.error("That customer is on mobile data, not on an OLT.");
                            setExpanded(s.olt_id);
                            setFocusSub(s.subscriber_id);
                            setQ("");
                          }}>
                    <span className="truncate">{s.name}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">{s.subscriber_id}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        {expanded && (
          <Button size="sm" variant="ghost" onClick={() => setExpanded(null)}>
            Hide customers of {expanded}{people.data && people.data.subscribers.length > 60 ? ` (showing 60 of ${people.data.subscribers.length})` : ""}
          </Button>
        )}
      </div>

      {loading ? <Skeleton className="h-[70svh] rounded-2xl" /> : (
        <div ref={box}
             className="relative -mx-4 h-[68svh] touch-none overflow-hidden select-none md:-mx-6 md:h-[76svh] lg:-mx-8"
             onPointerDown={(e) => { drag.current = { x: e.clientX, y: e.clientY, moved: false }; }}
             onPointerMove={(e) => {
               const d = drag.current;
               if (!d || e.buttons !== 1) return;
               const dx = e.clientX - d.x;
               const dy = e.clientY - d.y;
               if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
               d.x = e.clientX;
               d.y = e.clientY;
               if (d.moved) setView((v) => ({ ...v, x: v.x + dx, y: v.y + dy }));
             }}
             onPointerUp={() => setTimeout(() => { drag.current = null; }, 0)}>
          <svg className={cn("size-full", drag.current?.moved ? "cursor-grabbing" : "cursor-grab")} role="group" aria-label="Network graph"
               style={{ maskImage: EDGE_FADE, WebkitMaskImage: EDGE_FADE, maskComposite: "intersect", WebkitMaskComposite: "source-in" }}>
            <defs>
              <radialGradient id="core-glow">
                <stop offset="0%" style={{ stopColor: "var(--primary)", stopOpacity: 0.55 }} />
                <stop offset="100%" style={{ stopColor: "var(--primary)", stopOpacity: 0 }} />
              </radialGradient>
              <radialGradient id="halo">
                <stop offset="0%" style={{ stopColor: "var(--primary)", stopOpacity: 0.18 }} />
                <stop offset="70%" style={{ stopColor: "var(--primary)", stopOpacity: 0.04 }} />
                <stop offset="100%" style={{ stopColor: "var(--primary)", stopOpacity: 0 }} />
              </radialGradient>
              {/* Lit spheres: a highlight up and to the left, the colour, then shade. */}
              {Object.entries(SPHERE).map(([k, v]) => (
                <radialGradient key={k} id={`sphere-${k}`} cx="0.35" cy="0.3" r="0.75">
                  <stop offset="0%" style={{ stopColor: `color-mix(in oklch, var(${v}) 25%, white)` }} />
                  <stop offset="45%" style={{ stopColor: `var(${v})` }} />
                  <stop offset="100%" style={{ stopColor: `color-mix(in oklch, var(${v}) 40%, black)` }} />
                </radialGradient>
              ))}
              {/* Each link runs from the violet of the core toward the colour of what it feeds. */}
              {edges.map((e, i) => {
                const a = byId.get(e.from)!;
                const b = byId.get(e.to)!;
                return (
                  <linearGradient key={e.id} id={`eg-${i}`} gradientUnits="userSpaceOnUse" x1={a.x} y1={a.y} x2={b.x} y2={b.y}>
                    <stop offset="0%" style={{ stopColor: "var(--primary)", stopOpacity: 0.85 }} />
                    <stop offset="100%" style={{ stopColor: `var(${e.olt ? SPHERE[e.olt.health] : e.kind === "drop" ? SPHERE[b.health] : SPHERE.hub})`, stopOpacity: 0.95 }} />
                  </linearGradient>
                );
              })}
            </defs>
            <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
              <circle r={RING.olt + 140} fill="url(#halo)" />
              {[RING.district, RING.exchange, RING.olt].map((r) => (
                <circle key={r} r={r} fill="none" className="stroke-border" strokeDasharray="2 8" strokeWidth={1 / view.k} />
              ))}
              {edges.map((e, i) => {
                const a = byId.get(e.from)!;
                const b = byId.get(e.to)!;
                const util = e.olt?.utilisation_pct ?? 30;
                const health = e.olt?.health ?? byId.get(e.to)!.health;
                const path = `M ${a.x} ${a.y} Q ${(a.x + b.x) / 2 * 0.92} ${(a.y + b.y) / 2 * 0.92} ${b.x} ${b.y}`;
                return (
                  <g key={e.id} className={cn("transition-opacity duration-500 ease-out", (dim(e.from) || dim(e.to)) && "opacity-10")}>
                    {/* A steady translucent link; a light crosses it now and then, more often the busier it is. */}
                    <path d={path} fill="none" strokeLinecap="round" stroke={`url(#eg-${i})`}
                          className={health === "down" ? "opacity-25" : "opacity-40"}
                          strokeWidth={e.kind === "backbone" ? 3 : e.kind === "trunk" ? 2 : e.kind === "drop" ? 0.8 : 1 + util / 30} />
                    {health !== "down" && (
                      <path d={path} fill="none" pathLength={100} className="link-pulse pointer-events-none"
                            stroke={`color-mix(in oklch, var(${e.olt ? SPHERE[e.olt.health] : SPHERE.hub}) 35%, white)`}
                            strokeWidth={(e.kind === "backbone" ? 3 : e.kind === "trunk" ? 2 : e.kind === "drop" ? 0.8 : 1 + util / 30) + 0.6}
                            style={{ "--pulse-dur": `${Math.max(3.5, 10 - util / 12)}s`, "--pulse-delay": `${-((i * 1.618) % 10)}s` } as React.CSSProperties} />
                    )}
                    <path d={path} fill="none" stroke="transparent" strokeWidth={14 / view.k} className="cursor-pointer"
                          onClick={(ev) => !drag.current?.moved && setSel({ type: "edge", edge: e, origin: originOf(ev) })}>
                      <title>{e.kind === "uplink" ? `${e.olt?.olt_id} uplink, ${Math.round(util)}% used` : "Backbone link"}</title>
                    </path>
                  </g>
                );
              })}
              {nodes.map((n) => (
                <g key={n.id} data-node={n.id} transform={`translate(${n.x} ${n.y})`} tabIndex={0} role="button"
                   aria-label={`${n.label}, ${WORD[n.health]}`}
                   className={cn("cursor-pointer outline-none transition-opacity duration-500 ease-out", dim(n.id) && "opacity-15")}
                   onPointerEnter={() => setHover(n.id)} onPointerLeave={() => setHover(null)}
                   onFocus={() => setHover(n.id)} onBlur={() => setHover(null)}
                   onClick={(e) => openNode(n, e)}
                   onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && openNode(n, { currentTarget: e.currentTarget })}>
                  {n.kind === "core" && <circle r={70} fill="url(#core-glow)" className="animate-pulse" />}
                  {/* The ring of the node under the pointer or selected: it grows in, and stays while selected. */}
                  <circle r={n.r + 6} strokeWidth={2 / Math.max(1, view.k)} style={{ transformBox: "fill-box", transformOrigin: "center" }}
                          className={cn("fill-primary/10 stroke-primary transition-[transform,opacity] duration-500 ease-[cubic-bezier(0.32,0.72,0,1)]",
                            focus === n.id ? "scale-100 opacity-100" : "scale-50 opacity-0")} />
                  {picked === n.id && <circle r={n.r + 6} className="animate-ping fill-none stroke-primary/60" strokeWidth={1} style={{ transformBox: "fill-box", transformOrigin: "center", animationDuration: "2.4s" }} />}
                  <circle r={n.r}
                          fill={`url(#sphere-${n.kind === "core" ? "core" : n.kind === "olt" || n.kind === "customer" ? n.health : "hub"})`}
                          className={cn(n.kind !== "core" && n.kind !== "olt" && STROKE[n.health], n.health === "down" && n.kind === "olt" && "animate-pulse")}
                          strokeWidth={n.kind === "olt" || n.kind === "core" ? 0 : 1.5}
                          style={{ filter: "drop-shadow(0 6px 10px rgba(0,0,0,0.55))" }} />
                  {n.kind === "core" && <circle r={8} className="fill-gold" />}
                  {((n.kind !== "olt" && n.kind !== "customer") || view.k > (n.kind === "customer" ? 1.8 : 1.25) || hover === n.id) && (
                    <text y={n.r + 14} textAnchor="middle" className="fill-foreground text-[11px] font-medium"
                          style={{ paintOrder: "stroke", stroke: "var(--card)", strokeWidth: 4 }}>
                      {n.kind === "olt" ? n.label.split("-").slice(-2).join("-") : n.kind === "customer" ? n.label.split(" ")[0] : n.label}
                    </text>
                  )}
                </g>
              ))}
            </g>
          </svg>

          <div className="absolute bottom-3 left-3 flex max-w-[calc(100%-5rem)] flex-wrap gap-x-3 gap-y-1 rounded-2xl border border-foreground/10 bg-background/70 px-3 py-2 text-xs backdrop-blur-xl">
            {(["healthy", "busy", "down"] as const).map((h) => <StatusDot key={h} tone={TONE[h]} label={WORD[h]} />)}
            <span className="text-muted-foreground max-sm:hidden">Line thickness is uplink load</span>
          </div>
          <div className="absolute right-3 bottom-3 flex flex-col gap-1 rounded-full border border-foreground/10 bg-background/70 p-1 backdrop-blur-xl">
            <Button size="icon-sm" variant="ghost" aria-label="Zoom in" onClick={() => zoom(1.25)}><PlusIcon /></Button>
            <Button size="icon-sm" variant="ghost" aria-label="Zoom out" onClick={() => zoom(0.8)}><MinusIcon /></Button>
            <Button size="icon-sm" variant="ghost" aria-label="Fit the network" onClick={fit}><LocateFixedIcon /></Button>
          </div>
        </div>
      )}

      <FocusLayer open={sel !== null} origin={sel?.origin ?? null} onClose={() => setSel(null)}
                  title={sel?.type === "edge" ? (sel.edge.kind === "uplink" ? `${sel.edge.olt?.olt_id} uplink` : "Backbone link") : sel?.node.label ?? ""}
                  subtitle={sel?.type === "node" ? { core: "Core network", district: "District", exchange: "Exchange", olt: sel.node.olt ? `${sel.node.olt.vendor} ${sel.node.olt.model}` : "OLT", customer: `${sel.node.sub?.subscriber_id ?? ""}, on ${sel.node.parent?.slice(2) ?? ""}` }[sel.node.kind] : sel?.edge.exchange?.name}>
        {sel?.type === "node" && sel.node.kind === "core" && (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">{data?.exchanges.length} exchanges, {all.length} OLTs, {all.reduce((s, o) => s + o.lines, 0)} lines.</p>
            <div className="grid gap-2">
              <Button variant="outline" disabled={busy} onClick={() => act("resolve_outages", {}, "Every incident resolved")}><WrenchIcon /> Resolve every incident</Button>
              <Button variant="outline" disabled={busy} onClick={() => act("relieve_uplink", {}, "Uplinks back to normal")}><ActivityIcon /> Relieve every uplink</Button>
            </div>
          </div>
        )}
        {sel?.type === "node" && (sel.node.kind === "district" || sel.node.kind === "exchange") && (() => {
          const olts = sel.node.kind === "exchange" ? sel.node.exchange!.olts
            : data!.exchanges.filter((e) => e.district === sel.node.district).flatMap((e) => e.olts);
          return (
            <div className="space-y-3">
              <StatusDot tone={TONE[sel.node.health]} label={WORD[sel.node.health]} />
              <p className="text-sm text-muted-foreground">{olts.length} OLTs, {olts.reduce((s, o) => s + o.lines, 0)} lines, {olts.reduce((s, o) => s + o.lines_down, 0)} down.</p>
              <ul className="max-h-56 divide-y overflow-y-auto rounded-xl border">
                {olts.map((o) => (
                  <li key={o.olt_id}>
                    <button type="button" className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-muted"
                            onClick={(e) => setSel({ type: "node", node: byId.get(`o:${o.olt_id}`)!, origin: originOf(e) })}>
                      <StatusDot tone={TONE[o.health]} label={o.olt_id} />
                      <span className="tabular-nums text-muted-foreground">{Math.round(o.utilisation_pct)}%</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          );
        })()}
        {sel?.type === "node" && sel.node.kind === "olt" && sel.node.olt && (() => {
          const o = all.find((x) => x.olt_id === sel.node.olt!.olt_id) ?? sel.node.olt;
          return (
            <div className="space-y-4">
              <StatusDot tone={TONE[o.health]} label={WORD[o.health]} />
              <dl className="grid grid-cols-3 gap-2 text-center">
                {([["Lines", o.lines], ["Down", o.lines_down], ["Uplink", `${Math.round(o.utilisation_pct)}%`]] as const).map(([k, v]) => (
                  <div key={k} className="rounded-xl border p-2"><dd className="font-semibold tabular-nums">{v}</dd><dt className="text-xs text-muted-foreground">{k}</dt></div>
                ))}
              </dl>
              <Sparkline values={o.sparkline} className="h-14 w-full" />
              <div className="grid gap-2">
                <Button variant="outline" disabled={busy} onClick={() => act("open_outage", { olt_ref: o.olt_id }, "Fibre break opened")}><TriangleAlertIcon /> Open a fibre break</Button>
                <Button variant="outline" disabled={busy} onClick={() => act("planned_work", { olt_ref: o.olt_id }, "Maintenance scheduled")}><WrenchIcon /> Schedule maintenance</Button>
                <Button variant="secondary" onClick={() => { setExpanded(expanded === o.olt_id ? null : o.olt_id); setSel(null); }}>
                  {expanded === o.olt_id ? "Hide its customers" : `Show its ${o.lines} customers`}
                </Button>
              </div>
            </div>
          );
        })()}
        {sel?.type === "node" && sel.node.kind === "customer" && sel.node.sub && (() => {
          const s = sel.node.sub;
          return (
            <div className="space-y-4">
              <StatusDot tone={TONE[sel.node.health]}
                         label={s.account_status === "suspended" ? "Paused for non payment" : s.line_state === "up" ? "Line up" : `Line ${s.line_state ?? "unknown"}`} />
              <dl className="grid grid-cols-2 gap-2 text-sm">
                {([["Plan", s.plan_code], ["Account", s.account_status], ["Balance", s.balance_display], ["Segment", s.segment]] as const).map(([k, v]) => (
                  <div key={k} className="rounded-xl border p-2"><dt className="text-xs text-muted-foreground">{k}</dt><dd className="font-medium capitalize">{v}</dd></div>
                ))}
              </dl>
              <div className="grid grid-cols-2 gap-2">
                {CUSTOMER_ACTIONS.map(([name, label]) => (
                  <Button key={name} size="sm" variant={name === "reset_customer" ? "default" : "outline"} disabled={busy}
                          onClick={() => act(name, { subscriber_ref: s.subscriber_id }, label)}>
                    {label}
                  </Button>
                ))}
              </div>
              <Link href={`/sim/lab?sub=${s.subscriber_id}`} className={buttonVariants({ variant: "secondary", className: "w-full" })}>
                Send a test ticket as {s.name.split(" ")[0]}
              </Link>
            </div>
          );
        })()}
        {sel?.type === "edge" && (
          <div className="space-y-4">
            {sel.edge.olt ? (
              <>
                <p className="text-sm text-muted-foreground">From {sel.edge.exchange?.name} to {sel.edge.olt.olt_id}, carrying {Math.round(sel.edge.olt.utilisation_pct)}% of capacity.</p>
                <Sparkline values={sel.edge.olt.sparkline} className="h-14 w-full" />
                <div className="grid gap-2">
                  <Button variant="outline" disabled={busy} onClick={() => act("congest_uplink", { olt_ref: sel.edge.olt!.olt_id }, "Uplink congested")}><ActivityIcon /> Congest this uplink</Button>
                  <Button variant="outline" disabled={busy} onClick={() => act("relieve_uplink", {}, "Uplinks back to normal")}>Relieve every uplink</Button>
                </div>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">Backbone capacity between the core and {byId.get(sel.edge.to)?.label}. Faults here are simulated on the OLT uplinks below it.</p>
            )}
          </div>
        )}
      </FocusLayer>
    </div>
  );
}
