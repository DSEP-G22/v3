"use client";

import { NetworkIcon, UserIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api, post, useApi, usePoll } from "@/lib/api";
import { cn } from "@/lib/utils";

type Scenario = { name: string; description: string; needs_subscriber: boolean };
type Fault = { id: string; kind: string; label: string; target_kind: string; target_ref: string; source: string;
  started_display: string; eta_display: string | null };
type Exchange = { name: string; olts: { olt_id: string; health: string }[] };

/** Scenarios that act on shared equipment; everything else acts on one customer. */
const NETWORK = new Set(["open_outage", "congest_uplink", "resolve_outages", "relieve_uplink"]);
const title = (s: string) => s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

export default function Incidents() {
  const list = useApi<{ scenarios: Scenario[] }>("/sim/scenarios");
  const faults = useApi<{ faults: Fault[] }>("/sim/faults");
  const network = useApi<{ exchanges: Exchange[] }>("/sim/network");
  const people = useApi<{ subscribers: { subscriber_id: string; name: string }[] }>("/sim/subscribers?q=SUB-10000&limit=8");
  const [tab, setTab] = useState<"network" | "customer">("network");
  const [olt, setOlt] = useState("");
  const [target, setTarget] = useState("SUB-100002");
  const [busy, setBusy] = useState<string | null>(null);
  usePoll(faults.reload, 4000);

  const olts = useMemo(() => network.data?.exchanges.flatMap((e) => e.olts.map((o) => ({ ...o, exchange: e.name }))) ?? [], [network.data]);
  const chosenOlt = olt || olts[0]?.olt_id || "";
  const shown = (list.data?.scenarios ?? []).filter((s) => (tab === "network") === NETWORK.has(s.name));
  const board = (faults.data?.faults ?? []).filter((f) => (tab === "network") === NETWORK.has(f.kind));

  async function run(s: Scenario) {
    setBusy(s.name);
    const body = !s.needs_subscriber ? {} : tab === "network" ? { olt_ref: chosenOlt } : { subscriber_ref: target };
    try {
      await post(`/sim/scenarios/${s.name}`, body);
      toast.success("Injected");
      void faults.reload();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Incidents</h1>
          <p className="text-muted-foreground">Break things on purpose, then watch the tickets that follow.</p>
        </div>
        <div className="flex gap-1 rounded-full border bg-card p-1" role="tablist" aria-label="Scope">
          {([["network", "Network", NetworkIcon], ["customer", "Customers", UserIcon]] as const).map(([key, label, Icon]) => (
            <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => setTab(key)}
                    className={cn("flex items-center gap-1.5 rounded-full px-4 py-1.5 text-sm transition-colors",
                      tab === key ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")}>
              <Icon className="size-4" /> {label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 rounded-2xl border bg-secondary/40 p-3">
        {tab === "network" ? (
          <>
            <span className="text-sm text-muted-foreground">Equipment</span>
            <select value={chosenOlt} onChange={(e) => setOlt(e.target.value)} aria-label="Equipment"
                    className="h-8 rounded-lg border bg-background px-2 text-sm">
              {olts.map((o) => <option key={o.olt_id} value={o.olt_id}>{o.olt_id}, {o.exchange} ({o.health})</option>)}
            </select>
          </>
        ) : (
          <>
            <span className="text-sm text-muted-foreground">Customer</span>
            <Input value={target} onChange={(e) => setTarget(e.target.value)} className="h-8 w-36" aria-label="Customer" />
            {people.data?.subscribers.map((p) => (
              <Button key={p.subscriber_id} size="xs" variant={target === p.subscriber_id ? "secondary" : "ghost"} onClick={() => setTarget(p.subscriber_id)}>
                {p.name.split(" ")[0]}
              </Button>
            ))}
          </>
        )}
      </div>

      {list.loading ? <Skeleton className="h-60 rounded-2xl" /> : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {shown.map((s) => (
            <article key={s.name} className="flex flex-col justify-between gap-4 rounded-2xl border bg-card p-4 transition-shadow hover:shadow-md">
              <div>
                <h3 className="font-medium">{title(s.name)}</h3>
                <p className="mt-1 text-sm text-muted-foreground">{s.description}</p>
              </div>
              <Button size="sm" variant="outline" className="self-start" disabled={busy !== null} onClick={() => run(s)}>
                {busy === s.name ? "Injecting" : !s.needs_subscriber ? "Run" : tab === "network" ? `Inject on ${chosenOlt}` : `Inject on ${target}`}
              </Button>
            </article>
          ))}
        </div>
      )}

      <section className="space-y-2">
        <h2 className="flex items-center gap-2 font-medium">
          Active {tab === "network" ? "network" : "customer"} faults
          <span className="relative flex size-2"><span className="absolute inline-flex size-full animate-ping rounded-full bg-primary/60" /><span className="relative inline-flex size-2 rounded-full bg-primary" /></span>
        </h2>
        {!board.length ? <p className="text-muted-foreground">Nothing is injected right now.</p> : (
          <ul className="grid gap-2 md:grid-cols-2">
            {board.map((f) => (
              <li key={f.id} className="flex items-center justify-between gap-3 rounded-xl border bg-card p-3">
                <div className="min-w-0">
                  <p className="truncate font-medium">{f.label}{f.source === "random" && <span className="text-muted-foreground"> (random)</span>}</p>
                  <p className="text-xs text-muted-foreground">{f.target_ref}, started {f.started_display}{f.eta_display ? `, ends ${f.eta_display}` : ""}</p>
                </div>
                <Button size="xs" variant="ghost" onClick={async () => {
                  await api(`/sim/faults/${f.id}`, { method: "DELETE" }).catch((e) => toast.error((e as Error).message));
                  void faults.reload();
                }}>Clear</Button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
