import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

const MASK = "linear-gradient(to top left, #000 10%, rgba(0,0,0,0.4) 40%, transparent 70%)";

/**
 * A card's icon as still background art: oversized, anchored in the bottom right corner and
 * fading out diagonally toward the top left. Place inside a `relative overflow-hidden` card.
 */
export function BentoIcon({ icon: Icon, className, tone = "text-primary", place = "-right-8 -bottom-10 size-44" }: {
  icon: LucideIcon;
  className?: string;
  /** Text colour class; separate so it replaces the default rather than competing with it. */
  tone?: string;
  /** Position and size classes, likewise. */
  place?: string;
}) {
  return (
    <Icon aria-hidden strokeWidth={1.1}
          className={cn("pointer-events-none absolute opacity-35", place, tone, className)}
          style={{ maskImage: MASK, WebkitMaskImage: MASK }} />
  );
}
