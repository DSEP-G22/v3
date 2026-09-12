// Server components only (reads GATEWAY_INTERNAL_URL).
export type Plan = {
  code: string;
  family: string;
  name: string;
  tier: string;
  technology: string;
  technology_display: string;
  price_lkr: number;
  price_display: string;
  speed_display: string;
  upload_display: string;
  data_cap_display: string;
  contract_display: string;
};

const GATEWAY = process.env.GATEWAY_INTERNAL_URL ?? "http://gateway:8000";

/** Public catalogue, cached for a minute. An unreachable gateway renders an empty state. */
export async function getPlans(): Promise<Plan[]> {
  try {
    const r = await fetch(`${GATEWAY}/api/public/plans`, { next: { revalidate: 60 } });
    if (!r.ok) return [];
    return (await r.json()).plans as Plan[];
  } catch {
    return [];
  }
}
