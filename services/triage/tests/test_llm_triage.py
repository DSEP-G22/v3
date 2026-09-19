"""The llm_triage binding: an LLM reading when it answers, the TriageModel when it does not."""

from __future__ import annotations

import asyncio

from app import main


class _Answers:
    name, model = "groq", "fake"

    async def generate_json(self, prompt, schema, system=None):
        return schema(level=8, department="network_operations", reason="Their service is down.")


class _Slow(_Answers):
    async def generate_json(self, prompt, schema, system=None):
        await asyncio.sleep(5)


def _run(llm, monkeypatch):
    async def bound():
        return llm

    monkeypatch.setattr(main, "_llm", bound)
    monkeypatch.setattr(main, "LLM_TIMEOUT_S", 0.1)
    return asyncio.run(main.run(main.TriageIn(fused_text="no internet since morning, please fix")))["customer_priority"]


def test_the_llm_reading_is_used_when_it_answers(monkeypatch):
    cp = _run(_Answers(), monkeypatch)
    assert (cp["source"], cp["level"], cp["band"], cp["department_hint"]) == ("groq", 8, "high", "network_operations")


def test_a_slow_llm_falls_back_to_the_model_and_says_so(monkeypatch):
    cp = _run(_Slow(), monkeypatch)
    assert cp["source"] in ("model", "rules")
    assert cp["reasons"][-1]["signal"] == "fallback"


def test_no_llm_bound_means_the_model(monkeypatch):
    cp = _run(None, monkeypatch)
    assert cp["source"] in ("model", "rules")
    assert all(r["signal"] != "fallback" for r in cp["reasons"])
