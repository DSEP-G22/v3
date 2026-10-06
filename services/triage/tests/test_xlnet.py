"""The xlnet-priority-int8 head: XLNet's band, the TriageModel's level clamped into it."""

from __future__ import annotations

import asyncio

import pytest

from app import main, xlnet


def _run(monkeypatch, head):
    async def bound():
        return None

    monkeypatch.setattr(main, "_llm", bound)
    monkeypatch.setitem(main.state, "head", head)
    return asyncio.run(main.run(main.TriageIn(fused_text="hi, what plans do you have for a new connection?")))["customer_priority"]


def test_xlnet_band_wins_and_the_level_moves_into_it(monkeypatch):
    monkeypatch.setattr(xlnet, "band", lambda text: ("critical", 0.91))
    cp = _run(monkeypatch, xlnet.VERSION)
    assert (cp["band"], cp["model_version"], cp["confidence"]) == ("critical", xlnet.VERSION, 0.91)
    assert 9 <= cp["level"] <= 10


def test_broken_xlnet_falls_back_to_the_triage_model(monkeypatch):
    def broken(text):
        raise FileNotFoundError(text)

    monkeypatch.setattr(xlnet, "band", broken)
    cp = _run(monkeypatch, xlnet.VERSION)
    assert cp["model_version"] != xlnet.VERSION
    assert cp["reasons"][-1]["signal"] == "fallback"


def test_default_head_never_touches_xlnet(monkeypatch):
    monkeypatch.setattr(xlnet, "band", lambda text: pytest.fail("XLNet ran without being bound"))
    assert _run(monkeypatch, "triage_multitask")["model_version"] != xlnet.VERSION


@pytest.mark.skipif(not (xlnet.DIR / "model.int8.onnx").exists(), reason="XLNet weights are baked into the image only")
def test_real_xlnet_reads_an_outage_as_urgent():
    assert xlnet.band("Our whole office has had no internet since yesterday, the business is losing money")[0] in ("critical", "high")
    assert xlnet.band("Hi, which payment methods do you accept?")[0] in ("low", "normal")
