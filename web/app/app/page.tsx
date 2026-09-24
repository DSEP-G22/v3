"use client";

import { ArrowRightIcon, CreditCardIcon, GaugeIcon, InfinityIcon, SparklesIcon, TicketIcon, WifiIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { BentoIcon } from "@/components/bento-icon";
import { Carousel } from "@/components/fx/carousel";
import { FocusLayer, originOf, type Origin } from "@/components/fx/focus-layer";
import { TiltCard } from "@/components/fx/tilt-card";
import { NoticeCard, type Notice } from "@/components/notice-card";
import { PayDialog } from "@/components/pay-dialog";
import { type TicketRow } from "@/components/ticket-list";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { post, useApi, useEvents } from "@/lib/api";
import { cn } from "@/lib/utils";

type Overview = {
  first_name: string;
  service: { state: string; headline: string; detail?: string; expected?: string };
  billing: { state: string; headline: string; outstanding_display?: string; due_display?: string };
  plan: { found: boolean; name?: string; speed_display?: string; allowance_display?: string; used_fraction?: number | null;
    unlimited?: boolean; days_left?: number };
};

const ORB: Record<string, { core: string; ring: string; word: string }> = {
  up: { core: "bg-success", ring: "bg-success/30", word: "Working" },
  busy: { core: "bg-warning", ring: "bg-warning/30", word: "Busy" },
  shaped: { core: "bg-warning", ring: "bg-warning/30", word: "Slower" },
  setting_up: { core: "bg-info", ring: "bg-info/30", word: "Setting up" },
  outage: { core: "bg-destructive", ring: "bg-destructive/30", word: "Fault in your area" },
  down: { core: "bg-destructive", ring: "bg-destructive/30", word: "Not connecting" },
  suspended: { core: "bg-destructive", ring: "bg-destructive/30", word: "Paused" },
  unknown: { core: "bg-muted-foreground", ring: "bg-muted", word: "Unknown" },
};

/** The colour token each state's sphere is lit in. */
const SPHERE: Record<string, string> = {
  up: "--success", busy: "--warning", shaped: "--warning", setting_up: "--info",
  outage: "--destructive", down: "--destructive", suspended: "--destructive",
};

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

const TONE_TEXT: Record<string, string> = {
  up: "text-success", busy: "text-warning", shaped: "text-warning", setting_up: "text-info",
  outage: "text-destructive", down: "text-destructive", suspended: "text-destructive",
};

/**
 * The service card is washed in the state's colour over a neutral ground, so it reads plainly
 * green or red (amber, blue) with no violet in it: the card itself is the status.
 */
function tint(state: string): React.CSSProperties {
  const c = `var(${SPHERE[state] ?? "--muted-foreground"})`;
  return {
    background: `radial-gradient(120% 110% at 0% 0%, color-mix(in oklch, ${c} 34%, transparent), transparent 62%),
      linear-gradient(160deg, color-mix(in oklch, ${c} 22%, oklch(0.2 0 0)), color-mix(in oklch, ${c} 9%, oklch(0.15 0 0)) 55%, color-mix(in oklch, ${c} 5%, oklch(0.1 0 0)))`,
    borderColor: `color-mix(in oklch, ${c} 45%, transparent)`,
    "--tilt-glow": c,
  } as React.CSSProperties;
}

function UsageRing({ fraction, unlimited }: { fraction: number; unlimited?: boolean }) {
  const pct = unlimited ? 100 : Math.min(100, Math.round(fraction * 100));
  const over = !unlimited && fraction >= 1;
  return (
    <div className="relative size-28 shrink-0">
      <svg viewBox="0 0 36 36" className="size-28 -rotate-90" aria-hidden>
        <circle cx="18" cy="18" r="15.5" fill="none" strokeWidth="3.2" className="stroke-muted" />
        <circle cx="18" cy="18" r="15.5" fill="none" strokeWidth="3.2" strokeLinecap="round"
                className={cn("transition-[stroke-dasharray] duration-1000 ease-out", over ? "stroke-destructive" : "stroke-primary")}
                strokeDasharray={`${(pct / 100) * 97.4} 97.4`} />
      </svg>
      <span className="absolute inset-0 grid place-items-center text-center">
        {unlimited ? <InfinityIcon aria-label="Unlimited" className="size-9 text-primary" strokeWidth={1.75} />
          : <span className="text-xl font-semibold tabular-nums">{pct}%</span>}
      </span>
    </div>
  );
}

export default function Home() {
  const router = useRouter();
  const { data, error, loading, reload } = useApi<Overview>("/app/overview");
  const tickets = useApi<{ tickets: TicketRow[] }>("/app/tickets");
  const notices = useApi<{ notices: Notice[] }>("/app/notices");
  const [pay, setPay] = useState<Origin | null>(null);
  const [status, setStatus] = useState<Origin | null>(null);
  useEvents((kind) => (kind === "account" || kind === "ticket") && (void reload(), void notices.reload(), void tickets.reload()));

  useEffect(() => {
    if (error?.status === 409) router.replace("/onboarding");
  }, [error, router]);

  if (loading || error?.status === 409) {
    return (
      <div className="grid gap-4 md:grid-cols-3">
        {[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className={cn("h-44 rounded-2xl", i === 0 && "md:col-span-2")} />)}
      </div>
    );
  }
  if (error || !data) return <p className="text-muted-foreground">{error?.message}</p>;

  const { service, billing, plan } = data;
  const owes = billing.state !== "clear" && billing.state !== "unknown";
  const latest = tickets.data?.tickets[0];
  const open = tickets.data?.tickets.filter((t) => t.status === "open").length ?? 0;
  const orb = ORB[service.state] ?? ORB.unknown;

  return (
    <div className="relative isolate space-y-8">

      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm text-muted-foreground">{greeting()},</p>
          <h1 className="text-3xl font-semibold tracking-tight">{data.first_name}</h1>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href="/app/tickets/new" className={buttonVariants({ variant: "outline", className: "rounded-full bg-background/60 backdrop-blur" })}>Open a ticket</Link>
          <Link href="/app/usage" className={buttonVariants({ variant: "outline", className: "rounded-full bg-background/60 backdrop-blur" })}>See usage</Link>
          <Link href="/app/plan" className={buttonVariants({ variant: "outline", className: "rounded-full bg-background/60 backdrop-blur" })}>Change plan</Link>
        </div>
      </header>

      <div className="grid gap-4 md:grid-cols-3">
        <TiltCard className="border transition-[transform,box-shadow,background,border-color] duration-700 md:col-span-2" max={3} style={tint(service.state)}>
          <BentoIcon icon={WifiIcon} className="-z-10" tone={TONE_TEXT[service.state] ?? "text-muted-foreground"} />
          <div className="flex flex-col gap-6 sm:flex-row sm:items-center">
            <div className="min-w-0 space-y-2">
              <p className="text-xs font-medium tracking-wide uppercase" style={{ color: `var(${SPHERE[service.state] ?? "--muted-foreground"})` }}>{orb.word}</p>
              <h2 className="text-2xl font-semibold tracking-tight">{service.headline}</h2>
              {service.detail && <p className="max-w-prose text-muted-foreground">{service.detail}</p>}
              {service.expected && <p className="text-sm">Expected back {service.expected}</p>}
              <div className="flex flex-wrap gap-2 pt-1">
                <Button variant="ghost" size="sm" className="-ml-2" onClick={(e) => setStatus(originOf(e))}>Details</Button>
                {service.state === "suspended" && <Button onClick={(e) => setPay(originOf(e))}>Pay and restore service</Button>}
                {(service.state === "down" || service.state === "busy" || service.state === "outage") && (
                  <Link href="/app/tickets/new" className={buttonVariants({ variant: "outline" })}>Tell us what you see</Link>
                )}
              </div>
            </div>
          </div>
        </TiltCard>

        <TiltCard>
          <BentoIcon icon={CreditCardIcon} className="-z-10" tone="text-highlight" />
          <p className="text-sm text-muted-foreground">Your bill</p>
          <p className="mt-1 text-2xl font-semibold tracking-tight">{owes ? billing.outstanding_display : "All paid"}</p>
          <p className="text-sm text-muted-foreground">{owes ? (billing.due_display ? `Due ${billing.due_display}` : billing.headline) : "Nothing to pay right now."}</p>
          <div className="mt-5 flex gap-2">
            {owes && <Button onClick={(e) => setPay(originOf(e))} className="bg-highlight text-highlight-foreground hover:bg-highlight/90">Pay balance</Button>}
            <Link href="/app/billing" className={buttonVariants({ variant: "ghost" })}>Bills</Link>
          </div>
        </TiltCard>

        <TiltCard>
          <BentoIcon icon={GaugeIcon} className="-z-10" />
          <div className="flex items-center gap-4">
            <UsageRing fraction={plan.used_fraction ?? 0} unlimited={plan.unlimited} />
            <div className="min-w-0">
              <p className="text-sm text-muted-foreground">This month</p>
              <p className="font-semibold">{plan.name ?? "Your plan"}</p>
              <p className="text-sm text-muted-foreground">{plan.unlimited ? `Unlimited at ${plan.speed_display}` : plan.allowance_display}</p>
              {plan.days_left !== undefined && <p className="text-xs text-muted-foreground">Resets in {plan.days_left} days</p>}
            </div>
          </div>
        </TiltCard>

        <TiltCard className="md:col-span-2">
          <BentoIcon icon={TicketIcon} className="-z-10" />
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-sm text-muted-foreground">{open ? `${open} ticket${open > 1 ? "s" : ""} waiting on us` : "Support"}</p>
              {latest ? (
                <Link href={`/app/tickets/${latest.id}`} className="group/t mt-1 block">
                  <p className="font-semibold group-hover/t:text-primary">{latest.subject}</p>
                  {latest.last_body && <p className="line-clamp-2 text-sm text-muted-foreground">{latest.last_author === "customer" ? "You: " : "Lanka Link: "}{latest.last_body}</p>}
                </Link>
              ) : (
                <p className="mt-1 font-semibold">Write, send a photo, or leave a voice note.</p>
              )}
            </div>
            <div className="flex gap-2">
              <Link href="/app/tickets" className={buttonVariants({ variant: "ghost" })}>All tickets</Link>
              <Link href="/app/tickets/new" className={buttonVariants()}>New ticket <ArrowRightIcon /></Link>
            </div>
          </div>
        </TiltCard>
      </div>

      {!!notices.data?.notices.length && (
        <section aria-labelledby="known" className="space-y-3">
          <h2 id="known" className="flex items-center gap-2 font-medium"><SparklesIcon className="size-4 text-highlight" /> Happening on our side</h2>
          <Carousel label="Known issues on our side">
            {notices.data.notices.map((n, i) => <NoticeCard key={i} n={n} />)}
          </Carousel>
        </section>
      )}

      <FocusLayer open={status !== null} origin={status} onClose={() => setStatus(null)} title={orb.word} subtitle="Your connection right now">
        <div className="space-y-3 text-sm">
          <p>{service.headline}.</p>
          {service.detail && <p className="text-muted-foreground">{service.detail}</p>}
          {service.expected && <p>Expected back {service.expected}.</p>}
          <div className="flex gap-2 pt-1">
            <Link href="/app/usage" className={buttonVariants({ variant: "outline", size: "sm" })}>Line health</Link>
            <Link href="/app/tickets/new" className={buttonVariants({ size: "sm" })}>Open a ticket</Link>
          </div>
        </div>
      </FocusLayer>

      <PayDialog open={pay !== null} origin={pay} onClose={() => setPay(null)} title="Pay your balance"
                 start={() => post<{ intent_id: string; amount_display: string }>("/app/balance/pay")}
                 onPaid={() => { void reload(); void notices.reload(); }} />
    </div>
  );
}
