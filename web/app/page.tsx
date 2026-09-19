import { ArrowRightIcon, CheckCheckIcon, MessageSquareTextIcon } from "lucide-react";
import Link from "next/link";

import { BinaryField } from "@/components/fx/binary-field";
import { LogoIcon, LogoMark } from "@/components/logo";
import { PlanCard } from "@/components/plan-card";
import { SessionNav } from "@/components/session-nav";
import { getPlans } from "@/lib/server";
import { cn } from "@/lib/utils";

// Rendered per request (the fetch keeps a one minute cache): prerendering at image build time, when
// no gateway exists, cached an empty catalogue that every deploy then served.
export const dynamic = "force-dynamic";

const NAV: [string, string][] = [["Plans", "/plans"], ["How it works", "/docs"]];
const DOES = [
  { k: "Support", title: "Tickets in your language.", rest: "Type, send a photo of the router or leave a voice note, in Sinhala, Tamil or English." },
  { k: "Service", title: "Your line, in the open.", rest: "Repairs, maintenance and busy hours in your area appear on your account as they happen." },
  { k: "Billing", title: "Pay and reconnect.", rest: "Every charge and payment in one place. Settle from your phone and the line is back in minutes." },
];
const STEPS = [
  { title: "You write", body: "Text, a photo or a voice note, in your own words." },
  { title: "We check", body: "Your line, your account and our network, in seconds." },
  { title: "You hear back", body: "Your side first, then anything on ours, in the language you wrote." },
];

const HORIZON = "radial-gradient(70% 100% at 50% 100%, oklch(0.95 0.04 305) 0%, oklch(0.78 0.13 302 / 0.9) 16%, oklch(0.55 0.19 296 / 0.55) 40%, oklch(0.3 0.12 295 / 0.2) 62%, transparent 80%)";
const BTN = "inline-flex h-9 items-center gap-2 rounded-md px-4 font-mono text-[11px] tracking-[0.12em] uppercase transition-colors";
const LIGHT = cn(BTN, "bg-white text-black shadow-[0_0_0_1px_rgba(255,255,255,0.4),0_8px_24px_-8px_rgba(255,255,255,0.5)] hover:bg-white/90");
const DARK = cn(BTN, "border border-white/15 bg-black/70 text-white backdrop-blur hover:bg-black/90");

function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-md border border-white/10 bg-white/5 px-2.5 py-1 font-mono text-[11px] tracking-[0.12em] text-white/70 uppercase backdrop-blur">
      <span className="size-1.5 bg-white/70" />{children}
    </span>
  );
}

/** A raised key, like a keyboard cap, holding one glyph. */
function Keycap({ children, big }: { children: React.ReactNode; big?: boolean }) {
  return (
    <div className={cn("grid shrink-0 place-items-center rounded-2xl border border-white/15 bg-linear-to-b from-[oklch(0.38_0.02_295)] to-[oklch(0.16_0.02_295)] p-1.5 shadow-[0_18px_40px_-12px_rgba(0,0,0,0.9),inset_0_1px_0_rgba(255,255,255,0.25)]",
      big ? "size-20" : "size-14")}>
      <div className="grid size-full place-items-center rounded-xl bg-black/85 text-white shadow-[inset_0_2px_6px_rgba(0,0,0,0.8)]">{children}</div>
    </div>
  );
}

