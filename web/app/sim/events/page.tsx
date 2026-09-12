"use client";

import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApi } from "@/lib/api";

type Event = { id: string; kind: string; target: string; note: string; actor: string; occurred_display: string };

export default function Events() {
  const { data, loading } = useApi<{ events: Event[] }>("/sim/events?limit=200");
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold tracking-tight">Event log</h1>
      {loading ? <Skeleton className="h-96" /> : !data?.events.length ? (
        <p className="text-muted-foreground">Nothing has happened yet.</p>
      ) : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>When</TableHead>
                <TableHead>What</TableHead>
                <TableHead>Target</TableHead>
                <TableHead>By</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.events.map((e) => (
                <TableRow key={e.id}>
                  <TableCell className="whitespace-nowrap text-muted-foreground">{e.occurred_display}</TableCell>
                  <TableCell>{e.note}</TableCell>
                  <TableCell>{e.target}</TableCell>
                  <TableCell className="text-muted-foreground">{e.actor}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
