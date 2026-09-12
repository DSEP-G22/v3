"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Sparkline } from "@/components/sparkline";
import { StatusDot, type Tone } from "@/components/status-dot";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { post, useApi } from "@/lib/api";

type Olt = { olt_id: string; vendor: string; model: string; health: string; utilisation_pct: number;
  sparkline: number[]; lines: number; lines_down: number };
type Network = { exchanges: { code: string; name: string; district: string; olts: Olt[] }[] };
type Sub = { subscriber_id: string; name: string; line_state: string | null; account_status: string };

const TONE: Record<string, Tone> = { healthy: "ok", busy: "warn", down: "bad" };
const WORD: Record<string, string> = { healthy: "Healthy", busy: "Busy", down: "Incident open" };

export default function NetworkPage() {
  const { data, loading, reload } = useApi<Network>("/sim/network");
  const [olt, setOlt] = useState<Olt | null>(null);
  const subs = useApi<{ subscribers: Sub[] }>(olt ? `/sim/subscribers?olt=${olt.olt_id}&limit=100` : null);

  async function inject(name: string) {
    const target = subs.data?.subscribers.find((s) => s.line_state !== null);
    if (!target) return toast.error("No customer on this OLT to anchor the scenario to.");
    try {
      await post(`/sim/scenarios/${name}`, { subscriber_ref: target.subscriber_id });
      toast.success("Injected");
      void reload();
      void subs.reload();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold tracking-tight">Network</h1>
      {loading ? <Skeleton className="h-96" /> : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data?.exchanges.map((ex) => (
            <Card key={ex.code} size="sm">
              <CardHeader>
                <CardTitle>{ex.name}</CardTitle>
                <CardDescription>{ex.district}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {ex.olts.map((o) => (
                  <button key={o.olt_id} type="button" onClick={() => setOlt(o)}
                          className="flex w-full items-center justify-between gap-3 rounded-md px-2 py-1.5 text-left hover:bg-muted">
                    <span>
                      <span className="block font-medium">{o.olt_id}</span>
                      <StatusDot tone={TONE[o.health] ?? "idle"} label={WORD[o.health] ?? o.health} className="text-xs" />
                    </span>
                    <span className="flex items-center gap-2 text-xs text-muted-foreground tabular-nums">
                      <Sparkline values={o.sparkline} />
                      {Math.round(o.utilisation_pct)}%
                    </span>
                  </button>
                ))}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Sheet open={olt !== null} onOpenChange={(o) => !o && setOlt(null)}>
        <SheetContent>
          {olt && (
            <>
              <SheetHeader>
                <SheetTitle>{olt.olt_id}</SheetTitle>
                <SheetDescription>
                  {olt.vendor} {olt.model}. {olt.lines} lines, {olt.lines_down} down, uplink {Math.round(olt.utilisation_pct)}% used.
                </SheetDescription>
              </SheetHeader>
              <div className="flex flex-wrap gap-2 px-4">
                <Button size="sm" variant="outline" onClick={() => inject("open_outage")}>Open an outage</Button>
                <Button size="sm" variant="outline" onClick={() => inject("congest_uplink")}>Congest the uplink</Button>
                <Button size="sm" variant="outline" onClick={() => inject("planned_work")}>Schedule maintenance</Button>
              </div>
              <ul className="divide-y overflow-y-auto px-4 text-sm">
                {subs.data?.subscribers.map((s) => (
                  <li key={s.subscriber_id} className="flex justify-between py-1.5">
                    <span>{s.name} <span className="text-muted-foreground">{s.subscriber_id}</span></span>
                    <span className="text-muted-foreground">{s.line_state === "up" ? "Up" : s.line_state}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
