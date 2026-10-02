import time

from app import main
from app.translate import PassthroughTranslator


def _bind(monkeypatch, impl, loader):
    monkeypatch.setattr(main, "backends", {"nllb": PassthroughTranslator()})
    monkeypatch.setattr(main, "_bound", {"mt_in": (time.monotonic(), impl)})
    monkeypatch.setattr(main, "LAZY", {"nllb-1.3b": loader})


def test_large_model_loads_on_first_pick(monkeypatch):
    big = PassthroughTranslator()
    _bind(monkeypatch, "nllb-1.3b", lambda: big)
    assert main._impl("mt_in") == "nllb-1.3b" and main.backends["nllb-1.3b"] is big


def test_missing_or_broken_large_model_falls_back_to_600m(monkeypatch):
    _bind(monkeypatch, "nllb-1.3b", lambda: None)
    assert main._impl("mt_in") == "nllb"

    def boom():
        raise RuntimeError("bad weights")

    _bind(monkeypatch, "nllb-1.3b", boom)
    assert main._impl("mt_in") == "nllb"
