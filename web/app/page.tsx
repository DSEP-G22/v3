import { ArrowRightIcon, ArrowUpRightIcon, CheckCheckIcon, MenuIcon, MessageSquareTextIcon } from "lucide-react";
import Image from "next/image";
import Link from "next/link";

import { BinaryField } from "@/components/fx/binary-field";
import { Reveal } from "@/components/fx/reveal";
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
  { k: "Support", art: "/art/voice.webp", title: "Tickets in your language.", rest: "Type, send a photo of the router or leave a voice note, in Sinhala, Tamil or English." },
  { k: "Service", art: "/art/island.webp", title: "Your line, in the open.", rest: "Repairs, maintenance and busy hours in your area appear on your account as they happen." },
  { k: "Billing", art: "/art/core.webp", title: "Pay and reconnect.", rest: "Every charge and payment in one place. Settle from your phone and the line is back in minutes." },
];
const STEPS = [
  { title: "You write", body: "Text, a photo or a voice note, in your own words." },
  { title: "We check", body: "Your line, your account and our network, in seconds." },
  { title: "You hear back", body: "Your side first, then anything on ours, in the language you wrote." },
];

const HORIZON = "radial-gradient(70% 100% at 50% 100%, oklch(0.95 0.04 305) 0%, oklch(0.78 0.13 302 / 0.9) 16%, oklch(0.55 0.19 296 / 0.55) 40%, oklch(0.3 0.12 295 / 0.2) 62%, transparent 80%)";
const BTN = "pixel-label inline-flex h-10 items-center gap-2 rounded-full px-5 text-[17px] transition-[background-color,box-shadow,transform] duration-300 active:scale-[0.98]";
const LIGHT = cn(BTN, "bg-white text-black shadow-[0_0_0_1px_rgba(255,255,255,0.4),0_8px_24px_-8px_rgba(255,255,255,0.5)] hover:shadow-[0_0_0_1px_rgba(255,255,255,0.6),0_10px_32px_-6px_oklch(0.8_0.12_300)]");
const DARK = cn(BTN, "border border-white/15 bg-black/60 text-white backdrop-blur hover:bg-white/10");
/** An accent word: VT323 in the gold to violet shine. */
const ACCENT = "text-shine font-pixel font-normal tracking-normal";

function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span className="pixel-label inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-[15px] text-white/75 backdrop-blur">
      <span className="size-1.5 animate-pulse rounded-full bg-gold" />{children}
    </span>
  );
}

/** A raised key, like a keyboard cap, holding one glyph. */
function Keycap({ children, big }: { children: React.ReactNode; big?: boolean }) {
  return (
    <div className={cn("grid shrink-0 place-items-center rounded-2xl border border-white/15 bg-linear-to-b from-[oklch(0.38_0.02_295)] to-[oklch(0.16_0.02_295)] p-1.5 shadow-[0_18px_40px_-12px_rgba(0,0,0,0.9),inset_0_1px_0_rgba(255,255,255,0.25)]",
      big ? "size-16 sm:size-20" : "size-12 sm:size-14")}>
      <div className="grid size-full place-items-center rounded-xl bg-black/85 text-white shadow-[inset_0_2px_6px_rgba(0,0,0,0.8)]">{children}</div>
    </div>
  );
}

/** Artwork in a rounded frame that leans in slightly on hover. */
function Art({ src, alt, className, priority }: { src: string; alt: string; className?: string; priority?: boolean }) {
  return (
    <div className={cn("relative overflow-hidden rounded-3xl border border-white/10 bg-black", className)}>
      <Image src={src} alt={alt} fill unoptimized priority={priority} sizes="(min-width: 768px) 60vw, 100vw"
             className="object-cover transition-transform duration-[1.2s] ease-[cubic-bezier(0.22,1,0.36,1)] group-hover:scale-[1.04]" />
      <div aria-hidden className="absolute inset-0 rounded-3xl shadow-[inset_0_1px_0_rgba(255,255,255,0.12)]" />
    </div>
  );
}

