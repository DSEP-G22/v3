// k6: read-only browsing, safe against production (no ticket, no payment, no write).
// Ramps to 20 virtual users: public pages and the catalogue, then a signed-in customer's reads.
//   SCRIPT=load/browse.js LANKA_URL=https://... bash scripts/load.sh
import http from "k6/http";
import { check, sleep } from "k6";

const BASE = __ENV.BASE || "http://localhost:8080";

export const options = {
  scenarios: {
    browse: {
      executor: "ramping-vus",
      stages: [
        { duration: "1m", target: 20 },
        { duration: "3m", target: 20 },
        { duration: "1m", target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    "http_req_duration{kind:page}": ["p(95)<2000"],
    "http_req_duration{kind:api}": ["p(95)<1500"],
  },
};

export function setup() {
  // One sign-in for the whole run: sign-in is rate limited per address, as it should be.
  const r = http.post(`${BASE}/api/auth/sign-in/email`,
    JSON.stringify({ email: __ENV.EMAIL, password: __ENV.PASSWORD }),
    { headers: { "content-type": "application/json", origin: BASE } });
  check(r, { "signed in": (x) => x.status === 200 });
  return { token: http.get(`${BASE}/api/auth/token`).json("token") };
}

export default function ({ token }) {
  const auth = { headers: { authorization: `Bearer ${token}` } };
  const page = (path) => http.get(`${BASE}${path}`, { tags: { kind: "page", name: path } });
  const api = (path, params = {}) => http.get(`${BASE}${path}`, { ...params, tags: { kind: "api", name: path } });

  check(page("/"), { "landing 200": (r) => r.status === 200 });
  check(api("/api/public/plans"), { "plans 200": (r) => r.status === 200 });
  sleep(1);
  check(page("/plans"), { "plans page 200": (r) => r.status === 200 });
  check(api("/api/app/overview", auth), { "overview 200": (r) => r.status === 200 });
  check(api("/api/app/billing", auth), { "billing 200": (r) => r.status === 200 });
  check(api("/api/app/tickets", auth), { "tickets 200": (r) => r.status === 200 });
  sleep(2);
}
