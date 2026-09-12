// k6: customer inquiry acknowledgement latency through :8080 (stub LLM profile).
//   k6 run -e BASE=http://localhost:8080 -e EMAIL=amara@customers.lankalink.example.lk -e PASSWORD=... load/ack.js
import http from "k6/http";
import { check } from "k6";

const BASE = __ENV.BASE || "http://localhost:8080";

export const options = {
  scenarios: {
    chat: { executor: "constant-arrival-rate", rate: 5, timeUnit: "1s", duration: "1m", preAllocatedVUs: 20 },
  },
  thresholds: {
    // Plan section 4: the ack is a gateway plus inquiry write, no pipeline work on the request path.
    "http_req_duration{name:ack}": ["p(50)<300", "p(95)<800"],
    "http_req_duration{name:overview}": ["p(50)<250"],
    http_req_failed: ["rate<0.01"],
  },
};

export function setup() {
  const jar = http.cookieJar();
  const r = http.post(`${BASE}/api/auth/sign-in/email`,
    JSON.stringify({ email: __ENV.EMAIL, password: __ENV.PASSWORD }),
    { headers: { "content-type": "application/json", origin: BASE } });
  check(r, { "signed in": (x) => x.status === 200 });
  const t = http.get(`${BASE}/api/auth/token`, { jar });
  return { token: t.json("token") };
}

export default function ({ token }) {
  const auth = { authorization: `Bearer ${token}` };
  const ack = http.post(`${BASE}/api/app/messages`, { text: "my internet is slow in the evenings" },
    { headers: auth, tags: { name: "ack" } });
  check(ack, { acknowledged: (x) => x.status === 201 });
  const home = http.get(`${BASE}/api/app/overview`, { headers: auth, tags: { name: "overview" } });
  check(home, { home: (x) => x.status === 200 });
}
