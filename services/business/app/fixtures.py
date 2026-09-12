"""Dump every tool's result for the eight personas as JSON (python -m app.fixtures OUT).

This is the contract fixture other services test against (grounding, response): real
payloads from the real tools, without those services importing business code.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from app.seed import SandboxSeeder, SeedClock
from app.tools import available_tools, call
from app.world import build, resolve

NOW = datetime(2026, 9, 11, 6, 30, tzinfo=timezone.utc)
PERSONAS = [f"SUB-10000{i}" for i in range(1, 9)]


def dump() -> dict:
    seeder = SandboxSeeder(SeedClock(NOW))
    seeder.run(subscriber_count=24)
    world, snaps = build(seeder.rows)
    out: dict = {"sim_now": NOW.isoformat(), "subscribers": {}, "led": {}}
    for ref in PERSONAS:
        snap = resolve(snaps, ref)
        out["subscribers"][ref] = {
            name: call(name, snap, world, NOW, subscriber_ref=ref)
            for name in available_tools() if name != "get_device_led_semantics"
        }
    for model in world.device_models:
        out["led"][model] = {
            colour: call("get_device_led_semantics", None, world, NOW, model=model, colour=colour)
            for colour in ("red", "amber", "green", "off")
        }
    return out


if __name__ == "__main__":
    with open(sys.argv[1], "w", encoding="utf-8") as fh:
        json.dump(dump(), fh, indent=1, default=str, ensure_ascii=False)
    print(f"wrote {sys.argv[1]}")
