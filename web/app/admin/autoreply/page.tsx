"use client";

import { useState } from "react";
import { toast } from "sonner";

import { StatusDot } from "@/components/status-dot";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, useApi } from "@/lib/api";
import { department } from "@/lib/format";

type Policy = {
  department: string;
  enabled: boolean;
  min_completeness: number;
  max_priority_level: number;
  require_clean_compliance: boolean;
  allow_with_action: boolean;
  updated_by: string;
};

export default function AutoReply() {
  const { data, loading, reload } = useApi<{ policies: Policy[] }>("/admin/autoreply");
  const [edit, setEdit] = useState<Policy | null>(null);

  async function save() {
    if (!edit) return;
    try {
      await api(`/admin/autoreply/${edit.department}`, {
        method: "PUT",
        body: JSON.stringify({
          enabled: edit.enabled, min_completeness: edit.min_completeness, max_priority_level: edit.max_priority_level,
          require_clean_compliance: edit.require_clean_compliance, allow_with_action: edit.allow_with_action,
        }),
      });
      toast.success("Saved. Services pick it up immediately.");
      setEdit(null);
      void reload();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Auto reply</h1>
        <p className="text-sm text-muted-foreground">
          Which departments may answer without a person. Every department starts switched off.
        </p>
      </div>
      {loading ? <Skeleton className="h-72" /> : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Department</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Needs grounding</TableHead>
                <TableHead>Up to priority</TableHead>
                <TableHead>With actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data?.policies.map((p) => (
                <TableRow key={p.department} className="cursor-pointer" onClick={() => setEdit({ ...p })}>
                  <TableCell className="font-medium">{p.department === "default" ? "Default" : department(p.department)}</TableCell>
                  <TableCell><StatusDot tone={p.enabled ? "ok" : "idle"} label={p.enabled ? "On" : "Off"} /></TableCell>
                  <TableCell className="tabular-nums">{Math.round(p.min_completeness * 100)}%</TableCell>
                  <TableCell className="tabular-nums">{p.max_priority_level}</TableCell>
                  <TableCell>{p.allow_with_action ? "Allowed" : "Held"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <Sheet open={edit !== null} onOpenChange={(o) => !o && setEdit(null)}>
        <SheetContent>
          {edit && (
            <>
              <SheetHeader>
                <SheetTitle>{edit.department === "default" ? "Default" : department(edit.department)}</SheetTitle>
                <SheetDescription>Last changed by {edit.updated_by}.</SheetDescription>
              </SheetHeader>
              <FieldGroup className="px-4">
                <Field orientation="horizontal">
                  <FieldLabel htmlFor="enabled">Answer without a person</FieldLabel>
                  <Switch id="enabled" checked={edit.enabled} onCheckedChange={(v) => setEdit({ ...edit, enabled: !!v })} />
                </Field>
                <Field>
                  <FieldLabel htmlFor="mc">Grounding needed (percent)</FieldLabel>
                  <Input id="mc" type="number" min={0} max={100} value={Math.round(edit.min_completeness * 100)}
                         onChange={(e) => setEdit({ ...edit, min_completeness: Number(e.target.value) / 100 })} />
                </Field>
                <Field>
                  <FieldLabel htmlFor="mp">Highest priority answered automatically</FieldLabel>
                  <Input id="mp" type="number" min={1} max={10} value={edit.max_priority_level}
                         onChange={(e) => setEdit({ ...edit, max_priority_level: Number(e.target.value) })} />
                  <FieldDescription>1 to 10. Anything above waits for a person.</FieldDescription>
                </Field>
                <Field orientation="horizontal">
                  <FieldLabel htmlFor="cc">Require a clean compliance check</FieldLabel>
                  <Switch id="cc" checked={edit.require_clean_compliance}
                          onCheckedChange={(v) => setEdit({ ...edit, require_clean_compliance: !!v })} />
                </Field>
                <Field orientation="horizontal">
                  <FieldLabel htmlFor="aa">Allow replies that credit, book or change a plan</FieldLabel>
                  <Switch id="aa" checked={edit.allow_with_action}
                          onCheckedChange={(v) => setEdit({ ...edit, allow_with_action: !!v })} />
                </Field>
              </FieldGroup>
              <SheetFooter>
                <Button onClick={save}>Save</Button>
              </SheetFooter>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
