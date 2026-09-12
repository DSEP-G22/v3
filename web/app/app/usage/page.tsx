"use client";

import { Area, AreaChart, CartesianGrid, XAxis } from "recharts";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { Skeleton } from "@/components/ui/skeleton";
import { useApi } from "@/lib/api";

type Usage = {
  used_display: string;
  allowance_display: string;
  cycle_ends_display: string;
  daily: { date: string; gb: number }[];
  health: string;
};

const config = { gb: { label: "Data used (GB)", color: "var(--chart-1)" } } satisfies ChartConfig;

export default function UsagePage() {
  const { data, loading, error } = useApi<Usage>("/app/usage");
  if (loading) return <Skeleton className="h-80" />;
  if (error || !data) return <p className="text-muted-foreground">{error?.message}</p>;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Usage</h1>
      <Card>
        <CardHeader>
          <CardDescription>This cycle, ending {data.cycle_ends_display}</CardDescription>
          <CardTitle className="text-xl">{data.allowance_display}</CardTitle>
        </CardHeader>
        <CardContent>
          {data.daily.length ? (
            <ChartContainer config={config} className="aspect-auto h-64 w-full">
              <AreaChart data={data.daily} margin={{ left: 4, right: 4 }}>
                <CartesianGrid vertical={false} />
                <XAxis
                  dataKey="date"
                  tickLine={false}
                  axisLine={false}
                  minTickGap={32}
                  tickFormatter={(d: string) => new Date(d).toLocaleDateString(undefined, { day: "numeric", month: "short" })}
                />
                <ChartTooltip content={<ChartTooltipContent indicator="line" />} />
                <Area dataKey="gb" type="monotone" fill="var(--color-gb)" fillOpacity={0.15} stroke="var(--color-gb)" />
              </AreaChart>
            </ChartContainer>
          ) : (
            <p className="text-muted-foreground">Usage appears here after your first day online.</p>
          )}
        </CardContent>
      </Card>
      <p className="max-w-prose">{data.health}</p>
    </div>
  );
}
