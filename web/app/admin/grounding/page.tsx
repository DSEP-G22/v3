"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { api, post, useApi } from "@/lib/api";
import { department } from "@/lib/format";

type Plan = { by_department: Record<string, { tools: string[]; required_sections?: string[] }>; [k: string]: unknown };
type DryRun = { tools: string[]; required_sections: string[]; facts: { tool: string; found: boolean; signals: string[] }[] };

export default function GroundingPlan() {
  const { data, loading } = useApi<{ plan: Plan; generation: number; tools: string[] }>("/admin/grounding-plan");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [dept, setDept] = useState("technical_support");
  const [subscriber, setSubscriber] = useState("SUB-100002");
  const [result, setResult] = useState<DryRun | null>(null);

  useEffect(() => {
    if (data) setPlan(structuredClone(data.plan));
  }, [data]);

  if (loading || !plan || !data) return <Skeleton className="h-96" />;
  const departments = Object.keys(plan.by_department);
  const chosen = plan.by_department[dept]?.tools ?? [];

  function toggle(tool: string, on: boolean) {
    setPlan((p) => {
      if (!p) return p;
      const next = structuredClone(p);
      const tools = next.by_department[dept].tools;
      next.by_department[dept].tools = on ? [...tools, tool] : tools.filter((t) => t !== tool);
      return next;
    });
  }

  async function save() {
    try {
      await api("/admin/grounding-plan", { method: "PUT", body: JSON.stringify({ plan }) });
      toast.success("Saved. Grounding uses it on the next case.");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Grounding plan</h1>
          <p className="text-sm text-muted-foreground">What the reply writer is allowed to know, per department.</p>
        </div>
        <Button onClick={save}>Save plan</Button>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <Select value={dept} onValueChange={(v) => setDept(String(v))}
                    items={departments.map((d) => ({ value: d, label: department(d) }))}>
              <SelectTrigger className="w-64"><SelectValue /></SelectTrigger>
              <SelectContent>{departments.map((d) => <SelectItem key={d} value={d}>{department(d)}</SelectItem>)}</SelectContent>
            </Select>
            <CardDescription>
              Must have: {(plan.by_department[dept]?.required_sections ?? []).join(", ") || "nothing"}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="divide-y">
              {data.tools.map((t) => (
                <li key={t} className="flex items-center justify-between py-2 text-sm">
                  <label htmlFor={t}>{t.replace(/^get_/, "").replace(/_/g, " ")}</label>
                  <Switch id={t} checked={chosen.includes(t)} onCheckedChange={(v) => toggle(t, !!v)} />
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Dry run</CardTitle>
            <CardDescription>Run this department&apos;s saved plan against a customer, without a case.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="sub">Customer</FieldLabel>
                <Input id="sub" value={subscriber} onChange={(e) => setSubscriber(e.target.value)} />
              </Field>
            </FieldGroup>
            <Button variant="outline" onClick={async () => {
              try {
                setResult(await post<DryRun>("/admin/grounding-plan/dry-run", { department: dept, subscriber_ref: subscriber }));
              } catch (e) {
                toast.error((e as Error).message);
              }
            }}>
              Run
            </Button>
            {result && (
              <ul className="space-y-2 text-sm">
                {result.facts.map((f) => (
                  <li key={f.tool}>
                    <span className={f.found ? "" : "text-muted-foreground"}>{f.tool.replace(/^get_/, "").replace(/_/g, " ")}</span>
                    {!f.found && <span className="text-muted-foreground"> (not found)</span>}
                    <span className="ml-2 inline-flex flex-wrap gap-1">
                      {f.signals.map((s) => <Badge key={s} variant="secondary">{s.replace(/_/g, " ")}</Badge>)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
