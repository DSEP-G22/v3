import Link from "next/link";

import { Brand } from "@/components/brand";
import { buttonVariants } from "@/components/ui/button";

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-30 border-b border-white/40 bg-background/70 backdrop-blur-xl">
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between px-4">
        <Brand />
        <nav className="flex items-center gap-1 text-sm" aria-label="Site">
          <Link href="/plans" className={buttonVariants({ variant: "ghost", className: "hidden sm:inline-flex" })}>
            Plans
          </Link>
          <Link href="/docs" className={buttonVariants({ variant: "ghost", className: "hidden sm:inline-flex" })}>
            How it works
          </Link>
          <Link href="/sign-in" className={buttonVariants({ variant: "ghost" })}>
            Sign in
          </Link>
          <Link href="/sign-up" className={buttonVariants({ className: "shadow-md shadow-primary/25" })}>
            Get started
          </Link>
        </nav>
      </div>
    </header>
  );
}
