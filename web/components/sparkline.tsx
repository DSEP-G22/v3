/** A tiny line for a table cell. Decorative: the number beside it carries the meaning. */
export function Sparkline({ values, max = 100, className = "h-6 w-24" }: { values: number[]; max?: number; className?: string }) {
  if (values.length < 2) return <span className={className} />;
  const points = values
    .map((v, i) => `${(i / (values.length - 1)) * 100},${30 - (Math.min(v, max) / max) * 28}`)
    .join(" ");
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" className={className} aria-hidden>
      <polyline points={points} fill="none" stroke="var(--chart-1)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
