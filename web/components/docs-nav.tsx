"use client";

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

type Section = { id: string; title: string };

/** Which section is being read: the last one whose heading has passed the top third. */
function useActive(sections: Section[]) {
  const [active, setActive] = useState(sections[0]?.id);
  useEffect(() => {
    const onScroll = () => {
      let cur = sections[0]?.id;
      for (const s of sections) {
        const el = document.getElementById(s.id);
        if (el && el.getBoundingClientRect().top < innerHeight / 3) cur = s.id;
      }
      setActive(cur);
    };
    onScroll();
    addEventListener("scroll", onScroll, { passive: true });
    return () => removeEventListener("scroll", onScroll);
  }, [sections]);
  return active;
}

/** The table of contents: a rail beside the article on wide screens, a row of chips on a phone. */
export function DocsNav({ sections, variant }: { sections: Section[]; variant: "rail" | "chips" }) {
  const active = useActive(sections);
  const row = useRef<HTMLUListElement>(null);

  // Keep the current chip in view as the reader scrolls.
  useEffect(() => {
    if (variant !== "chips") return;
    const chip = row.current?.querySelector<HTMLElement>(`[data-id="${active}"]`);
    if (chip) row.current?.parentElement?.scrollTo({ left: chip.offsetLeft - 16, behavior: "smooth" });
  }, [active, variant]);

  if (variant === "chips") {
    return (
      <nav aria-label="On this page" className="snap-row -mx-4 overflow-x-auto px-4">
        <ul ref={row} className="flex w-max gap-1.5 py-2">
          {sections.map((s, i) => (
            <li key={s.id}>
              <a href={`#${s.id}`} data-id={s.id} aria-current={active === s.id ? "location" : undefined}
                 className={cn("flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm whitespace-nowrap transition-colors duration-300",
                   active === s.id ? "border-primary/40 bg-primary/10 text-foreground" : "border-transparent text-muted-foreground")}>
                <span className="font-pixel text-[15px] leading-none opacity-60">{String(i + 1).padStart(2, "0")}</span>{s.title}
              </a>
            </li>
          ))}
        </ul>
      </nav>
    );
  }
  return (
    <nav aria-label="On this page">
      <p className="pixel-label mb-3 text-[15px] text-muted-foreground">On this page</p>
      <ul className="space-y-0.5 border-l border-foreground/10 text-sm">
        {sections.map((s, i) => (
          <li key={s.id}>
            <a href={`#${s.id}`} aria-current={active === s.id ? "location" : undefined}
               className={cn("-ml-px flex items-center gap-2.5 border-l-2 py-1.5 pl-4 transition-[color,border-color] duration-300",
                 active === s.id ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
              <span className="font-pixel text-[15px] leading-none opacity-50">{String(i + 1).padStart(2, "0")}</span>{s.title}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
