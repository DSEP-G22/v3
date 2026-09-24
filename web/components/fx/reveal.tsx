"use client";

import { animate, stagger, utils } from "animejs";
import { useEffect, useRef, type ReactNode } from "react";

const still = () => matchMedia("(prefers-reduced-motion: reduce)").matches || navigator.webdriver;

/**
 * Fades its [data-reveal] descendants in with anime.js. `data-reveal="now"` rises in on load, in
 * document order; any other value waits until it scrolls into view. Content already on screen
 * when the page opens is left alone, so nothing that was visible disappears. Screenshots taken
 * by a test browser, and reduced motion, see everything at once.
 */
export function Reveal({ children, className }: { children: ReactNode; className?: string }) {
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = root.current!;
    const now = [...el.querySelectorAll<HTMLElement>('[data-reveal="now"]')];
    const later = [...el.querySelectorAll<HTMLElement>('[data-reveal]:not([data-reveal="now"])')]
      .filter((n) => n.getBoundingClientRect().top > innerHeight);
    if (still()) {
      utils.set(now, { opacity: 1 });
      return;
    }
    animate(now, { opacity: [0, 1], y: [18, 0], filter: ["blur(6px)", "blur(0px)"], duration: 900, delay: stagger(90, { start: 80 }), ease: "outExpo" });
    utils.set(later, { opacity: 0, y: 28 });
    const io = new IntersectionObserver((entries) => {
      const shown = entries.filter((e) => e.isIntersecting).map((e) => e.target as HTMLElement);
      if (!shown.length) return;
      shown.forEach((t) => io.unobserve(t));
      animate(shown, { opacity: 1, y: 0, duration: 1000, delay: stagger(80), ease: "outExpo" });
    }, { rootMargin: "0px 0px -8% 0px" });
    later.forEach((n) => io.observe(n));
    return () => io.disconnect();
  }, []);

  return <div ref={root} className={className}>{children}</div>;
}

const whole = (n: number) => Math.round(n).toLocaleString();

/** A number that counts up to its value the first time it is shown, and eases to each new one. */
export function Count({ value, format = whole }: { value: number; format?: (n: number) => string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const shown = useRef(0);

  useEffect(() => {
    const el = ref.current!;
    if (still()) {
      shown.current = value;
      el.textContent = format(value);
      return;
    }
    const state = { n: shown.current };
    const a = animate(state, { n: value, duration: 1200, ease: "outExpo",
      onUpdate: () => { shown.current = state.n; el.textContent = format(state.n); } });
    return () => { a.pause(); };
  }, [value, format]);

  return <span ref={ref} className="tabular-nums">{format(0)}</span>;
}
