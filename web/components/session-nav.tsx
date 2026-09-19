"use client";

import { ArrowRightIcon } from "lucide-react";
import Link from "next/link";

import { homeFor, roleOf } from "@/components/role-gate";
import { useSession } from "@/lib/auth-client";

const PLACE: Record<string, string> = { customer: "Your account", agent: "Console", lead: "Console", admin: "Admin", operator: "Simulation" };

/**
 * The landing page's sign-in corner. Signed out: Sign in and Get started. Signed in: who you
 * are and a way straight back to your own portal, so the session visibly persists.
 */
export function SessionNav({ light, dark }: { light: string; dark: string }) {
  const { data, isPending } = useSession();
  if (isPending) return <span className="h-9 w-40" aria-hidden />; // hold the space, no flicker
  if (!data?.user) {
    return (
      <div className="flex items-center gap-2">
        <Link href="/sign-in" className={dark}>Sign in</Link>
        <Link href="/sign-up" className={light}>Get started</Link>
      </div>
    );
  }
  const role = roleOf(data.user);
  const name = data.user.name?.split(" ")[0] || data.user.email;
  return (
    <div className="flex items-center gap-3">
      <span className="hidden items-center gap-2 text-sm text-white/70 sm:flex">
        <span className="grid size-7 place-items-center rounded-full bg-white/15 text-xs font-medium text-white" aria-hidden>
          {name.slice(0, 1).toUpperCase()}
        </span>
        Signed in as {name}
      </span>
      <Link href={homeFor(role)} className={light}>{PLACE[role]} <ArrowRightIcon className="size-3.5" /></Link>
    </div>
  );
}
