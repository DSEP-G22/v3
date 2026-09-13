"use client";

import { GlobeIcon, LogOutIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { Brand } from "@/components/brand";
import { RoleGate } from "@/components/role-gate";
import { Button, buttonVariants } from "@/components/ui/button";
import { forgetToken } from "@/lib/api";
import { signOut } from "@/lib/auth-client";
import { cn } from "@/lib/utils";

type Item = { href: string; label: string; sub?: { href: string; label: string }[] };
const NAV: Item[] = [
  { href: "/app", label: "Home" },
  { href: "/app/tickets", label: "Support", sub: [{ href: "/app/tickets", label: "Your tickets" }, { href: "/app/tickets/new", label: "Open a ticket" }] },
  { href: "/app/billing", label: "Billing", sub: [{ href: "/app/billing?tab=overview", label: "Overview" },
    { href: "/app/billing?tab=activity", label: "Activity" }, { href: "/app/billing?tab=invoices", label: "Invoices" }] },
  { href: "/app/usage", label: "Usage" },
  { href: "/app/plan", label: "Plan" },
  { href: "/app/settings", label: "Settings" },
];

export default function CustomerLayout({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  return (
    <RoleGate roles={["customer"]}>
      <div className="flex min-h-svh flex-col text-[15px]">
        <header className="sticky top-0 z-30 border-b bg-background/75 backdrop-blur-xl">
          <div className="mx-auto flex h-14 w-full max-w-5xl items-center gap-6 px-4">
            <Brand href="/app" />
            <nav className="-mx-2 flex gap-1 overflow-x-auto text-sm md:overflow-visible" aria-label="Main">
              {NAV.map((n) => {
                const active = n.href === "/app" ? path === "/app" : path.startsWith(n.href);
                return (
                  <div key={n.href} className="group/nav relative">
                    <Link
                      href={n.href}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "block rounded-full px-3 py-1.5 whitespace-nowrap text-muted-foreground transition-colors hover:text-foreground",
                        active && "bg-primary/10 font-medium text-primary",
                      )}
                    >
                      {n.label}
                    </Link>
                    {/* Submenu on hover or keyboard focus, wide screens only; the page itself covers small ones. */}
                    {n.sub && (
                      <div className="invisible absolute top-full left-0 z-40 hidden pt-2 opacity-0 transition-[opacity,visibility] duration-150 group-focus-within/nav:visible group-focus-within/nav:opacity-100 group-hover/nav:visible group-hover/nav:opacity-100 md:block">
                        <ul className="min-w-44 rounded-xl border bg-popover/95 p-1 shadow-xl backdrop-blur-xl">
                          {n.sub.map((s) => (
                            <li key={s.href}>
                              <Link href={s.href} className="block rounded-lg px-3 py-2 whitespace-nowrap text-muted-foreground hover:bg-muted hover:text-foreground">
                                {s.label}
                              </Link>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                );
              })}
            </nav>
            <div className="ml-auto flex shrink-0 items-center gap-1">
              <Link href="/" aria-label="Lanka Link website" title="Lanka Link website"
                    className={buttonVariants({ variant: "ghost", size: "sm", className: "text-muted-foreground" })}>
                <GlobeIcon /> <span className="hidden md:inline">Website</span>
              </Link>
              <Button variant="ghost" size="sm" className="text-muted-foreground" aria-label="Sign out" title="Sign out"
                      onClick={async () => { await signOut(); forgetToken(); router.replace("/"); }}>
                <LogOutIcon /> <span className="hidden md:inline">Sign out</span>
              </Button>
            </div>
          </div>
        </header>
        <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8">{children}</main>
      </div>
    </RoleGate>
  );
}
