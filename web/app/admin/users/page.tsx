"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { post } from "@/lib/api";
import { authClient } from "@/lib/auth-client";

type User = { id: string; name: string; email: string; role?: string | null; createdAt: string | Date };
const ROLES = ["customer", "agent", "lead", "admin", "operator"];

export default function Users() {
  const [users, setUsers] = useState<User[] | null>(null);
  const [q, setQ] = useState("");
  const [link, setLink] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    const { data } = await authClient.admin.listUsers({
      query: { limit: 100, ...(q ? { searchValue: q, searchField: "email" as const } : {}) },
    });
    setUsers((data?.users ?? []) as User[]);
  }, [q]);

  useEffect(() => {
    void load();
  }, [load]);

  async function setRole(id: string, role: string) {
    const { error } = await authClient.admin.setRole({ userId: id, role: role as "admin" });
    if (error) toast.error(error.message ?? "Could not change the role.");
    else toast.success("Role changed. It applies from their next sign in.");
    void load();
  }

  async function linkCustomer(id: string) {
    try {
      await post("/admin/links", { user_id: id, subscriber_ref: link[id] });
      toast.success("Linked to the customer record.");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold tracking-tight">Users and roles</h1>
      <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by email" className="max-w-sm" />
      {!users ? <Skeleton className="h-72" /> : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Person</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Customer record</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.map((u) => (
                <TableRow key={u.id}>
                  <TableCell>
                    <span className="font-medium">{u.name}</span>
                    <span className="block text-xs text-muted-foreground">{u.email}</span>
                  </TableCell>
                  <TableCell>
                    <Select value={u.role ?? "customer"} onValueChange={(v) => setRole(u.id, String(v))}
                            items={ROLES.map((r) => ({ value: r, label: r }))}>
                      <SelectTrigger className="w-36"><SelectValue /></SelectTrigger>
                      <SelectContent>{ROLES.map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent>
                    </Select>
                  </TableCell>
                  <TableCell>
                    {(u.role ?? "customer") === "customer" && (
                      <div className="flex gap-2">
                        <Input className="w-36" placeholder="SUB-100002" value={link[u.id] ?? ""}
                               onChange={(e) => setLink({ ...link, [u.id]: e.target.value })} />
                        <Button size="sm" variant="outline" disabled={!link[u.id]} onClick={() => linkCustomer(u.id)}>
                          Link
                        </Button>
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
