"use client";

import { GaugeIcon, GlobeIcon, HouseIcon, LifeBuoyIcon, LogOutIcon, ReceiptTextIcon, SettingsIcon, WifiIcon, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { Brand } from "@/components/brand";
import { RoleGate, signOutTo } from "@/components/role-gate";
import { Button, buttonVariants } from "@/components/ui/button";
import { prefetch } from "@/lib/api";
import { cn } from "@/lib/utils";

const WARM = ["/app/overview", "/app/tickets", "/app/notices", "/app/billing", "/app/usage", "/app/plan"];

type Item = { href: string; label: string; icon: LucideIcon; sub?: { href: string; label: string }[] };
const NAV: Item[] = [
  { href: "/app", label: "Home", icon: HouseIcon },
  { href: "/app/tickets", label: "Support", icon: LifeBuoyIcon, sub: [{ href: "/app/tickets", label: "Your tickets" }, { href: "/app/tickets/new", label: "Open a ticket" }] },
  { href: "/app/billing", label: "Billing", icon: ReceiptTextIcon, sub: [{ href: "/app/billing?tab=overview", label: "Overview" },
    { href: "/app/billing?tab=activity", label: "Activity" }, { href: "/app/billing?tab=invoices", label: "Invoices" }] },
  { href: "/app/usage", label: "Usage", icon: GaugeIcon },
  { href: "/app/plan", label: "Plan", icon: WifiIcon },
  { href: "/app/settings", label: "Settings", icon: SettingsIcon },
];
/** A phone gets these as a bottom tab bar (five at most); Settings moves to the header. */
const TABS = NAV.filter((n) => n.href !== "/app/settings");

export default function CustomerLayout({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const isActive = (href: string) => (href === "/app" ? path === "/app" : path.startsWith(href));
  // Every tab's data, fetched once in the background: switching tabs then shows it at once.
  useEffect(() => {
    const t = setTimeout(() => WARM.forEach(prefetch), 300);
    return () => clearTimeout(t);
  }, []);
  return (
    <RoleGate roles={["customer"]}>
      <div className="flex min-h-svh flex-col text-[15px]">
        <header className="sticky top-0 z-30 border-b bg-background/75 backdrop-blur-xl">
          <div className="mx-auto flex h-14 w-full max-w-5xl items-center gap-6 px-4">
            <Brand href="/app" />
            <nav className="-mx-2 hidden gap-1 text-sm md:flex" aria-label="Main">
              {NAV.map((n) => {
                const active = isActive(n.href);
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
              <Link href="/app/settings" aria-label="Settings" title="Settings" aria-current={isActive("/app/settings") ? "page" : undefined}
                    className={buttonVariants({ variant: "ghost", size: "icon-lg", className: cn("text-muted-foreground md:hidden", isActive("/app/settings") && "text-primary") })}>
                <SettingsIcon />
              </Link>
              <Link href="/" aria-label="Lanka Link website" title="Lanka Link website"
                    className={buttonVariants({ variant: "ghost", size: "sm", className: "text-muted-foreground max-md:size-11" })}>
                <GlobeIcon /> <span className="hidden md:inline">Website</span>
              </Link>
              <Button variant="ghost" size="sm" className="text-muted-foreground max-md:size-11" aria-label="Sign out" title="Sign out"
                      onClick={() => signOutTo(router, "/")}>
                <LogOutIcon /> <span className="hidden md:inline">Sign out</span>
              </Button>
            </div>
          </div>
        </header>
        <main className="mx-auto w-full max-w-5xl flex-1 px-4 pt-6 pb-28 md:py-8">{children}</main>
        <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-30 border-t bg-background/85 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl md:hidden">
          <ul className="mx-auto grid max-w-md grid-cols-5">
            {TABS.map(({ href, label, icon: Icon }) => {
              const active = isActive(href);
              return (
                <li key={href}>
                  <Link href={href} aria-current={active ? "page" : undefined}
                        className={cn("flex min-h-14 flex-col items-center justify-center gap-1 text-[11px] text-muted-foreground transition-colors",
                          active && "font-medium text-primary")}>
                    <span className={cn("grid h-7 w-12 place-items-center rounded-full transition-colors", active && "bg-primary/10")}>
                      <Icon className="size-5" aria-hidden />
                    </span>
                    {label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </div>
    </RoleGate>
  );
}
