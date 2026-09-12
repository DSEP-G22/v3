"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { StatusDot, type Tone } from "@/components/status-dot";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { useApi, useEvents } from "@/lib/api";

type Overview = {
  first_name: string;
  service: { state: string; headline: string; detail?: string; expected?: string };
  billing: { state: string; headline: string; due_display?: string };
  plan: {
    found: boolean;
    name?: string;
    speed_display?: string;
    allowance_display?: string;
    used_fraction?: number | null;
    unlimited?: boolean;
    days_left?: number;
  };
};

const SERVICE_TONE: Record<string, Tone> = {
  up: "ok", busy: "warn", shaped: "warn", setting_up: "info", outage: "bad", down: "bad", suspended: "bad",
};
const SERVICE_WORD: Record<string, string> = {
  up: "Working", busy: "Busy", shaped: "Slower", setting_up: "Setting up", outage: "Fault in your area",
  down: "Not connecting", suspended: "Paused", unknown: "Unknown",
};

export default function Home() {
  const router = useRouter();
  const { data, error, loading, reload } = useApi<Overview>("/app/overview");
  useEvents((kind) => kind === "account" && void reload());

  useEffect(() => {
    if (error?.status === 409) router.replace("/onboarding");
  }, [error, router]);

  if (loading || error?.status === 409) {
    return (
      <div className="grid gap-4 md:grid-cols-2">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-40" />
        ))}
      </div>
    );
  }
  if (error || !data) return <p className="text-muted-foreground">{error?.message}</p>;

  const { service, billing, plan } = data;
  const settingUp = service.state === "setting_up";

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Hello, {data.first_name}</h1>
      <div className="grid gap-4 md:grid-cols-2">
        <Card className="md:col-span-2">
          <CardHeader>
            <CardDescription>
              <StatusDot tone={SERVICE_TONE[service.state] ?? "idle"} label={SERVICE_WORD[service.state] ?? "Unknown"} />
            </CardDescription>
            <CardTitle className="text-xl">{service.headline}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {service.detail && <p className="max-w-prose text-muted-foreground">{service.detail}</p>}
            {service.expected && <p className="text-sm">Expected back {service.expected}</p>}
            {service.state === "suspended" && (
              <Link href="/app/billing" className={buttonVariants()}>
                Pay and restore service
              </Link>
            )}
            {(service.state === "down" || service.state === "busy") && (
              <Link href="/app/support" className={buttonVariants({ variant: "outline" })}>
                Tell us what you see
              </Link>
            )}
            {settingUp && <Progress value={60} aria-label="Setting up your line" />}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardDescription>Your bill</CardDescription>
            <CardTitle className="text-lg">{billing.headline}</CardTitle>
            <CardAction>
              <Link href="/app/billing" className={buttonVariants({ variant: billing.state === "clear" ? "ghost" : "default", size: "sm" })}>
                {billing.state === "clear" ? "View bills" : "Pay"}
              </Link>
            </CardAction>
          </CardHeader>
          {billing.due_display && billing.state !== "clear" && (
            <CardContent className="text-sm text-muted-foreground">Due {billing.due_display}</CardContent>
          )}
        </Card>

        <Card>
          <CardHeader>
            <CardDescription>This month</CardDescription>
            <CardTitle className="text-lg">{plan.name ?? "Your plan"}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {plan.unlimited ? (
              <p className="text-sm text-muted-foreground">Unlimited data at up to {plan.speed_display}.</p>
            ) : (
              <>
                <Progress value={Math.round((plan.used_fraction ?? 0) * 100)} aria-label="Data used" />
                <p className="text-sm text-muted-foreground">{plan.allowance_display}</p>
              </>
            )}
            {plan.days_left !== undefined && (
              <p className="text-sm text-muted-foreground">Resets in {plan.days_left} days</p>
            )}
          </CardContent>
        </Card>

        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle className="text-lg">Need a hand?</CardTitle>
            <CardDescription>Write, send a photo of your router, or leave a voice note. English, Sinhala or Tamil.</CardDescription>
            <CardAction>
              <Link href="/app/support" className={buttonVariants({ variant: "outline" })}>
                Ask us
              </Link>
            </CardAction>
          </CardHeader>
        </Card>
      </div>
    </div>
  );
}
