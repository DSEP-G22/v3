"use client";

import { RoleGate } from "@/components/role-gate";
import { StaffShell } from "@/components/staff-shell";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <RoleGate roles={["admin"]}>
      <StaffShell>{children}</StaffShell>
    </RoleGate>
  );
}
