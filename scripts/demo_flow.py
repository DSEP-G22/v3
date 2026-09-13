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
    print(f"1. suspend_account on {SUB}: {r.status_code}" + (" (already suspended)" if r.status_code == 422 else ""))
    if r.status_code != 422:
        r.raise_for_status()

    seen = {m["id"] for m in ravi.get("/api/app/conversation").raise_for_status().json()["messages"]}
    # A message on an open case adds a revision instead of a new case, so match on both.
    seen_cases = {(c["id"], c["revision"]) for c in agent.get("/api/console/cases", params={"tab": "all"})
                  .raise_for_status().json()["cases"]}
    t0 = time.monotonic()
    # The time keeps reruns clear of inquiry's 10 minute duplicate guard.
    ravi.post("/api/app/messages", data={"text": f"{MESSAGE} ({time.strftime('%H:%M:%S')})"}).raise_for_status()
    print(f"2. Ravi wrote in Sinhala, acknowledged in {int((time.monotonic() - t0) * 1000)} ms")

    def find_case():
        cases = agent.get("/api/console/cases", params={"tab": "all"}).raise_for_status().json()["cases"]
        return next((c for c in cases if c.get("subscriber_id") == SUB and (c["id"], c["revision"]) not in seen_cases),
                    None)

    case = wait("the case", find_case)

    def drafted():
        d = agent.get(f"/api/console/cases/{case['id']}").raise_for_status().json()
        # Earlier revisions keep their own drafts; only this revision's draft counts.
        return next((dr for dr in d["drafts"] if dr.get("revision") == d["case"]["revision"]), None)

    draft = wait("a draft", drafted, timeout=180)
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
        return next((m for m in msgs if m["id"] not in seen and m.get("author_kind") in ("assistant", "agent")), None)

    reply = wait("the reply", replied)
    in_sinhala = bool(SINHALA.search(reply.get("body") or ""))
    print(f"   Ravi received after {int(time.monotonic() - t0)} s ({'Sinhala' if in_sinhala else 'not Sinhala'}):\n"
          f"   {reply['body']}")
    if args.strict and not in_sinhala:
        sys.exit("strict: the reply must be in Sinhala (needs the translation service, not the CI profile)")
    print("demo flow OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
