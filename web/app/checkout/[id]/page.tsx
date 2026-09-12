"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Brand } from "@/components/brand";
import { RoleGate } from "@/components/role-gate";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { FieldLabel } from "@/components/ui/field";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Skeleton } from "@/components/ui/skeleton";
import { api, post, useApi } from "@/lib/api";

type Intent = {
  id: string;
  purpose: "subscription" | "invoice" | "plan_change";
  description: string;
  amount_display: string;
  status: "requires_payment" | "processing" | "succeeded" | "cancelled";
};

// Stub methods only. This page never shows or collects card numbers.
const METHODS = [
  { value: "card_4242", label: "Card ending 4242", hint: "Your saved card" },
  { value: "lankaqr", label: "LankaQR", hint: "Pay from your banking app" },
];

export default function CheckoutPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data, error, loading } = useApi<Intent>(`/app/intents/${id}`);
  const [method, setMethod] = useState("card_4242");
  const [status, setStatus] = useState<Intent["status"] | null>(null);

  const current = status ?? data?.status;

  useEffect(() => {
    if (current !== "processing") return;
    const timer = setInterval(async () => {
      const i = await api<Intent>(`/app/intents/${id}`).catch(() => null);
      if (i && i.status !== "processing") setStatus(i.status);
    }, 700);
    return () => clearInterval(timer);
  }, [current, id]);

  useEffect(() => {
    if (current !== "succeeded" || !data) return;
    const to = data.purpose === "invoice" ? "/app/billing" : "/app";
    const t = setTimeout(() => router.replace(to), 1200);
    return () => clearTimeout(t);
  }, [current, data, router]);

  async function pay() {
    setStatus("processing");
    const i = await post<Intent>(`/app/intents/${id}/pay`, { method }).catch(() => null);
    if (i) setStatus(i.status);
    else setStatus("requires_payment");
  }

  return (
    <RoleGate roles={["customer"]}>
      <main className="flex min-h-svh flex-col items-center justify-center gap-8 bg-muted/40 px-4 py-10">
        <Brand href="/app" />
        {loading ? (
          <Skeleton className="h-72 w-full max-w-sm" />
        ) : error || !data ? (
          <p className="text-muted-foreground">{error?.message}</p>
        ) : (
          <Card className="w-full max-w-sm">
            <CardHeader>
              <CardDescription>{data.description}</CardDescription>
              <CardTitle className="text-2xl">{data.amount_display}</CardTitle>
            </CardHeader>
            <CardContent>
              {current === "succeeded" ? (
                <p role="status" className="font-medium">
                  Payment received. Thank you.
                </p>
              ) : (
                <RadioGroup value={method} onValueChange={(v) => setMethod(String(v))} disabled={current === "processing"}>
                  {METHODS.map((m) => (
                    <FieldLabel key={m.value} htmlFor={m.value} className="w-full rounded-lg border p-3">
                      <RadioGroupItem id={m.value} value={m.value} />
                      <span>
                        <span className="block font-medium">{m.label}</span>
                        <span className="block text-sm font-normal text-muted-foreground">{m.hint}</span>
                      </span>
                    </FieldLabel>
                  ))}
                </RadioGroup>
              )}
            </CardContent>
            {current !== "succeeded" && (
              <CardFooter>
                <Button className="w-full" size="lg" onClick={pay} disabled={current === "processing"}>
                  {current === "processing" ? "Processing payment" : `Pay ${data.amount_display}`}
                </Button>
              </CardFooter>
            )}
          </Card>
        )}
      </main>
    </RoleGate>
  );
}
