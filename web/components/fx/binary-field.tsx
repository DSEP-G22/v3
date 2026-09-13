"use client";

import { useEffect, useRef } from "react";

const CELL = 18;

/**
 * A field of 1s and 0s that keep flipping, seen through a slowly moving alpha map: a few soft
 * pools of visibility drift across it, and moving the pointer brightens the digits around it.
 * Over it, a very light blur grows outward from the pointer. Background only: it sits behind
 * the page, so content stays sharp. Still under reduced motion.
 */
export function BinaryField() {
  const canvas = useRef<HTMLCanvasElement>(null);
  const veil = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const c = canvas.current!;
    const ctx = c.getContext("2d")!;
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const family = getComputedStyle(document.documentElement).getPropertyValue("--font-geist-mono").trim() || "monospace";
    const ink = getComputedStyle(c).color;
    let w = 0;
    let h = 0;
    let cols = 0;
    let rows = 0;
    let bits = new Uint8Array(0);
    const m = { x: -9999, y: -9999, energy: 0 };

    function frame(t: number) {
      const s = t / 1000;
      const big = Math.max(w, h);
      // Three pools of visibility on slow Lissajous paths: the alpha map.
      const pools = [
        [w * (0.5 + 0.35 * Math.sin(s * 0.07)), h * (0.35 + 0.25 * Math.cos(s * 0.05)), big * 0.32],
        [w * (0.5 + 0.4 * Math.cos(s * 0.045 + 1)), h * (0.6 + 0.3 * Math.sin(s * 0.06 + 2)), big * 0.26],
        [w * (0.5 + 0.3 * Math.sin(s * 0.03 + 4)), h * (0.5 + 0.35 * Math.cos(s * 0.04 + 3)), big * 0.22],
      ];
      m.energy *= 0.95;
      const mr = 240;
      if (!still) for (let i = 0; i < bits.length / 90; i++) bits[(Math.random() * bits.length) | 0] ^= 1;
      ctx.clearRect(0, 0, w, h);
      for (let r = 0; r < rows; r++) {
        const y = r * CELL + CELL / 2;
        for (let q = 0; q < cols; q++) {
          const x = q * CELL + CELL / 2;
          let a = 0;
          for (const [px, py, pr] of pools) {
            const d = ((x - px) ** 2 + (y - py) ** 2) / (pr * pr);
            if (d < 1) a = Math.max(a, (1 - d) ** 2);
          }
          a *= 0.22;
          const md = ((x - m.x) ** 2 + (y - m.y) ** 2) / (mr * mr);
          if (md < 1) {
            a += (1 - md) * (0.05 + 0.25 * m.energy);
            if (md < 0.3 && Math.random() < 0.15 * m.energy) bits[r * cols + q] ^= 1;
          }
          if (a < 0.02) continue;
          ctx.globalAlpha = Math.min(0.6, a);
          ctx.fillText(bits[r * cols + q] ? "1" : "0", x, y);
        }
      }
    }

    function resize() {
      const dpr = Math.min(2, devicePixelRatio || 1);
      w = innerWidth;
      h = innerHeight;
      c.width = w * dpr;
      c.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.font = `500 11px ${family}`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = ink;
      cols = Math.ceil(w / CELL);
      rows = Math.ceil(h / CELL);
      bits = Uint8Array.from({ length: cols * rows }, () => (Math.random() < 0.5 ? 1 : 0));
      if (still) frame(0);
    }

    function move(e: PointerEvent) {
      m.energy = Math.min(1, m.energy + Math.hypot(e.clientX - m.x, e.clientY - m.y) / 400);
      m.x = e.clientX;
      m.y = e.clientY;
      veil.current?.style.setProperty("--mx", `${m.x}px`);
      veil.current?.style.setProperty("--my", `${m.y}px`);
    }

    let raf = 0;
    let last = 0;
    const loop = (t: number) => {
      raf = requestAnimationFrame(loop);
      if (t - last < 50) return; // about 20 frames a second is plenty for drifting digits
      last = t;
      frame(t);
    };

    resize();
    addEventListener("resize", resize);
    addEventListener("pointermove", move, { passive: true });
    if (!still) raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      removeEventListener("resize", resize);
      removeEventListener("pointermove", move);
    };
  }, []);

  const mask = "radial-gradient(circle at var(--mx, 50%) var(--my, 40%), transparent 0, transparent 140px, rgba(0,0,0,0.55) 520px, #000 1000px)";
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10">
      <canvas ref={canvas} className="size-full text-[oklch(0.82_0.1_305)]" />
      <div ref={veil} className="absolute inset-0 backdrop-blur-[1.2px]" style={{ maskImage: mask, WebkitMaskImage: mask }} />
    </div>
  );
}
