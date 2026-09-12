"""The sim clock. Business is its single source; every tool and page uses sim time."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class ClockState:
    speed: float
    anchor_wall: datetime
    anchor_sim: datetime

    def now(self, wall: datetime | None = None) -> datetime:
        wall = wall or datetime.now(timezone.utc)
        return self.anchor_sim + (wall - self.anchor_wall) * self.speed

    def reanchor(self, *, speed: float | None = None, advance: timedelta = timedelta(0)) -> ClockState:
        """New state anchored at the current sim instant. Sim time never moves backwards."""
        wall = datetime.now(timezone.utc)
        return ClockState(
            speed=self.speed if speed is None else speed,
            anchor_wall=wall,
            anchor_sim=self.now(wall) + max(advance, timedelta(0)),
        )


if __name__ == "__main__":
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    c = ClockState(speed=60.0, anchor_wall=t0, anchor_sim=t0)
    assert c.now(t0 + timedelta(seconds=10)) == t0 + timedelta(minutes=10)
    paused = ClockState(speed=0.0, anchor_wall=t0, anchor_sim=t0)
    assert paused.now(t0 + timedelta(hours=5)) == t0
    assert c.reanchor(advance=timedelta(hours=-3)).anchor_sim >= c.now()
    print("clock ok")
