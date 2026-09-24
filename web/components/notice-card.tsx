"use client";

import { CalendarClockIcon, CreditCardIcon, GaugeIcon, TrafficConeIcon, WifiIcon, type LucideIcon } from "lucide-react";
import Link from "next/link";

import { BentoIcon } from "@/components/bento-icon";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type Notice = {
  kind: "outage" | "payment" | "maintenance" | "congestion" | "allowance";
  title: string;
  detail: string;
  eta?: string | null;
  since?: string | null;
  credit?: boolean;
  amount?: string | null;
  due?: string | null;
  window?: string | null;
  in_progress?: boolean;
  peak?: string;
  used?: string | null;
  allowance?: string | null;
  renews?: string | null;
  shaped_speed?: string | null;
  blocking?: boolean;
  action?: { label: string; href: string };
};

const LOOK: Record<Notice["kind"], { icon: LucideIcon; tint: string; ring: string }> = {
  outage: { icon: TrafficConeIcon, tint: "from-destructive/15 to-transparent", ring: "text-destructive bg-destructive/10" },
  payment: { icon: CreditCardIcon, tint: "from-highlight/30 to-transparent", ring: "text-highlight-foreground bg-highlight/30" },
  maintenance: { icon: CalendarClockIcon, tint: "from-info/15 to-transparent", ring: "text-info bg-info/10" },
  congestion: { icon: WifiIcon, tint: "from-warning/20 to-transparent", ring: "text-warning bg-warning/15" },
  allowance: { icon: GaugeIcon, tint: "from-primary/15 to-transparent", ring: "text-primary bg-primary/10" },
};

/** The repair template: a crew at work, with the estimate if there is one. */
function RepairBar({ eta }: { eta?: string | null }) {
  return (
    <div className="space-y-1.5">
      <div className="h-2 overflow-hidden rounded-full bg-destructive/10">
        <div className="h-full w-2/3 animate-pulse rounded-full bg-[repeating-linear-gradient(45deg,var(--destructive),var(--destructive)_8px,transparent_8px,transparent_14px)] opacity-70" />
      </div>
      <p className="text-xs text-muted-foreground">{eta && eta !== "not yet estimated" ? `Expected back ${eta}` : "We will post an estimate shortly"}</p>
    </div>
  );
}

/** Busy hours template: a day as 24 bars, the evening peak lit. Illustrates the window, not measurements. */
function PeakHours() {
  return (
    <div className="space-y-1.5">
      <div className="flex h-10 items-end gap-0.5" aria-hidden>
        {Array.from({ length: 24 }, (_, h) => {
          const peak = h >= 19 && h <= 23;
          const height = peak ? 70 + (h === 21 ? 30 : h === 20 || h === 22 ? 18 : 0) : 20 + Math.round(18 * Math.sin((h / 24) * Math.PI));
          return <span key={h} className={cn("flex-1 rounded-sm", peak ? "bg-warning" : "bg-muted")} style={{ height: `${height}%` }} />;
        })}
      </div>
      <div className="flex justify-between text-[10px] text-muted-foreground"><span>Midnight</span><span>Noon</span><span>Evening</span></div>
    </div>
  );
}

function Ring({ used }: { used?: string | null }) {
  const pct = Math.min(100, Number.parseFloat(used ?? "") || 100);
  return (
    <div className="relative size-16 shrink-0">
      <svg viewBox="0 0 36 36" className="size-16 -rotate-90" aria-hidden>
        <circle cx="18" cy="18" r="15.5" fill="none" strokeWidth="4" className="stroke-muted" />
        <circle cx="18" cy="18" r="15.5" fill="none" strokeWidth="4" strokeLinecap="round" className="stroke-primary"
                strokeDasharray={`${(pct / 100) * 97.4} 97.4`} />
      </svg>
      <span className="absolute inset-0 grid place-items-center text-xs font-semibold">{used ?? ""}</span>
    </div>
  );
}

/** One template per kind of issue on our side. Every string arrives ready to read. */
export function NoticeCard({ n, className }: { n: Notice; className?: string }) {
  const look = LOOK[n.kind];
  const Icon = look.icon;
  return (
    <article className={cn("group relative isolate h-full overflow-hidden rounded-2xl border bg-card p-4 shadow-sm", className)}>
      <div aria-hidden className={cn("absolute inset-0 -z-10 bg-linear-to-br", look.tint)} />
      <BentoIcon icon={Icon} className="-z-10" tone={look.ring.split(" ")[0]} />
      <div className="relative space-y-3">
        <div className="min-w-0">
          <h3 className="font-semibold leading-tight">{n.title}</h3>
          <p className="mt-0.5 text-sm text-muted-foreground">{n.detail}</p>
        </div>

        {n.kind === "outage" && (
          <>
            <RepairBar eta={n.eta} />
            <p className="text-xs text-muted-foreground">
              {n.since ? `Reported ${n.since}. ` : ""}{n.credit ? "A service credit applies for any full day without service." : ""}
            </p>
          </>
        )}
        {n.kind === "payment" && (
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-2xl font-semibold tracking-tight">{n.amount}</p>
              {n.due && <p className="text-xs text-muted-foreground">Due since {n.due}</p>}
            </div>
            {n.action && <Link href={n.action.href} className={buttonVariants({ size: "sm", className: "bg-highlight text-highlight-foreground hover:bg-highlight/90" })}>{n.action.label}</Link>}
          </div>
        )}
        {n.kind === "maintenance" && (
          <div className="rounded-xl border bg-background/70 p-3 text-sm">
            <p className="text-xs text-muted-foreground">{n.in_progress ? "Running now" : "Window"}</p>
            <p className="font-medium">{n.window}</p>
            {n.in_progress && <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-info/15"><div className="h-full w-1/2 animate-pulse rounded-full bg-info" /></div>}
          </div>
        )}
        {n.kind === "congestion" && <PeakHours />}
        {n.kind === "allowance" && (
          <div className="flex items-center gap-4">
            <Ring used={n.used} />
            <div className="text-sm">
              <p className="font-medium">{n.allowance}</p>
              <p className="text-xs text-muted-foreground">
                {n.shaped_speed ? `Reduced to ${n.shaped_speed}` : "Reduced speed"}{n.renews ? ` until ${n.renews}` : ""}
              </p>
              {n.action && <Link href={n.action.href} className="mt-1 inline-block text-xs font-medium text-primary underline underline-offset-4">{n.action.label}</Link>}
            </div>
          </div>
        )}
      </div>
    </article>
  );
}
