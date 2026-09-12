"use client";

import { Bar, BarChart, CartesianGrid, XAxis } from "recharts";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { Skeleton } from "@/components/ui/skeleton";
import { useApi } from "@/lib/api";

type Stats = {
  open_cases: number;
  median_reply_s: number | null;
  auto_share: number | null;
  p95_pipeline_ms: number | null;
  series: { hour: string; opened: number }[];
};

const config = { opened: { label: "Cases opened", color: "var(--chart-1)" } } satisfies ChartConfig;

function minutes(s: number | null) {
  if (s == null) return "No replies yet";
  return s < 90 ? `${Math.round(s)} s` : `${Math.round(s / 60)} min`;
}

export default function Overview() {
  const { data, loading } = useApi<Stats>("/admin/overview");
  if (loading || !data) return <Skeleton className="h-96" />;

  const kpis = [
    { label: "Open cases", value: String(data.open_cases) },
    { label: "Median time to first reply", value: minutes(data.median_reply_s) },
    { label: "Answered without a person", value: data.auto_share == null ? "None yet" : `${Math.round(data.auto_share * 100)}%` },
    { label: "Pipeline time, 95th percentile", value: data.p95_pipeline_ms == null ? "None yet" : `${(data.p95_pipeline_ms / 1000).toFixed(1)} s` },
  ];

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold tracking-tight">Overview</h1>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {kpis.map((k) => (
          <Card key={k.label} size="sm">
            <CardHeader>
              <CardDescription>{k.label}</CardDescription>
              <CardTitle className="text-2xl tabular-nums">{k.value}</CardTitle>
            </CardHeader>
          </Card>
        ))}
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Cases opened, last 24 hours</CardTitle>
        </CardHeader>
        <CardContent>
          {data.series.length ? (
            <ChartContainer config={config} className="aspect-auto h-64 w-full">
              <BarChart data={data.series}>
                <CartesianGrid vertical={false} />
                <XAxis dataKey="hour" tickLine={false} axisLine={false} minTickGap={24}
                       tickFormatter={(h: string) => new Date(h).toLocaleTimeString(undefined, { hour: "numeric" })} />
                <ChartTooltip content={<ChartTooltipContent />} />
                <Bar dataKey="opened" fill="var(--color-opened)" radius={4} />
              </BarChart>
            </ChartContainer>
          ) : (
            <p className="text-muted-foreground">No cases in the last 24 hours.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
