"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, post, useApi } from "@/lib/api";

type Scenario = { name: string; description: string; needs_subscriber: boolean };
type Fault = { id: string; kind: string; label: string; target_ref: string; source: string; started_display: string;
  eta_display: string | null };

export default function Scenarios() {
  const list = useApi<{ scenarios: Scenario[] }>("/sim/scenarios");
  const faults = useApi<{ faults: Fault[] }>("/sim/faults");
  const people = useApi<{ subscribers: { subscriber_id: string; name: string }[] }>("/sim/subscribers?q=SUB-10000&limit=8");
  const [target, setTarget] = useState("SUB-100002");
  const [busy, setBusy] = useState<string | null>(null);

  async function run(name: string, needs: boolean) {
    setBusy(name);
    try {
      await post(`/sim/scenarios/${name}`, needs ? { subscriber_ref: target } : {});
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
        <h1 className="text-xl font-semibold tracking-tight">Scenarios</h1>
        <div className="flex flex-wrap items-center gap-2">
          <Input value={target} onChange={(e) => setTarget(e.target.value)} className="w-40" aria-label="Target customer" />
          {people.data?.subscribers.map((p) => (
            <Button key={p.subscriber_id} size="xs" variant={target === p.subscriber_id ? "secondary" : "ghost"}
                    onClick={() => setTarget(p.subscriber_id)}>
              {p.name.split(" ")[0]}
            </Button>
          ))}
        </div>
      </div>

      {list.loading ? <Skeleton className="h-60" /> : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {list.data?.scenarios.map((s) => (
            <Card key={s.name} size="sm">
              <CardHeader>
                <CardTitle>{s.name.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())}</CardTitle>
                <CardDescription>{s.description}</CardDescription>
              </CardHeader>
              <CardContent />
              <CardFooter>
                <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => run(s.name, s.needs_subscriber)}>
                  {busy === s.name ? "Injecting" : s.needs_subscriber ? `Inject on ${target}` : "Run"}
                </Button>
              </CardFooter>
            </Card>
          ))}
        </div>
      )}

      <section>
        <h2 className="mb-2 font-medium">Active faults</h2>
        {!faults.data?.faults.length ? <p className="text-muted-foreground">Nothing is injected right now.</p> : (
          <div className="rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Fault</TableHead>
                  <TableHead>Target</TableHead>
                  <TableHead>Started</TableHead>
                  <TableHead>Ends</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {faults.data.faults.map((f) => (
                  <TableRow key={f.id}>
                    <TableCell>{f.label}{f.source === "random" && <span className="text-muted-foreground"> (random)</span>}</TableCell>
                    <TableCell>{f.target_ref}</TableCell>
                    <TableCell className="text-muted-foreground">{f.started_display}</TableCell>
                    <TableCell className="text-muted-foreground">{f.eta_display ?? "When cleared"}</TableCell>
                    <TableCell className="text-right">
                      <Button size="xs" variant="ghost" onClick={async () => {
                        await api(`/sim/faults/${f.id}`, { method: "DELETE" }).catch((e) => toast.error((e as Error).message));
                        void faults.reload();
                      }}>
                        Clear
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </section>
    </div>
  );
}
