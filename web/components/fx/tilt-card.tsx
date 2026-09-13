"use client";

import { useRef, type HTMLAttributes, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * A raised glass card: a gradient surface lit from the top left, a thin highlight on the top
 * edge, and a slight lean toward the pointer. Still for touch and reduced motion.
 */
export function TiltCard({ children, className, max = 4, ...rest }: HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
  max?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);

  function move(e: React.PointerEvent<HTMLDivElement>) {
    const el = ref.current;
    if (!el || e.pointerType !== "mouse" || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const r = el.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width;
    const py = (e.clientY - r.top) / r.height;
    el.style.setProperty("--rx", `${(0.5 - py) * max}deg`);
    el.style.setProperty("--ry", `${(px - 0.5) * max}deg`);
    el.style.setProperty("--mx", `${px * 100}%`);
    el.style.setProperty("--my", `${py * 100}%`);
  }

  function leave() {
    ref.current?.style.setProperty("--rx", "0deg");
    ref.current?.style.setProperty("--ry", "0deg");
  }

  return (
    <div ref={ref} onPointerMove={move} onPointerLeave={leave} {...rest}
         className={cn("surface-3d group relative isolate overflow-hidden rounded-2xl p-5 transition-[transform,box-shadow] duration-300 ease-out will-change-transform",
           "[transform:perspective(1000px)_rotateX(var(--rx,0deg))_rotateY(var(--ry,0deg))]", className)}>
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 opacity-0 transition-opacity duration-500 group-hover:opacity-100"
           style={{ background: "radial-gradient(420px circle at var(--mx,50%) var(--my,50%), color-mix(in oklch, var(--tilt-glow, var(--primary)) 16%, transparent), transparent 45%)" }} />
      {children}
    </div>
  );
}
