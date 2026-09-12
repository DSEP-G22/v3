"use client";

import { RoleGate } from "@/components/role-gate";
import { StaffShell } from "@/components/staff-shell";

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  return (
    <RoleGate roles={["agent", "lead", "admin"]}>
      <StaffShell>{children}</StaffShell>
    </RoleGate>
  );
}
