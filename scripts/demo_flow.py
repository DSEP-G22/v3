"""The headline case, end to end through :8080 (the Phase 6 checkpoint).

    uv run python scripts/demo_flow.py [--strict]

1. The operator suspends SUB-100002 (Ravi, who is also inside a seeded outage).
2. Ravi writes in Sinhala from the customer chat.
3. The agent finds the case in the console and reads the draft.
   --strict: the draft must cite both the payment and the outage.
4. The agent approves, and Ravi's conversation receives a Sinhala reply.
"""

from __future__ import annotations

import argparse
import re
import sys
import time

from lanka_http import customer, staff

SUB = "SUB-100002"
MESSAGE = "මගේ ඉන්ටර්නෙට් එක දවස් දෙකක ඉඳන් වැඩ කරන්නේ නෑ. මොකද වෙලා තියෙන්නේ?"
SINHALA = re.compile(r"[\u0D80-\u0DFF]")


def wait(what: str, fn, timeout: float = 120):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if (got := fn()) is not None:
            return got
        time.sleep(1.5)
    sys.exit(f"timed out waiting for {what}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="require the draft to cite payment and outage")
    args = ap.parse_args()

    operator, agent, ravi = staff("operator1"), staff("agent1"), customer("ravi")

    r = operator.post("/api/sim/scenarios/suspend_account", json={"subscriber_ref": SUB})
    print(f"1. suspend_account on {SUB}: {r.status_code}")
    r.raise_for_status()

    seen = {m["id"] for m in ravi.get("/api/app/conversation").raise_for_status().json()["messages"]}
    seen_cases = {c["id"] for c in agent.get("/api/console/cases", params={"tab": "all"}).raise_for_status()
                  .json()["cases"]}
    t0 = time.monotonic()
    ravi.post("/api/app/messages", data={"text": MESSAGE}).raise_for_status()
    print(f"2. Ravi wrote in Sinhala, acknowledged in {int((time.monotonic() - t0) * 1000)} ms")

    def find_case():
        cases = agent.get("/api/console/cases", params={"tab": "all"}).raise_for_status().json()["cases"]
        return next((c for c in cases if c.get("subscriber_id") == SUB and c["id"] not in seen_cases), None)

    case = wait("the case", find_case)

    def drafted():
        d = agent.get(f"/api/console/cases/{case['id']}").raise_for_status().json()
        return d if d["drafts"] else None

    detail = wait("a draft", drafted, timeout=180)
    draft = detail["drafts"][0]
    text = draft["text_en"]
    print(f"3. {case['id']} drafted ({draft['status']}) after {int(time.monotonic() - t0)} s:\n   {text}")
    cites_payment = bool(re.search(r"payment|pay|balance|overdue|bill", text, re.I))
    cites_outage = bool(re.search(r"outage|fault|repair|restor|engineer|network issue", text, re.I))
    print(f"   cites payment: {cites_payment}, cites outage: {cites_outage}")
    if args.strict and not (cites_payment and cites_outage):
        sys.exit("strict: the draft must cite both the payment and the outage")

    if draft["status"] != "released":
        agent.post(f"/api/console/cases/{case['id']}/approve", json={}).raise_for_status()
        print("4. agent approved")

    def replied():
        msgs = ravi.get("/api/app/conversation").raise_for_status().json()["messages"]
        return next((m for m in msgs if m["id"] not in seen and m.get("author_kind") in ("assistant", "agent")
                     and SINHALA.search(m.get("body") or "")), None)

    reply = wait("the Sinhala reply", replied)
    print(f"   Ravi received after {int(time.monotonic() - t0)} s:\n   {reply['body']}")
    print("demo flow OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
