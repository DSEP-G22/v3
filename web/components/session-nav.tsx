"use client";

import { ArrowUpRightIcon } from "lucide-react";
import Link from "next/link";

import { homeFor, roleOf } from "@/components/role-gate";
import { useSession } from "@/lib/auth-client";

const PLACE: Record<string, string> = { customer: "Your account", agent: "Console", lead: "Console", admin: "Admin", operator: "Simulation" };

/**
 * The header's sign-in corner. Signed out: Sign in and Get started. Signed in: one account chip,
 * the initial with a live dot, who is signed in and where it leads, so the session visibly persists.
 */
export function SessionNav({ light, dark }: { light: string; dark: string }) {
  const { data, isPending } = useSession();
  if (isPending) return <span className="h-10 w-28 animate-pulse rounded-full bg-foreground/5" aria-hidden />; // hold the space
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
    <Link href={homeFor(role)} aria-label={`Signed in as ${name}. Open ${PLACE[role]}`}
          className="group inline-flex h-10 items-center gap-2.5 rounded-full border border-foreground/10 bg-background/40 py-1 pr-3 pl-1 backdrop-blur transition-[border-color,background-color,box-shadow] duration-300 hover:border-primary/40 hover:bg-background/70 hover:shadow-[0_0_24px_-6px_var(--primary)]">
      <span aria-hidden className="relative grid size-8 place-items-center rounded-full bg-linear-to-br from-lilac via-primary to-[oklch(0.35_0.15_295)] text-sm font-semibold text-white">
        {name.slice(0, 1).toUpperCase()}
        <span className="absolute -right-0.5 -bottom-0.5 size-2.5 rounded-full border-2 border-background bg-success" />
      </span>
      <span className="hidden flex-col text-left leading-none sm:flex">
        <span className="pixel-label text-[13px] text-muted-foreground">Signed in as</span>
        <span className="mt-0.5 max-w-32 truncate text-sm font-medium">{name}</span>
      </span>
      <span aria-hidden className="hidden h-5 w-px bg-foreground/10 sm:block" />
      <span className="flex items-center gap-1 text-sm font-medium">
        <span className="max-sm:sr-only">{PLACE[role]}</span>
        <ArrowUpRightIcon aria-hidden className="size-4 text-muted-foreground transition-transform duration-300 group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-foreground" />
      </span>
    </Link>
  );
}
