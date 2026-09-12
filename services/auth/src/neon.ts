// TypeScript twin of lanka_common/db.py: accepts a postgresql:// URL or Neon's `psql '...'`
// command, drops channel_binding, and derives the direct host by stripping -pooler.
export function parseNeonKey(raw: string): { pooled: string; direct: string } {
  const m = (raw ?? "").match(/postgres(?:ql)?:\/\/[^\s'"]+/);
  if (!m) throw new Error("NEON_KEY holds no postgres URL");
  const u = new URL(m[0].replace(/^postgres:/, "postgresql:"));
  u.searchParams.delete("channel_binding");
  const pooled = u.toString();
  u.hostname = u.hostname.replace("-pooler.", ".");
  return { pooled, direct: u.toString() };
}
