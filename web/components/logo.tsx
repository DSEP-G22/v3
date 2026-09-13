import { useId } from "react";

import { cn } from "@/lib/utils";

/** The Lanka Link mark (the woven L), from /logo/Logo.svg. It is the logo's first 185 units. */
const MARK = "M154.74,131.53l25.72-50.14c.42-.83.57-1.77.4-2.68l-.57-3.21c-.77-3.74-3.16-10.83-4.79-15.39-.7-1.96-3.21-2.52-4.69-1.04l-3.97,3.97-42.67,42.67c-.58.58-1.52-.15-1.09-.85l39.22-64.81c.63-1.05.53-2.37-.26-3.3-1.86-2.2-5.21-6.11-6.73-7.63-.92-.92-2.97-2.78-4.6-4.23-1.23-1.1-3.1-1.04-4.27.13l-6.8,6.8-51.22,51.22c-.61.61-1.57-.16-1.12-.89L129.44,14.48c.9-1.45.33-3.36-1.22-4.08-.99-.46-1.94-.9-2.31-1.06-3.42-1.41-9.13-3.07-12.98-4.13-2.46-.68-5.09.03-6.89,1.83l-5.56,5.56-51.54,51.54c-.58.58-1.53-.12-1.13-.85L78.27,7.65c1.14-2.08-.63-4.57-2.96-4.15-4.57.81-11.28,2.31-17.78,4.88-2.79,1.1-5.56,2.27-8.26,3.63-8,4-15.55,9.28-22.34,15.78-.23.23-.45.43-.65.68-.26.2-.48.4-.71.65l-.74.74C11.8,43.2,3.62,59.52.34,76.58c-.27,1.4,1.42,2.31,2.42,1.31l22.58-22.58c.57-.57,1.51.11,1.13.83L.79,105.88c-.75,1.45-.97,3.11-.64,4.71l.41,1.94c.77,3.74,3.18,10.86,4.82,15.43.7,1.96,3.21,2.51,4.68,1.04l3.98-3.98,42.46-42.46c.6-.6,1.56.15,1.12.88l-38.52,63.63c-.95,1.57-.79,3.56.4,4.95,1.9,2.24,4.67,5.46,6.03,6.82l.03.03c.98.98,2.45,2.33,3.77,3.51,1.69,1.51,4.25,1.43,5.85-.17l6.04-6.04,55.74-55.74-45.54,73.21c-.85,1.37-.32,3.19,1.15,3.87,1.04.49,2.07.96,2.45,1.14,4.75,1.97,9.62,3.53,14.58,4.69,1.43.33,2.94-.12,3.98-1.16l6.81-6.79,51.52-51.52c.59-.59,1.55.13,1.15.86l-30.41,55.56c-1.13,2.07.61,4.54,2.94,4.18.6-.09,1.09-.17,1.34-.22h.03c5.7-1.02,11.32-2.61,16.8-4.74,2.81-1.08,5.59-2.33,8.29-3.72,8.4-4.26,16.26-9.88,23.27-16.91,13.47-13.47,21.87-30.07,25.2-47.44.27-1.4-1.41-2.31-2.42-1.31l-22.23,22.23c-.57.57-1.5-.11-1.13-.83ZM9.24,101.89l32.02-62.02c.34-.65.77-1.25,1.29-1.77l24.31-24.31c.58-.58,1.53.12,1.13.85L31.64,81.04c-.32.59-.73,1.13-1.21,1.61l-20.06,20.06c-.57.57-1.51-.11-1.13-.83ZM30.89,138.59l46.2-76.32c.3-.49.65-.94,1.05-1.34l37.2-37.19c.6-.6,1.55.16,1.1.88l-49.74,79.91c-.29.46-.62.88-1,1.27l-33.68,33.68c-.6.6-1.55-.15-1.12-.88ZM115.25,82.15l33.74-33.74c.59-.59,1.53.15,1.1.86l-46.32,76.54c-.3.49-.65.94-1.05,1.35l-37.18,37.18c-.59.59-1.53-.16-1.09-.86l49.8-80.05c.29-.46.62-.89,1.01-1.27ZM112.92,173.31l36.35-66.39c.32-.59.73-1.14,1.21-1.61l20.11-20.11c.56-.56,1.48.1,1.12.81l-31.63,61.65c-.34.66-.77,1.26-1.3,1.78l-24.72,24.72c-.59.59-1.54-.12-1.14-.85Z";

/** Logo height to width, and the share of the width the mark takes (for the sidebar reveal). */
export const LOGO_RATIO = 575.54 / 185.34;
export const MARK_RATIO = 185.34 / 185.34;

function Gradient({ id }: { id: string }) {
  return (
    <defs>
      {/* A soft top light: pale lilac falling to deep violet, one hue family. */}
      <linearGradient id={id} x1="0.2" y1="0" x2="0.8" y2="1">
        <stop offset="0" style={{ stopColor: "oklch(0.9 0.06 305)" }} />
        <stop offset="0.5" style={{ stopColor: "oklch(0.72 0.16 300)" }} />
        <stop offset="1" style={{ stopColor: "oklch(0.52 0.2 292)" }} />
      </linearGradient>
    </defs>
  );
}

/**
 * The full logo: the mark in a lilac to violet gradient (or `mono`, in the current text colour)
 * and "Lanka Link." set as in /logo/Logo.svg. The type is Cornero; add
 * public/fonts/Cornero.woff2 and it is used, otherwise the app font stands in.
 */
export function LogoMark({ className, style, mono }: { className?: string; style?: React.CSSProperties; mono?: boolean }) {
  const id = useId();
  return (
    <svg viewBox="0 0 575.54 185.34" role="img" aria-label="Lanka Link" className={cn("w-auto shrink-0", className)} style={style}>
      {!mono && <Gradient id={id} />}
      <path d={MARK} fill={mono ? "currentColor" : `url(#${id})`} />
      <g fill="currentColor" style={{ fontFamily: "Cornero, CorneroRegular, var(--font-app)" }}>
        <text x="218.83" y="156.89" fontSize="196.23">L</text>
        <text x="283.45" y="97.95" fontSize="81.52">anka</text>
        <text x="348.02" y="157.04" fontSize="81.52">ink.</text>
      </g>
    </svg>
  );
}

/** The mark alone, square. */
export function LogoIcon({ className, mono }: { className?: string; mono?: boolean }) {
  const id = useId();
  return (
    <svg viewBox="0 0 185.34 185.34" role="img" aria-label="Lanka Link" className={cn("size-8", className)}>
      {!mono && <Gradient id={id} />}
      <path d={MARK} fill={mono ? "currentColor" : `url(#${id})`} />
    </svg>
  );
}
