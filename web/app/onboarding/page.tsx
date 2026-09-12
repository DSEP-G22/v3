"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Brand } from "@/components/brand";
import { RoleGate } from "@/components/role-gate";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { post, useApi } from "@/lib/api";
import type { Plan } from "@/lib/server";

type Area = { district: string; city: string; technologies: string[] };

export default function Onboarding() {
  const router = useRouter();
  const plans = useApi<{ plans: Plan[] }>("/public/plans");
  const coverage = useApi<{ areas: Area[] }>("/public/coverage");
  const [step, setStep] = useState<1 | 2>(1);
  const [planCode, setPlanCode] = useState<string>("");
  const [city, setCity] = useState<string>("");
  const [address, setAddress] = useState("");
  const [busy, setBusy] = useState(false);

  const plan = plans.data?.plans.find((p) => p.code === planCode);
  const areas = useMemo(
    () => (coverage.data?.areas ?? []).filter((a) => !plan || a.technologies.includes(plan.technology)),
    [coverage.data, plan],
  );

  async function order() {
    setBusy(true);
    try {
      const o = await post<{ intent_id: string }>("/app/orders", {
        kind: "new_service", plan_code: planCode, city, address_line: address,
      });
      router.push(`/checkout/${o.intent_id}`);
    } catch (e) {
      toast.error((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <RoleGate roles={["customer"]}>
      <main className="flex min-h-svh flex-col items-center gap-8 bg-muted/40 px-4 py-10">
        <Brand />
        <Card className="w-full max-w-lg">
          <CardHeader>
            <CardDescription>Step {step} of 2</CardDescription>
            <CardTitle className="text-xl">{step === 1 ? "Choose a plan" : "Where should we connect you?"}</CardTitle>
          </CardHeader>
          <CardContent>
            {step === 1 ? (
              plans.loading ? (
                <Skeleton className="h-60" />
              ) : (
                <RadioGroup value={planCode} onValueChange={(v) => setPlanCode(String(v))}>
                  {plans.data?.plans.map((p) => (
                    <FieldLabel key={p.code} htmlFor={p.code} className="w-full rounded-lg border p-3">
                      <RadioGroupItem id={p.code} value={p.code} />
                      <span className="flex flex-1 justify-between gap-4">
                        <span>
                          <span className="block font-medium">{p.name}</span>
                          <span className="block text-sm font-normal text-muted-foreground">
                            Up to {p.speed_display}, {p.data_cap_display === "Unlimited" ? "unlimited data" : `${p.data_cap_display}`}
                          </span>
                        </span>
                        <span className="shrink-0 text-sm">{p.price_display}</span>
                      </span>
                    </FieldLabel>
                  ))}
                </RadioGroup>
              )
            ) : (
              <FieldGroup>
                <Field>
                  <FieldLabel>Town</FieldLabel>
                  <Select
                    value={city}
                    onValueChange={(v) => setCity(String(v ?? ""))}
                    items={areas.map((a) => ({ value: a.city, label: `${a.city}, ${a.district}` }))}
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue placeholder="Select your town" />
                    </SelectTrigger>
                    <SelectContent>
                      {areas.map((a) => (
                        <SelectItem key={a.city} value={a.city}>
                          {a.city}, {a.district}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FieldDescription>Only towns where {plan?.name} is available are listed.</FieldDescription>
                </Field>
                <Field>
                  <FieldLabel htmlFor="address">Street address</FieldLabel>
                  <Input id="address" value={address} maxLength={160} onChange={(e) => setAddress(e.target.value)}
                         placeholder="No. 12, Temple Lane" autoComplete="street-address" />
                </Field>
              </FieldGroup>
            )}
          </CardContent>
          <CardFooter className="justify-between gap-2">
            {step === 2 ? (
              <Button variant="ghost" onClick={() => setStep(1)}>
                Back
              </Button>
            ) : (
              <span />
            )}
            {step === 1 ? (
              <Button disabled={!planCode} onClick={() => setStep(2)}>
                Continue
              </Button>
            ) : (
              <Button disabled={!city || !address.trim() || busy} onClick={order}>
                {busy ? "One moment" : "Continue to payment"}
              </Button>
            )}
          </CardFooter>
        </Card>
      </main>
    </RoleGate>
  );
}
