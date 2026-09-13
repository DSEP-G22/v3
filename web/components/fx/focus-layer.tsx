"use client";

import { XIcon } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { cn } from "@/lib/utils";

/** The component the user interacted with, as a viewport rectangle. */
export type Origin = { x: number; y: number; w: number; h: number };

/** The rectangle of the element that received the event (a card, a row, a graph node). */
export function originOf(e: { clientX?: number; clientY?: number; currentTarget?: EventTarget | null }): Origin {
  const el = e.currentTarget as Element | null;
  if (el && typeof el.getBoundingClientRect === "function") {
    const r = el.getBoundingClientRect();
    if (r.width || r.height) return { x: r.left, y: r.top, w: r.width, h: r.height };
  }
  return { x: e.clientX ?? innerWidth / 2, y: e.clientY ?? innerHeight / 2, w: 0, h: 0 };
}

const GAP = 12;

/**
 * A floating window that opens beside the component the user interacted with, never on top of
 * it. The content area behind softens with a light blur that grows away from that component;
 * the sidebar is never blurred. Escape, the close button or a click anywhere outside closes it.
 */
export function FocusLayer({ open, origin, onClose, title, subtitle, children, width = 380, className }: {
  open: boolean;
  origin: Origin | null;
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: ReactNode;
  width?: number;
  className?: string;
}) {
  const [shown, setShown] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [height, setHeight] = useState(0);
  const panel = useRef<HTMLDivElement>(null);
  const body = useRef<HTMLDivElement>(null);

  useEffect(() => setMounted(true), []);
  // Track the content's natural height, so the window is placed where all of it fits.
  useEffect(() => {
    const el = body.current;
    if (!open || !el) return;
    const ro = new ResizeObserver(() => setHeight(el.offsetHeight + 42));
    ro.observe(el);
    return () => ro.disconnect();
  }, [open, mounted, origin]);
  useEffect(() => {
    if (!open) {
      setShown(false);
      return;
    }
    const raf = requestAnimationFrame(() => setShown(true));
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    panel.current?.focus({ preventScroll: true });
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  if (!mounted || !open || !origin) return null;

  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const w = Math.min(width, vw - 32);
  const right = origin.x + origin.w;
  const bottom = origin.y + origin.h;

  // Beside the component if there is room, otherwise below (or above) it.
  let left: number;
  let top: number;
  let from: string;
  if (right + GAP + w <= vw - 16) {
    left = right + GAP;
    top = origin.y;
    from = "left top";
  } else if (origin.x - GAP - w >= 16) {
    left = origin.x - GAP - w;
    top = origin.y;
    from = "right top";
  } else {
    left = Math.min(Math.max(origin.x, 16), vw - w - 16);
    top = bottom + GAP + 240 <= vh ? bottom + GAP : Math.max(16, origin.y - GAP - 360);
    from = bottom + GAP + 240 <= vh ? "center top" : "center bottom";
  }
  // Slide up until the whole window is on screen; it only scrolls if taller than the viewport.
  top = Math.max(16, Math.min(top, vh - 16 - (height || 200)));

  // Blur only the content area: the staff sidebar stays sharp.
  const area = document.querySelector('[data-slot="sidebar-inset"]')?.getBoundingClientRect()
    ?? { left: 0, top: 0, width: vw, height: vh };
  const cx = origin.x + origin.w / 2 - area.left;
  const cy = origin.y + origin.h / 2 - area.top;
  const clear = Math.max(origin.w, origin.h) / 2 + 24;
  const mask = `radial-gradient(circle at ${cx}px ${cy}px, transparent ${clear}px, rgba(0,0,0,0.45) ${clear + 220}px, rgba(0,0,0,0.85) ${clear + 700}px)`;

  return createPortal(
    <div className="fixed inset-0 z-50" role="presentation">
      <div aria-hidden className="absolute inset-0" onClick={onClose} />
      <div aria-hidden
           className={cn("pointer-events-none fixed bg-background/10 backdrop-blur-[3px] transition-opacity duration-500 ease-out",
             shown ? "opacity-100" : "opacity-0")}
           style={{ left: area.left, top: area.top, width: area.width, height: area.height, maskImage: mask, WebkitMaskImage: mask }} />
      <div ref={panel} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title}
           className={cn("absolute overflow-y-auto rounded-2xl border border-white/10 bg-popover/90 p-5 text-popover-foreground shadow-2xl shadow-black/40 outline-none backdrop-blur-2xl",
             "transition-[opacity,transform] duration-300 ease-[cubic-bezier(0.32,0.72,0,1)]",
             shown ? "translate-y-0 scale-100 opacity-100" : "translate-y-1 scale-95 opacity-0", className)}
           style={{ left, top, width: w, maxHeight: vh - top - 16, transformOrigin: from }}>
        <div ref={body}>
          <div className="mb-4 flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h2 className="font-semibold leading-tight">{title}</h2>
              {subtitle && <p className="mt-0.5 text-sm text-muted-foreground">{subtitle}</p>}
            </div>
            <button type="button" onClick={onClose} aria-label="Close"
                    className="grid size-7 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground">
              <XIcon className="size-4" />
            </button>
          </div>
          {children}
        </div>
      </div>
    </div>,
    document.body,
  );
}
