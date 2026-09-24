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

type Feedback = { rated: number; average: number | null; happy: number; unhappy: number;
  recent: { id: string; subject: string | null; rating: number; feedback: string | null; feedback_at: string }[] };

const config = { opened: { label: "Cases opened", color: "var(--chart-1)" } } satisfies ChartConfig;

function FeedbackCard() {
  const { data } = useApi<Feedback>("/admin/feedback");
  return (
    <Card>
      <CardHeader>
        <CardDescription>Customer feedback, last 30 days</CardDescription>
        <CardTitle className="flex items-baseline gap-2 text-2xl tabular-nums">
          {data?.average != null ? data.average.toFixed(1) : "No ratings yet"}
          {data?.average != null && <span className="text-sm font-normal text-muted-foreground">out of 5 from {data.rated} tickets</span>}
        </CardTitle>
      </CardHeader>
      {!!data?.recent.length && (
        <CardContent>
          <ul className="divide-y text-sm">
            {data.recent.map((r) => (
              <li key={r.id} className="flex gap-3 py-2">
                <span className="w-16 shrink-0 text-gold" aria-label={`${r.rating} of 5`}>{"★".repeat(r.rating)}<span className="text-muted">{"★".repeat(5 - r.rating)}</span></span>
                <span className="min-w-0">
                  <span className="block truncate font-medium">{r.subject}</span>
                  {r.feedback && <span className="text-muted-foreground">{r.feedback}</span>}
                </span>
              </li>
            ))}
          </ul>
        </CardContent>
      )}
    </Card>
  );
}

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
      <div>
        <p className="pixel-label text-[15px] text-primary">Admin</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Overview</h1>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {kpis.map((k) => (
          <div key={k.label} className="rounded-2xl border border-foreground/10 bg-card/60 p-4 backdrop-blur">
            <p className="text-xs text-muted-foreground">{k.label}</p>
            <p className="mt-3 font-pixel text-3xl leading-none sm:text-4xl">{k.value}</p>
          </div>
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
      <FeedbackCard />
    </div>
  );
}
