import Link from "next/link";

import { Brand } from "@/components/brand";
import { buttonVariants } from "@/components/ui/button";

export function SiteHeader() {
  return (
    <header className="border-b">
      <div className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between px-4">
        <Brand />
        <nav className="flex items-center gap-1 text-sm">
          <Link href="/plans" className={buttonVariants({ variant: "ghost" })}>
            Plans
          </Link>
          <Link href="/sign-in" className={buttonVariants({ variant: "ghost" })}>
            Sign in
          </Link>
          <Link href="/sign-up" className={buttonVariants()}>
            Get started
          </Link>
        </nav>
      </div>
    </header>
  );
}
