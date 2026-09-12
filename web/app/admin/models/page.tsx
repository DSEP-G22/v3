"use client";

import { useState } from "react";
import { toast } from "sonner";

import { StatusDot, type Tone } from "@/components/status-dot";
import { Button } from "@/components/ui/button";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, post, useApi } from "@/lib/api";

type Role = {
  role: string; stage: string; summary: string; allowed: string[]; impl: string; model_version: string;
  generation: number; probe_status: string; probe_detail: string; probe_ms: number | null; updated_by: string;
};
type Event = { id: string; role: string; from_binding: string; to_binding: string; actor: string; reason: string; at: string };

const TONE: Record<string, Tone> = { reachable: "ok", degraded: "warn", down: "bad", unknown: "idle" };
const WORD: Record<string, string> = { reachable: "Reachable", degraded: "Degraded", down: "Down", unknown: "Not checked" };

export default function Models() {
  const { data, loading, reload } = useApi<{ roles: Role[] }>("/admin/models");
  const history = useApi<{ events: Event[] }>("/admin/models/history");
  const [edit, setEdit] = useState<(Role & { reason: string }) | null>(null);
  const [testing, setTesting] = useState(false);

  async function save() {
    if (!edit) return;
    try {
      await api(`/admin/models/${edit.role}`, {
        method: "PUT", body: JSON.stringify({ impl: edit.impl, model_version: edit.model_version, reason: edit.reason }),
      });
      toast.success("Switched. It takes effect on the next case, no restart.");
      setEdit(null);
      void reload();
      void history.reload();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  async function test(role: string) {
    setTesting(true);
    const r = await post<{ status: string; detail: string; ms: number }>(`/admin/models/${role}/probe`).catch((e) => {
      toast.error((e as Error).message);
      return null;
    });
    setTesting(false);
    if (r) toast[r.status === "reachable" ? "success" : "error"](`${WORD[r.status] ?? r.status}: ${r.detail}`);
    void reload();
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Models</h1>
        <p className="text-sm text-muted-foreground">Each job is a role. Rebinding a role takes effect without a restart.</p>
      </div>
      {loading ? <Skeleton className="h-60" /> : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Role</TableHead>
                <TableHead>Bound to</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Response</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data?.roles.map((r) => (
                <TableRow key={r.role} className="cursor-pointer" onClick={() => setEdit({ ...r, reason: "" })}>
                  <TableCell>
                    <span className="font-medium">{r.role.replace(/_/g, " ")}</span>
                    <span className="block text-xs text-muted-foreground">{r.summary}</span>
                  </TableCell>
                  <TableCell className="font-mono text-xs">{r.impl}:{r.model_version}</TableCell>
                  <TableCell><StatusDot tone={TONE[r.probe_status] ?? "idle"} label={WORD[r.probe_status] ?? r.probe_status} /></TableCell>
                  <TableCell className="tabular-nums text-muted-foreground">{r.probe_ms != null ? `${r.probe_ms} ms` : ""}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <section>
        <h2 className="mb-2 font-medium">History</h2>
        <ul className="space-y-1 text-sm">
          {history.data?.events.slice(0, 12).map((e) => (
            <li key={e.id} className="text-muted-foreground">
              <span className="text-foreground">{e.role.replace(/_/g, " ")}</span> {e.from_binding} to {e.to_binding}, by {e.actor}
              {e.reason && `: ${e.reason}`} ({new Date(e.at).toLocaleString()})
            </li>
          ))}
          {!history.data?.events.length && <li className="text-muted-foreground">No changes yet.</li>}
        </ul>
      </section>

      <Sheet open={edit !== null} onOpenChange={(o) => !o && setEdit(null)}>
        <SheetContent>
          {edit && (
            <>
              <SheetHeader>
                <SheetTitle>{edit.role.replace(/_/g, " ")}</SheetTitle>
                <SheetDescription>{edit.summary}</SheetDescription>
              </SheetHeader>
              <FieldGroup className="px-4">
                <Field>
                  <FieldLabel>Implementation</FieldLabel>
                  <Select value={edit.impl} onValueChange={(v) => setEdit({ ...edit, impl: String(v) })}
                          items={edit.allowed.map((a) => ({ value: a, label: a }))}>
                    <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                    <SelectContent>{edit.allowed.map((a) => <SelectItem key={a} value={a}>{a}</SelectItem>)}</SelectContent>
                  </Select>
                </Field>
                <Field>
                  <FieldLabel htmlFor="mv">Model</FieldLabel>
                  <Input id="mv" value={edit.model_version} onChange={(e) => setEdit({ ...edit, model_version: e.target.value })} />
                </Field>
                <Field>
                  <FieldLabel htmlFor="why">Reason</FieldLabel>
                  <Input id="why" value={edit.reason} onChange={(e) => setEdit({ ...edit, reason: e.target.value })}
                         placeholder="Why you are changing it" />
                </Field>
              </FieldGroup>
              <SheetFooter>
                <Button variant="outline" disabled={testing} onClick={() => test(edit.role)}>
                  {testing ? "Testing" : "Test current binding"}
                </Button>
                <Button onClick={save}>Save</Button>
              </SheetFooter>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
