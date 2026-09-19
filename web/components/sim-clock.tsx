"use client";

import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { post, useApi } from "@/lib/api";

type Clock = { sim_now_display: string; speed: number; paused: boolean };

/** The sticky sim clock. Business is its single source; sim time only moves forward. */
export function SimClockBar() {
  const { data, reload } = useApi<Clock>("/sim/clock");

  async function send(path: string, body: unknown, note?: string) {
    try {
      await post(`/sim/${path}`, body);
      if (note) toast.success(note);
      void reload();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  if (!data) return null;
  return (
    <div className="flex min-w-0 flex-1 items-center gap-1.5 overflow-x-auto text-sm whitespace-nowrap [scrollbar-width:none] md:flex-wrap">
      <span className="mr-2 shrink-0 tabular-nums font-medium">{data.sim_now_display}</span>
      <Button size="xs" variant={data.paused ? "default" : "outline"}
              onClick={() => send("clock", { action: data.paused ? "resume" : "pause" })}>
        {data.paused ? "Resume" : "Pause"}
      </Button>
      {[1, 10, 60].map((s) => (
        <Button key={s} size="xs" variant={!data.paused && data.speed === s ? "secondary" : "ghost"}
                onClick={() => send("clock", { action: "speed", speed: s })}>
          {s}x
        </Button>
      ))}
      <Button size="xs" variant="ghost" onClick={() => send("advance", { hours: 1 }, "Moved forward one hour")}>+1 hour</Button>
      <Button size="xs" variant="ghost" onClick={() => send("advance", { hours: 24 }, "Moved forward one day")}>+1 day</Button>
      <Button size="xs" variant="ghost" onClick={() => send("advance", { to: "next_bill_run" }, "Moved to the next bill run")}>
        Next bill run
      </Button>
    </div>
  );
}
