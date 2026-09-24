import { MenuIcon } from "lucide-react";
import Link from "next/link";

import { Brand } from "@/components/brand";
import { SessionNav } from "@/components/session-nav";
import { buttonVariants } from "@/components/ui/button";

const NAV: [string, string][] = [["Plans", "/plans"], ["How it works", "/docs"]];

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-30 border-b border-foreground/5 bg-background/70 backdrop-blur-xl">
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between gap-3 px-4">
        <Brand className="shrink-0" />
        <nav className="flex items-center gap-1" aria-label="Site">
          {NAV.map(([label, href]) => (
            <Link key={href} href={href} className="pixel-label rounded-full px-3 py-2 text-[17px] text-muted-foreground transition-colors hover:text-foreground max-md:hidden">
              {label}
            </Link>
          ))}
          <SessionNav light={buttonVariants({ className: "h-10 rounded-full px-4 shadow-md shadow-primary/25" })}
                      dark={buttonVariants({ variant: "ghost", className: "h-10 rounded-full max-[380px]:hidden" })} />
          <details className="relative ml-1 md:hidden">
            <summary aria-label="Menu" className="grid size-10 cursor-pointer list-none place-items-center rounded-full border bg-background/60 [&::-webkit-details-marker]:hidden">
              <MenuIcon className="size-4" />
            </summary>
            <div className="absolute top-12 right-0 w-48 rounded-2xl border bg-popover/95 p-1.5 shadow-2xl backdrop-blur-xl">
              {[...NAV, ["Sign in", "/sign-in"] as [string, string]].map(([label, href]) => (
                <Link key={href} href={href} className="pixel-label block rounded-xl px-3 py-3 text-[17px] text-muted-foreground hover:bg-muted hover:text-foreground">{label}</Link>
              ))}
            </div>
          </details>
        </nav>
      </div>
    </header>
  );
}
