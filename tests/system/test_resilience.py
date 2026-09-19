"""Failover and recovery: a dependency dies, the product keeps answering.

These stop and start containers, so they only run when asked:

    LANKA_RESILIENCE=1 uv run pytest tests/system/test_resilience.py -q
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest
from conftest import case_for, until

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.environ.get("LANKA_RESILIENCE") != "1",
                                reason="destructive: set LANKA_RESILIENCE=1 to run")


def compose(*args):
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, capture_output=True, text=True, check=True)


@pytest.fixture
def stopped():
    """Stop a service for the length of one test, and always bring it back."""
    names = []

    def stop(name):
        names.append(name)
        compose("stop", name)
        return name

    yield stop
    for n in names:
        compose("start", n)
        time.sleep(5)


def test_a_dead_translation_service_still_answers_the_customer(stopped, ravi, agent):
    """mt_out is the last hop. With it down the draft has to come through in English, not vanish."""
    stopped("translation")
    text = f"My internet is down ({time.strftime('%H:%M:%S')})"
    ravi.post("/api/app/messages", data={"text": text}).raise_for_status()
    assert case_for(agent, text), "no case was opened while translation was down"
    detail = until(lambda: (d := case_for(agent, text, timeout=5)) and d.get("drafts") and d)
    assert detail, "the case never reached a draft"


def test_a_dead_audio_service_does_not_lose_the_ticket(stopped, ravi):
    stopped("audio")
    r = ravi.post("/api/app/messages", data={"text": f"Audio down check ({time.strftime('%H:%M:%S')})"})
    assert r.status_code == 201


def test_the_edge_reports_a_stopped_dependency(stopped, admin):
    stopped("grounding")
    time.sleep(3)
    m = admin.get("/api/admin/models/map").raise_for_status().json()
    assert m["services"]["grounding"]["status"] in ("down", "off")


def test_a_restarted_service_is_healthy_again(admin):
    compose("restart", "translation")
    ok = until(lambda: admin.get("/api/admin/models/map").json()["services"]["translation"]["status"] == "up",
               timeout=120, step=3)
    assert ok, "translation did not come back up"
