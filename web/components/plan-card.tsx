import { CheckIcon } from "lucide-react";
import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import type { Plan } from "@/lib/server";

export function PlanCard({ plan, href = "/sign-up" }: { plan: Plan; href?: string }) {
  return (
    <article className="surface-3d flex h-full flex-col rounded-3xl p-6">
      <p className="text-xs tracking-wide text-muted-foreground uppercase">{plan.family}, {plan.technology_display}</p>
      <h3 className="mt-2 text-lg font-semibold">{plan.name}</h3>
      <p className="mt-6 text-3xl font-semibold tracking-tight tabular-nums">
        {plan.price_display}
        <span className="text-sm font-normal text-muted-foreground"> a month</span>
      </p>
      <ul className="mt-6 flex-1 space-y-2.5 text-sm text-muted-foreground">
        {[`Up to ${plan.speed_display}`,
          plan.data_cap_display === "Unlimited" ? "Unlimited data" : `${plan.data_cap_display} of data`,
          plan.contract_display].map((line) => (
          <li key={line} className="flex items-center gap-2"><CheckIcon className="size-3.5 text-primary" />{line}</li>
        ))}
      </ul>
      <Link href={href} className={buttonVariants({ variant: "outline", className: "mt-8 w-full rounded-full border-white/15" })}>
        Choose {plan.name}
      </Link>
    </article>
  );
}
