/** Small display helpers shared by the staff screens. */

export function department(code?: string | null): string {
  if (!code) return "Unassigned";
  const s = code.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function priority(level?: number | null, band?: string | null): string {
  if (level == null) return "Not set";
  const word = band ?? (level >= 9 ? "critical" : level >= 7 ? "high" : level >= 4 ? "normal" : "low");
  return `${level} ${word.charAt(0).toUpperCase()}${word.slice(1)}`;
}

export function waiting(iso?: string | null): string {
  if (!iso) return "";
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60_000));
  if (mins < 60) return `${mins} min`;
  const h = Math.floor(mins / 60);
  return h < 48 ? `${h} h ${mins % 60} min` : `${Math.floor(h / 24)} days`;
}

export const STATE_WORD: Record<string, string> = {
  RECEIVED: "New",
  PROCESSING: "Reading",
  AGGREGATED: "Reading",
  TRIAGED: "Checking",
  DIAGNOSED: "Drafting",
  AWAITING_APPROVAL: "Needs approval",
  IN_REVIEW: "In review",
  RESOLVED: "Answered",
  CLOSED: "Closed",
};
