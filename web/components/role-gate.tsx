"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { forgetToken } from "@/lib/api";
import { signOut, useSession } from "@/lib/auth-client";

export type Role = "customer" | "agent" | "lead" | "admin" | "operator";

export function roleOf(user: unknown): Role {
  return ((user as { role?: Role } | undefined)?.role ?? "customer") as Role;
}

export function homeFor(role: Role): string {
  return { customer: "/app", agent: "/console", lead: "/console", admin: "/admin", operator: "/sim" }[role];
}

let leaving = false;

/**
 * Sign out and go to `to`. Every sign-out button uses this: once the session clears, a mounted
 * RoleGate would otherwise send the person to sign-in before their own navigation lands.
 */
export async function signOutTo(router: { replace: (href: string) => void }, to: string) {
  leaving = true;
  await signOut();
  forgetToken();
  router.replace(to);
  setTimeout(() => { leaving = false; }, 3_000);
}

/** Client-side convenience only: the gateway enforces every role on every request. */
export function RoleGate({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { data, isPending } = useSession();
  const router = useRouter();
  const role = roleOf(data?.user);
  const allowed = !!data && roles.includes(role);

  useEffect(() => {
    if (isPending || leaving) return;
    if (!data) router.replace(`/sign-in?next=${encodeURIComponent(window.location.pathname)}`);
    else if (!roles.includes(role)) router.replace(homeFor(role));
  }, [isPending, data, role, roles, router]);

  if (!allowed) {
    return (
      <div className="mx-auto w-full max-w-5xl space-y-4 p-6" aria-busy="true">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }
  return <>{children}</>;
}
