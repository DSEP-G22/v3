"""Performance profiling: the budgets from the plan, measured through the edge.

Two numbers matter to a user: the acknowledgement they wait for with the send button pressed,
and the page they opened. Both are asserted here; sustained load is scripts/load.sh.
"""

from __future__ import annotations

import statistics
import time

import pytest

#: (path, warm p50 budget in ms). Generous against a database in another region; they are
#: regression fences, not targets.
PAGES = [
    ("/api/me", 800),
    ("/api/app/overview", 1500),
    ("/api/app/billing", 800),
    ("/api/app/plan", 800),
    ("/api/app/usage", 1200),
    ("/api/app/notices", 800),
]


def _times(client, path, n=5):
    out = []
    for _ in range(n):
        t = time.perf_counter()
        client.get(path).raise_for_status()
        out.append((time.perf_counter() - t) * 1000)
    return out


@pytest.mark.parametrize("path,budget", PAGES)
def test_a_warm_account_screen_is_within_budget(amara, path, budget):
    amara.get(path)  # warm the connection and the query plan
    p50 = statistics.median(_times(amara, path))
    assert p50 < budget, f"{path} p50 {p50:.0f} ms over {budget} ms"


def test_the_acknowledgement_is_immediate(ravi):
    """The customer waits for this one. The pipeline runs behind it."""
    t = time.perf_counter()
    ravi.post("/api/app/messages", data={"text": f"Latency probe {time.strftime('%H:%M:%S')}"}).raise_for_status()
    ms = (time.perf_counter() - t) * 1000
    assert ms < 2500, f"acknowledgement took {ms:.0f} ms"


def test_the_console_queue_loads_within_budget(agent):
    agent.get("/api/console/cases", params={"tab": "needs_approval"})
    p50 = statistics.median(_times(agent, "/api/console/cases?tab=needs_approval"))
    assert p50 < 3000, f"console queue p50 {p50:.0f} ms"
