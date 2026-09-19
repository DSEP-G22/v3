import { PlanCard } from "@/components/plan-card";
import { SiteHeader } from "@/components/site-header";
import { getPlans } from "@/lib/server";

// Rendered per request (the fetch keeps a one minute cache): prerendering at image build time, when
// no gateway exists, cached an empty catalogue that every deploy then served.
export const dynamic = "force-dynamic";
export const metadata = { title: "Plans" };

export default async function PlansPage() {
  const plans = await getPlans();
  return (
    <>
      <SiteHeader />
      <main className="mx-auto w-full max-w-6xl px-4 py-12">
        <h1 className="text-3xl font-semibold tracking-tight">Plans</h1>
        <p className="mt-2 text-muted-foreground">Prices include line rental. VAT is added at checkout.</p>
        {plans.length ? (
          <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {plans.map((p) => (
              <PlanCard key={p.code} plan={p} />
            ))}
          </div>
        ) : (
          <p className="mt-8 text-muted-foreground">Plans are loading. Refresh in a moment.</p>
        )}
      </main>
    </>
  );
}