export default async function Landing() {
  const plans = await getPlans();
  return (
    <div className="dark relative isolate min-h-svh bg-[linear-gradient(to_bottom,oklch(0.14_0.05_292),#050308_55%)] text-foreground">
      <BinaryField />

      <header className="sticky top-0 z-30 border-b border-white/5 bg-black/20 backdrop-blur-md">
        <div className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between px-6">
          <Link href="/" aria-label="Lanka Link home" className="text-white"><LogoMark mono className="h-7" /></Link>
          <nav aria-label="Site" className="hidden items-center gap-8 font-mono text-[11px] tracking-[0.12em] uppercase md:flex">
            {NAV.map(([label, href]) => <Link key={href} href={href} className="text-white/60 transition-colors hover:text-white">{label}</Link>)}
          </nav>
          <SessionNav light={LIGHT} dark={DARK} />
        </div>
      </header>

      <main>
        {/* Hero: the headline over the flipping field, a horizon of light rising beneath it. */}
        <section className="relative isolate flex min-h-[86svh] flex-col items-center justify-center overflow-hidden px-6 pt-10 pb-44 text-center">
          <div aria-hidden className="absolute inset-x-0 bottom-0 -z-10 h-[70%]" style={{ background: HORIZON }} />
          <Tag>New: support in Sinhala, Tamil and English</Tag>
          <h1 className="mt-8 max-w-4xl bg-linear-to-b from-white to-[oklch(0.84_0.07_305)] bg-clip-text text-5xl leading-[1.04] font-medium tracking-tight text-balance text-transparent md:text-7xl">
            Internet That <em className="font-serif font-normal">Knows</em> Your Line and <em className="font-serif font-normal">Answers</em> in Your Language
          </h1>
          <div className="mt-10 flex flex-wrap justify-center gap-3">
            <Link href="/sign-up" className={LIGHT}>Start with a plan</Link>
            <Link href="/docs" className={DARK}>See how it works</Link>
          </div>
        </section>

        {/* The band under the horizon: one statement, the mark on a key, a line of light down. */}
        <section className="relative isolate px-6 pt-20 text-center">
          <div aria-hidden className="absolute inset-0 -z-10 bg-[linear-gradient(to_bottom,oklch(0.4_0.17_296),oklch(0.2_0.08_295)_40%,transparent_85%)]" />
          <div aria-hidden className="absolute inset-x-0 top-0 h-px bg-linear-to-r from-transparent via-white/80 to-transparent" />
          <p className="mx-auto max-w-3xl text-3xl leading-tight font-light tracking-tight text-balance text-white md:text-5xl">
            Fibre at home. Data on the go. <span className="text-white/50">Support that already knows what is wrong.</span>
          </p>
          <div className="mt-14 flex justify-center"><Keycap big><LogoIcon mono className="size-9" /></Keycap></div>
          <div aria-hidden className="mx-auto h-36 w-px bg-linear-to-b from-white/50 via-[oklch(0.8_0.1_305)]/60 to-[oklch(0.8_0.1_305)]" />
          <div aria-hidden className="mx-auto h-px w-full max-w-5xl bg-linear-to-r from-transparent via-[oklch(0.8_0.1_305)] to-transparent" />
        </section>

        {/* What we do: a ruled grid, text on one side, the flow on a dotted plate on the other. */}
        <section aria-labelledby="what" className="mx-auto w-full max-w-6xl border-x border-white/10">
          <div className="grid md:grid-cols-2">
            <div className="border-b border-white/10 p-8 md:border-r md:p-12">
              <Tag>What we do</Tag>
              <h2 id="what" className="mt-8 text-3xl leading-tight font-light tracking-tight text-white md:text-4xl">
                Support at full speed. <span className="text-white/45">Every request is read against your own line, your bill and our network, then answered in the language you wrote.</span>
              </h2>
              <Link href="/docs" className={cn(DARK, "mt-10")}>Read how <ArrowRightIcon className="size-3.5" /></Link>
            </div>
            <div className="relative flex min-h-80 items-center justify-center gap-2 border-b border-white/10 p-6 sm:gap-3 sm:p-8 [background-image:radial-gradient(rgba(255,255,255,0.14)_1px,transparent_1px)] [background-size:16px_16px]">
              <Keycap><MessageSquareTextIcon className="size-6" /></Keycap>
              <span aria-hidden className="h-px w-6 border-t border-dashed border-white/30 sm:w-16" />
              <Keycap big><LogoIcon mono className="size-9" /></Keycap>
              <span aria-hidden className="h-px w-6 border-t border-dashed border-white/30 sm:w-16" />
              <Keycap><CheckCheckIcon className="size-6" /></Keycap>
            </div>
          </div>
          <div className="grid md:grid-cols-3">
            {DOES.map((d) => (
              <article key={d.k} className="border-b border-white/10 p-8 md:border-r md:last:border-r-0">
                <p className="font-mono text-[11px] tracking-[0.12em] text-white/50 uppercase">{d.k}</p>
                <h3 className="mt-4 text-lg font-medium text-white">{d.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-white/55">{d.rest}</p>
              </article>
            ))}
          </div>
        </section>

        <section aria-labelledby="how" className="mx-auto w-full max-w-6xl border-x border-white/10 px-8 py-20 md:px-12">
          <Tag>How it works</Tag>
          <h2 id="how" className="mt-8 max-w-2xl text-3xl leading-tight font-light tracking-tight text-white md:text-4xl">
            A reply that starts <em className="font-serif font-normal">on your side</em> of the line.
          </h2>
          <ol className="mt-12 grid gap-8 md:grid-cols-3">
            {STEPS.map((s, i) => (
              <li key={s.title} className="border-t border-white/15 pt-5">
                <p className="font-mono text-xs text-white/40">0{i + 1}</p>
                <h3 className="mt-3 font-medium text-white">{s.title}</h3>
                <p className="mt-1 text-sm text-white/55">{s.body}</p>
              </li>
            ))}
          </ol>
        </section>

        <section aria-labelledby="plans" className="mx-auto w-full max-w-6xl border-x border-t border-white/10 px-8 py-20 md:px-12">
          <div className="mb-10 flex flex-wrap items-end justify-between gap-4">
            <div>
              <Tag>Plans</Tag>
              <h2 id="plans" className="mt-8 text-3xl font-light tracking-tight text-white md:text-4xl">Pick a plan, <em className="font-serif font-normal">connect in days.</em></h2>
            </div>
            <Link href="/plans" className={DARK}>Every plan <ArrowRightIcon className="size-3.5" /></Link>
          </div>
          {plans.length ? (
            <div className="grid gap-4 md:grid-cols-3">{plans.slice(0, 3).map((p) => <PlanCard key={p.code} plan={p} />)}</div>
          ) : <p className="text-white/55">Plans are loading. Refresh in a moment.</p>}
        </section>

        <section className="relative isolate mx-auto w-full max-w-6xl overflow-hidden border border-white/10 px-8 py-24 text-center md:px-12">
          <div aria-hidden className="absolute inset-x-0 bottom-0 -z-10 h-full opacity-70" style={{ background: HORIZON }} />
          <h2 className="text-4xl font-light tracking-tight text-white md:text-5xl">Ready <em className="font-serif font-normal">when you are.</em></h2>
          <p className="mx-auto mt-4 max-w-md text-white/60">Choose a plan, tell us where you are, and your line is set up for you.</p>
          <div className="mt-10 flex justify-center gap-3">
            <Link href="/sign-up" className={LIGHT}>Get started</Link>
            <Link href="/plans" className={DARK}>Compare plans</Link>
          </div>
        </section>
      </main>

      <footer className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-6 px-6 py-12">
        <LogoMark mono className="h-7 text-white" />
        <nav aria-label="Footer" className="flex gap-6 font-mono text-[11px] tracking-[0.12em] uppercase">
          {NAV.map(([label, href]) => <Link key={href} href={href} className="text-white/50 hover:text-white">{label}</Link>)}
        </nav>
      </footer>
    </div>
  );
}
