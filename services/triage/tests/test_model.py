"""The TriageModel head runs from numpy weights and stays consistent with the one to ten scale."""

import numpy as np
import pytest

from app import model


@pytest.fixture(scope="module")
def triage_model():
    m = model.load()
    assert m is not None, "services/triage/models/ is missing; run ml/export_triage.py"
    # Offline: a fixed vector stands in for MiniLM so the test needs no model download.
    m.embed = lambda text: np.full(384, 1 / np.sqrt(384), dtype=np.float32)
    return m


def test_features_are_the_eighteen_the_model_was_trained_on(triage_model):
    feats = model.features("My internet is not working again!! please help", segment="enterprise")
    assert list(feats) == triage_model.signal_names
    assert feats["service_down"] == 1.0 and feats["repeat_contact"] == 1.0 and feats["polite"] == 1.0
    assert feats["customer_segment_score"] == 1.0


def test_prediction_band_and_level_agree(triage_model):
    out = triage_model.predict("no internet since morning, router red light", segment="consumer")
    lo, hi = model.BAND_RANGE[out["band"]]
    assert lo <= out["level"] <= hi
    assert 0 <= out["score"] <= 100 and 0 < out["confidence"] <= 1
    assert out["source"] == "model" and out["model_version"]


def test_weights_match_the_input_width(triage_model):
    assert triage_model.w["w1"].shape[1] == 384 + len(triage_model.signal_names)
