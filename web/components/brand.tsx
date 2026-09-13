import Link from "next/link";

import { LogoIcon, LogoMark } from "@/components/logo";
import { cn } from "@/lib/utils";

/** The logo as a home link. `compact` shows the mark alone. */
export function Brand({ href = "/", compact = false, className }: { href?: string; compact?: boolean; className?: string }) {
  return (
    <Link href={href} aria-label="Lanka Link home" className={cn("flex items-center text-foreground", className)}>
      {compact ? <LogoIcon className="size-8" /> : <LogoMark className="h-8" />}
    </Link>
  );
}
