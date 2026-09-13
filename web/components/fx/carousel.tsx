"use client";

import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react";
import { Children, useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Native scroll-snap carousel: swipe, trackpad, keyboard and buttons all work, no library.
 * Autoplay (ms) pauses on hover and focus, and never runs under reduced motion.
 */
export function Carousel({ children, label, autoplay = 0, itemClassName, className }: {
  children: ReactNode;
  label: string;
  autoplay?: number;
  itemClassName?: string;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(0);
  const [paused, setPaused] = useState(false);
  const items = Children.toArray(children);

  const go = useCallback((index: number) => {
    const el = ref.current;
    const child = el?.children[index] as HTMLElement | undefined;
    if (el && child) el.scrollTo({ left: child.offsetLeft - el.offsetLeft, behavior: "smooth" });
  }, []);

  const onScroll = () => {
    const el = ref.current;
    if (!el) return;
    const widths = Array.from(el.children).map((c) => (c as HTMLElement).offsetLeft - el.offsetLeft);
    const i = widths.reduce((best, left, idx) => (Math.abs(left - el.scrollLeft) < Math.abs(widths[best] - el.scrollLeft) ? idx : best), 0);
    setActive(i);
  };

  useEffect(() => {
    if (!autoplay || paused || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const t = setInterval(() => go((active + 1) % items.length), autoplay);
    return () => clearInterval(t);
  }, [autoplay, paused, active, items.length, go]);

  return (
    <div aria-roledescription="carousel" aria-label={label} className={cn("relative", className)}
         onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}
         onFocus={() => setPaused(true)} onBlur={() => setPaused(false)}>
      <div ref={ref} onScroll={onScroll} className="snap-row -mx-1 flex gap-4 overflow-x-auto px-1 pb-2">
        {items.map((child, i) => (
          <div key={i} role="group" aria-roledescription="slide" aria-label={`${i + 1} of ${items.length}`}
               className={cn("shrink-0 basis-[85%] sm:basis-[48%] lg:basis-[32%]", itemClassName)}>
            {child}
          </div>
        ))}
      </div>
      <div className="mt-3 flex items-center justify-between gap-4">
        <div className="flex gap-1.5" aria-hidden>
          {items.map((_, i) => (
            <span key={i} className={cn("h-1.5 rounded-full bg-primary/25 transition-all", i === active ? "w-6 bg-primary" : "w-1.5")} />
          ))}
        </div>
        <div className="flex gap-1">
          <Button size="icon-sm" variant="outline" aria-label="Previous" onClick={() => go(Math.max(0, active - 1))}>
            <ChevronLeftIcon />
          </Button>
          <Button size="icon-sm" variant="outline" aria-label="Next" onClick={() => go(Math.min(items.length - 1, active + 1))}>
            <ChevronRightIcon />
          </Button>
        </div>
      </div>
    </div>
  );
}
