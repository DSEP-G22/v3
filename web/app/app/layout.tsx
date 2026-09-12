"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { Brand } from "@/components/brand";
import { RoleGate } from "@/components/role-gate";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/app", label: "Home" },
  { href: "/app/support", label: "Support" },
  { href: "/app/billing", label: "Billing" },
  { href: "/app/usage", label: "Usage" },
  { href: "/app/plan", label: "Plan" },
  { href: "/app/settings", label: "Settings" },
];

export default function CustomerLayout({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  return (
    <RoleGate roles={["customer"]}>
      <div className="flex min-h-svh flex-col text-[15px]">
        <header className="border-b">
          <div className="mx-auto flex h-14 w-full max-w-5xl items-center gap-6 px-4">
            <Brand href="/app" />
            <nav className="-mx-2 flex gap-1 overflow-x-auto text-sm" aria-label="Main">
              {NAV.map((n) => {
                const active = n.href === "/app" ? path === "/app" : path.startsWith(n.href);
                return (
                  <Link
                    key={n.href}
                    href={n.href}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "rounded-md px-2.5 py-1.5 whitespace-nowrap text-muted-foreground transition-colors hover:text-foreground",
                      active && "bg-muted text-foreground",
                    )}
                  >
                    {n.label}
                  </Link>
                );
              })}
            </nav>
          </div>
        </header>
        <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8">{children}</main>
      </div>
    </RoleGate>
  );
}
