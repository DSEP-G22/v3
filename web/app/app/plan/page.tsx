"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { post, useApi } from "@/lib/api";
import type { Plan } from "@/lib/server";

type PlanScreen = {
  current: { found: boolean; code?: string; name?: string; speed_display?: string; price_display?: string; renews_display?: string };
  in_contract: boolean;
  plans: Plan[];
};

export default function PlanPage() {
  const router = useRouter();
  const { data, loading, error } = useApi<PlanScreen>("/app/plan");
  const [busy, setBusy] = useState<string | null>(null);

  async function change(code: string) {
    setBusy(code);
    try {
      const o = await post<{ intent_id: string }>("/app/orders", { kind: "plan_change", plan_code: code });
      router.push(`/checkout/${o.intent_id}`);
    } catch (e) {
      toast.error((e as Error).message);
      setBusy(null);
    }
  }

  if (loading) return <Skeleton className="h-80" />;
  if (error || !data) return <p className="text-muted-foreground">{error?.message}</p>;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Your plan</h1>
      <Card>
        <CardHeader>
          <CardDescription>Current plan, renews {data.current.renews_display}</CardDescription>
          <CardTitle className="text-xl">{data.current.name}</CardTitle>
        </CardHeader>
        <CardContent className="text-muted-foreground">
          Up to {data.current.speed_display}, {data.current.price_display} a month.
          {data.in_contract && " You are in a minimum term, so an early change may carry a fee."}
        </CardContent>
      </Card>

      <h2 className="font-medium">Other plans</h2>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {data.plans.filter((p) => p.code !== data.current.code).map((p) => (
          <Card key={p.code}>
            <CardHeader>
              <CardDescription>{p.family}</CardDescription>
              <CardTitle>{p.name}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm text-muted-foreground">
              <p className="text-lg font-semibold text-foreground">{p.price_display}</p>
              <p>Up to {p.speed_display}</p>
              <Badge variant="secondary">{p.technology_display}</Badge>
            </CardContent>
            <CardFooter>
              <Button variant="outline" className="w-full" onClick={() => change(p.code)} disabled={busy !== null}>
                {busy === p.code ? "One moment" : "Switch to this plan"}
              </Button>
            </CardFooter>
          </Card>
        ))}
      </div>
    </div>
  );
}
