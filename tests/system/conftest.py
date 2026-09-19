"""System tests: black box, through the edge on :8080, against the composed stack.

These are the tests that cannot be written against a function call: role gates, tenant
isolation, the pipeline end to end, response budgets. They skip themselves when nothing is
listening on the edge, so `uv run pytest` stays green on a machine without Docker.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from lanka_http import BASE, customer, staff  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def stack() -> None:
    try:
        httpx.get(f"{BASE}/healthz", timeout=3).raise_for_status()
    except Exception:  # noqa: BLE001 - any failure to reach the edge means the same thing
        pytest.skip(f"no stack on {BASE}: run scripts/up.sh")


@pytest.fixture(scope="session")
def anon() -> httpx.Client:
    return httpx.Client(base_url=BASE, timeout=30)


@pytest.fixture(scope="session")
def agent() -> httpx.Client:
    return staff("agent1")


@pytest.fixture(scope="session")
def admin() -> httpx.Client:
    return staff("admin1")


@pytest.fixture(scope="session")
def operator() -> httpx.Client:
    return staff("operator1")


@pytest.fixture(scope="session")
def amara() -> httpx.Client:
    return customer("amara")


@pytest.fixture(scope="session")
def ravi() -> httpx.Client:
    return customer("ravi")


def until(fn, timeout: float = 150, step: float = 2.0):
    """Poll until fn returns something truthy. The pipeline is asynchronous by design."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if (got := fn()):
            return got
        time.sleep(step)
    return None


def case_for(agent, text: str, timeout: float = 150):
    """The case this message produced, found by the message itself. Matching on "any new case"
    picks up another persona's case, or a revision bump on an open one."""
    def find():
        for c in agent.get("/api/console/cases", params={"tab": "all"}).json()["cases"][:20]:
            d = agent.get(f"/api/console/cases/{c['id']}").json()
            msgs = (d.get("conversation") or {}).get("messages") or []
            if any(text in (m.get("body") or "") for m in msgs):
                return d
        return None
    return until(find, timeout)