export default async function Landing() {
  const plans = await getPlans();
  return (
    <div className="dark relative isolate min-h-svh overflow-x-clip bg-[linear-gradient(to_bottom,oklch(0.14_0.05_292),#050308_55%)] text-foreground">
      <BinaryField />

      <header className="sticky top-0 z-30 border-b border-white/5 bg-black/30 backdrop-blur-xl">
        <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between gap-3 px-4 sm:px-6">
          <Link href="/" aria-label="Lanka Link home" className="shrink-0 text-white"><LogoMark mono className="h-7 sm:h-8" /></Link>
          <nav aria-label="Site" className="hidden items-center gap-8 md:flex">
            {NAV.map(([label, href]) => <Link key={href} href={href} className="pixel-label text-[17px] text-white/60 transition-colors hover:text-white">{label}</Link>)}
          </nav>
          <div className="flex items-center gap-2">
            <SessionNav light={LIGHT} dark={cn(DARK, "max-[380px]:hidden")} />
            {/* A phone gets the site links in a small menu: native details, no script. */}
            <details className="group relative md:hidden">
              <summary aria-label="Menu" className="grid size-10 cursor-pointer list-none place-items-center rounded-full border border-white/15 bg-black/60 text-white [&::-webkit-details-marker]:hidden">
                <MenuIcon className="size-4" />
              </summary>
              <nav aria-label="Site" className="absolute top-12 right-0 w-48 rounded-2xl border border-white/10 bg-black/90 p-1.5 shadow-2xl backdrop-blur-xl">
                {[...NAV, ["Sign in", "/sign-in"] as [string, string]].map(([label, href]) => (
                  <Link key={href} href={href} className="pixel-label block rounded-xl px-3 py-3 text-[17px] text-white/75 hover:bg-white/10 hover:text-white">{label}</Link>
                ))}
              </nav>
            </details>
          </div>
        </div>
      </header>

      <Reveal>
        <main>
          {/* Hero: the headline over the flipping field, a horizon of light rising beneath it. */}
          <section className="relative isolate flex min-h-[88svh] flex-col items-center justify-center overflow-hidden px-4 pt-12 pb-40 text-center sm:px-6 sm:pb-44">
            <div aria-hidden className="absolute inset-x-0 bottom-0 -z-10 h-[70%]" style={{ background: HORIZON }} />
            <div data-reveal="now"><Tag>New: support in Sinhala, Tamil and English</Tag></div>
            <h1 data-reveal="now" className="mt-8 max-w-4xl bg-linear-to-b from-white to-[oklch(0.84_0.07_305)] bg-clip-text text-[2.6rem] leading-[1.02] font-medium tracking-tight text-balance text-transparent sm:text-6xl md:text-7xl">
              Internet That <span className={cn(ACCENT, "text-[1.2em]")}>Knows</span> Your Line and <span className={cn(ACCENT, "text-[1.2em]")}>Answers</span> in Your Language
            </h1>
            <p data-reveal="now" className="mt-6 max-w-xl text-base text-balance text-white/60 sm:text-lg">
              Fibre, home broadband and mobile data across Sri Lanka, with support that reads your line before it replies.
            </p>
            <div data-reveal="now" className="mt-10 flex flex-wrap justify-center gap-3">
              <Link href="/sign-up" className={LIGHT}>Start with a plan</Link>
              <Link href="/docs" className={DARK}>See how it works</Link>
            </div>
          </section>

          {/* The band under the horizon: one statement, the artwork, the mark on a key. */}
          <section className="relative isolate px-4 pt-16 sm:px-6 sm:pt-20">
            <div aria-hidden className="absolute inset-0 -z-10 bg-[linear-gradient(to_bottom,oklch(0.4_0.17_296),oklch(0.2_0.08_295)_30%,transparent_70%)]" />
            <div aria-hidden className="absolute inset-x-0 top-0 h-px bg-linear-to-r from-transparent via-white/80 to-transparent" />
            <p data-reveal className="mx-auto max-w-3xl text-center text-3xl leading-tight font-light tracking-tight text-balance text-white md:text-5xl">
              Fibre at home. Data on the go. <span className="text-white/50">Support that already knows what is wrong.</span>
            </p>
            <figure data-reveal className="group mx-auto mt-14 w-full max-w-6xl">
              <Art src="/art/fibre.webp" alt="Strands of violet light fanning out across the dark, like fibre carrying a signal" className="aspect-[4/3] sm:aspect-[16/8]" />
              <figcaption className="mt-4 flex flex-wrap items-baseline justify-between gap-2 px-1">
                <span className="text-sm text-white/60">One network, from the core to your router, read in seconds.</span>
                <span className="pixel-label text-[15px] text-white/40">Fibre / 2026</span>
              </figcaption>
            </figure>
            <div data-reveal className="mt-14 flex justify-center"><Keycap big><LogoIcon mono className="size-8 sm:size-9" /></Keycap></div>
            <div aria-hidden className="mx-auto h-24 w-px bg-linear-to-b from-white/50 via-[oklch(0.8_0.1_305)]/60 to-[oklch(0.8_0.1_305)] sm:h-36" />
            <div aria-hidden className="mx-auto h-px w-full max-w-5xl bg-linear-to-r from-transparent via-[oklch(0.8_0.1_305)] to-transparent" />
          </section>

          {/* What we do: a statement and the flow on a dotted plate, then one artwork per promise. */}
          <section aria-labelledby="what" className="mx-auto w-full max-w-6xl border-white/10 md:border-x">
            <div className="grid md:grid-cols-2">
              <div data-reveal className="border-b border-white/10 px-4 py-10 sm:p-8 md:border-r md:p-12">
                <Tag>What we do</Tag>
                <h2 id="what" className="mt-8 text-3xl leading-tight font-light tracking-tight text-white md:text-4xl">
                  Support at full speed. <span className="text-white/45">Every request is read against your own line, your bill and our network, then answered in the language you wrote.</span>
                </h2>
                <Link href="/docs" className={cn(DARK, "mt-10")}>Read how <ArrowRightIcon className="size-3.5" /></Link>
              </div>
              <div data-reveal className="relative flex min-h-64 items-center justify-center gap-2 border-b border-white/10 p-6 sm:min-h-80 sm:gap-3 sm:p-8 [background-image:radial-gradient(rgba(255,255,255,0.14)_1px,transparent_1px)] [background-size:16px_16px]">
                <Keycap><MessageSquareTextIcon className="size-5 sm:size-6" /></Keycap>
                <span aria-hidden className="h-px w-6 border-t border-dashed border-white/30 sm:w-16" />
                <Keycap big><LogoIcon mono className="size-8 sm:size-9" /></Keycap>
                <span aria-hidden className="h-px w-6 border-t border-dashed border-white/30 sm:w-16" />
                <Keycap><CheckCheckIcon className="size-5 sm:size-6" /></Keycap>
              </div>
            </div>
            <div className="grid gap-10 px-4 py-12 sm:px-8 md:grid-cols-3 md:gap-6 md:px-12">
              {DOES.map((d) => (
                <article key={d.k} data-reveal className="group">
                  <Art src={d.art} alt="" className="aspect-[4/3]" />
                  <p className="pixel-label mt-5 text-[15px] text-gold/80">{d.k}</p>
                  <h3 className="mt-2 text-xl font-medium text-white">{d.title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-white/55">{d.rest}</p>
                </article>
              ))}
            </div>
          </section>

          <section aria-labelledby="how" className="mx-auto w-full max-w-6xl border-t border-white/10 px-4 py-16 sm:px-8 sm:py-20 md:border-x md:px-12">
            <div data-reveal><Tag>How it works</Tag></div>
            <h2 id="how" data-reveal className="mt-8 max-w-2xl text-3xl leading-tight font-light tracking-tight text-white md:text-4xl">
              A reply that starts <span className={cn(ACCENT, "text-[1.2em]")}>on your side</span> of the line.
            </h2>
            <ol className="mt-12 grid gap-8 md:grid-cols-3">
              {STEPS.map((s, i) => (
                <li key={s.title} data-reveal className="border-t border-white/15 pt-5">
                  <p className="font-pixel text-3xl leading-none text-white/35">0{i + 1}</p>
                  <h3 className="mt-3 text-lg font-medium text-white">{s.title}</h3>
                  <p className="mt-1 text-sm text-white/55">{s.body}</p>
                </li>
              ))}
            </ol>
          </section>

          <section aria-labelledby="plans" className="mx-auto w-full max-w-6xl border-t border-white/10 px-4 py-16 sm:px-8 sm:py-20 md:border-x md:px-12">
            <div data-reveal className="mb-10 flex flex-wrap items-end justify-between gap-4">
              <div>
                <Tag>Plans</Tag>
                <h2 id="plans" className="mt-8 text-3xl font-light tracking-tight text-white md:text-4xl">Pick a plan, <span className={cn(ACCENT, "text-[1.2em]")}>connect in days.</span></h2>
              </div>
              <Link href="/plans" className={DARK}>Every plan <ArrowUpRightIcon className="size-3.5" /></Link>
            </div>
            {plans.length ? (
              <div className="grid gap-4 md:grid-cols-3">{plans.slice(0, 3).map((p) => <div key={p.code} data-reveal><PlanCard plan={p} /></div>)}</div>
            ) : <p className="text-white/55">Plans are loading. Refresh in a moment.</p>}
          </section>

          <section data-reveal className="relative isolate mx-auto w-full max-w-6xl overflow-hidden border-y border-white/10 px-4 py-20 text-center sm:px-8 sm:py-24 md:border md:px-12">
            <div aria-hidden className="absolute inset-x-0 bottom-0 -z-10 h-full opacity-70" style={{ background: HORIZON }} />
            <h2 className="text-4xl font-light tracking-tight text-white md:text-5xl">Ready <span className={cn(ACCENT, "text-[1.2em]")}>when you are.</span></h2>
            <p className="mx-auto mt-4 max-w-md text-white/60">Choose a plan, tell us where you are, and your line is set up for you.</p>
            <div className="mt-10 flex flex-wrap justify-center gap-3">
              <Link href="/sign-up" className={LIGHT}>Get started</Link>
              <Link href="/plans" className={DARK}>Compare plans</Link>
            </div>
          </section>
        </main>
      </Reveal>

      <footer className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-6 px-4 py-12 sm:px-6">
        <LogoMark mono className="h-7 text-white" />
        <nav aria-label="Footer" className="flex gap-6">
          {NAV.map(([label, href]) => <Link key={href} href={href} className="pixel-label text-[17px] text-white/50 hover:text-white">{label}</Link>)}
        </nav>
        <p className="pixel-label w-full text-[14px] text-white/30">Lanka Link, Sri Lanka</p>
      </footer>
    </div>
  );
}
