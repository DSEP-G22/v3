import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import type { Plan } from "@/lib/server";

export function PlanCard({ plan, href = "/sign-up" }: { plan: Plan; href?: string }) {
  return (
    <Card className="h-full">
      <CardHeader>
        <CardDescription>{plan.family}</CardDescription>
        <CardTitle className="text-lg">{plan.name}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-4">
        <p className="text-2xl font-semibold tracking-tight">
          {plan.price_display}
          <span className="text-sm font-normal text-muted-foreground"> a month</span>
        </p>
        <ul className="space-y-1.5 text-sm text-muted-foreground">
          <li>Up to {plan.speed_display}</li>
          <li>{plan.data_cap_display === "Unlimited" ? "Unlimited data" : `${plan.data_cap_display} of data`}</li>
          <li>{plan.contract_display}</li>
        </ul>
        <Badge variant="secondary" className="w-fit">
          {plan.technology_display}
        </Badge>
      </CardContent>
      <CardFooter>
        <Link href={href} className={buttonVariants({ className: "w-full" })}>
          Choose {plan.name}
        </Link>
      </CardFooter>
    </Card>
  );
}
