"use client";

import { useEffect, useRef } from "react";

/**
 * A soft violet to lilac trail that follows the pointer. Decorative only: off for touch,
 * off under reduced motion, paused while the tab is hidden, never intercepts a click.
 */
export function FluidCursor() {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    if (matchMedia("(pointer: coarse)").matches || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let w = 0;
    let h = 0;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const resize = () => {
      w = window.innerWidth;
      h = window.innerHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();

    const N = 24;
    const pts = Array.from({ length: N }, () => ({ x: w / 2, y: h / 2 }));
    const mouse = { x: w / 2, y: h / 2, seen: false, still: 0 };
    const violet = [139, 92, 246];
    const lilac = [214, 196, 250];

    const move = (e: PointerEvent) => {
      mouse.x = e.clientX;
      mouse.y = e.clientY;
      mouse.seen = true;
      mouse.still = 0;
    };
    window.addEventListener("pointermove", move, { passive: true });
    window.addEventListener("resize", resize);

    let raf = 0;
    const frame = () => {
      raf = requestAnimationFrame(frame);
      if (document.hidden || !mouse.seen) return;
      mouse.still += 1;
      ctx.clearRect(0, 0, w, h);
      if (mouse.still > 90) return; // fade out once the pointer rests
      let { x, y } = mouse;
      for (const p of pts) {
        p.x += (x - p.x) * 0.32;
        p.y += (y - p.y) * 0.32;
        x = p.x;
        y = p.y;
      }
      const fade = Math.max(0, 1 - mouse.still / 90);
      pts.forEach((p, i) => {
        const t = 1 - i / N;
        const r = 34 * t + 6;
        const c = violet.map((v, k) => Math.round(v + (lilac[k] - v) * (i / N)));
        const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, r);
        g.addColorStop(0, `rgba(${c.join(",")},${0.22 * t * fade})`);
        g.addColorStop(1, `rgba(${c.join(",")},0)`);
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
        ctx.fill();
      });
    };
    frame();

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("resize", resize);
    };
  }, []);

  return <canvas ref={ref} aria-hidden className="pointer-events-none fixed inset-0 z-40" />;
}
