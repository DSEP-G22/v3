import { cn } from "@/lib/utils";

const FADE = "linear-gradient(to bottom, #000 35%, transparent)";

/**
 * Slow drifting violet, gold and lilac blobs behind a section, fading out toward the bottom so
 * it never ends in a hard edge. Pure CSS, still under reduced motion.
 */
export function FluidGradient({ className }: { className?: string }) {
  return (
    <div aria-hidden className={cn("pointer-events-none absolute inset-x-0 top-0 -z-10 overflow-hidden", className)}
         style={{ maskImage: FADE, WebkitMaskImage: FADE }}>
      <div className="absolute -top-1/3 -left-1/4 size-[70vmax] rounded-full bg-[radial-gradient(circle_at_center,var(--primary),transparent_62%)] opacity-35 blur-3xl animate-drift" />
      <div className="absolute -top-1/4 -right-1/4 size-[58vmax] rounded-full bg-[radial-gradient(circle_at_center,var(--gold),transparent_62%)] opacity-40 blur-3xl animate-drift-slow" />
      <div className="absolute -bottom-1/2 left-1/5 size-[64vmax] rounded-full bg-[radial-gradient(circle_at_center,var(--lilac),transparent_62%)] opacity-70 blur-3xl animate-drift" />
    </div>
  );
}
