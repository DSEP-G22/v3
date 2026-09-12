"use client";

import { RoleGate } from "@/components/role-gate";
import { SimClockBar } from "@/components/sim-clock";
import { StaffShell } from "@/components/staff-shell";

export default function SimLayout({ children }: { children: React.ReactNode }) {
  return (
    <RoleGate roles={["operator", "admin"]}>
      <StaffShell bar={<SimClockBar />}>{children}</StaffShell>
    </RoleGate>
  );
}
