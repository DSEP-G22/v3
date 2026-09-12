import Link from "next/link";

import { PlanCard } from "@/components/plan-card";
import { SiteHeader } from "@/components/site-header";
import { buttonVariants } from "@/components/ui/button";
import { getPlans } from "@/lib/server";

export const revalidate = 60;

export default async function Landing() {
  const plans = await getPlans();
  return (
    <>
      <SiteHeader />
      <main className="mx-auto w-full max-w-6xl px-4">
        <section className="flex flex-col items-start gap-6 py-20 md:py-28">
          <h1 className="max-w-2xl text-4xl font-semibold tracking-tight text-balance md:text-5xl">
            Internet that keeps up with you, across Sri Lanka.
          </h1>
          <p className="max-w-xl text-lg text-muted-foreground">
            Fibre, home broadband and mobile data, with support that answers in English, Sinhala and Tamil.
          </p>
          <div className="flex gap-2">
            <Link href="/sign-up" className={buttonVariants({ size: "lg" })}>
              Get started
            </Link>
            <Link href="/plans" className={buttonVariants({ size: "lg", variant: "outline" })}>
              Compare plans
            </Link>
          </div>
        </section>

        <section aria-labelledby="plans" className="pb-24">
          <h2 id="plans" className="mb-6 text-xl font-medium">
            Plans
          </h2>
          {plans.length ? (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {plans.slice(0, 3).map((p) => (
                <PlanCard key={p.code} plan={p} />
              ))}
            </div>
          ) : (
            <p className="text-muted-foreground">Plans are loading. Refresh in a moment.</p>
          )}
        </section>
      </main>
    </>
  );
}
