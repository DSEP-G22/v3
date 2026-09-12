"""Seed one-shot: create org tables, write the deterministic genesis, backfill telemetry.

Idempotent: a world that already holds SUB-100001 is left alone (reset is a sim control,
not a boot side effect). Rows go in with COPY, one round trip per table, because Neon may be
hundreds of milliseconds away.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, time, timezone
from typing import Any

import asyncpg
from sqlalchemy import JSON

from app.models import OrgBase, SimClock
from app.seed import SandboxSeeder, SeedClock
from app.world import COLOMBO, Metric, Usage
from lanka_common.db import parse_neon_key


def _value(obj: Any, column) -> Any:
    value = getattr(obj, column.key)
    if value is None and column.default is not None and not callable(column.default.arg):
        value = column.default.arg
    if value is not None and isinstance(column.type, JSON):
        value = json.dumps(value)
    return value


async def _create_tables(direct_dsn: str) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(direct_dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    async with engine.begin() as conn:
        await conn.run_sync(OrgBase.metadata.create_all)
    await engine.dispose()


async def write_org(conn: asyncpg.Connection, rows: list[Any]) -> int:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        if hasattr(row, "__table__"):
            grouped[row.__table__.name].append(row)
    written = 0
    for table in OrgBase.metadata.sorted_tables:
        objs = grouped.pop(table.name, [])
        if not objs:
            continue
        cols = list(table.columns)
        await conn.copy_records_to_table(
            table.name,
            schema_name=table.schema,
            columns=[c.name for c in cols],
            records=[tuple(_value(o, c) for c in cols) for o in objs],
        )
        written += len(objs)
    assert not grouped, f"rows for unknown tables: {sorted(grouped)}"
    return written


async def write_telemetry(ts: asyncpg.Connection, rows: list[Any]) -> tuple[int, int]:
    metrics = [
        (m.sampled_at, m.circuit_id, m.rx_power_dbm, m.tx_power_dbm, m.snr_db, m.sync_down_mbps,
         m.sync_up_mbps, m.latency_ms, m.jitter_ms, m.packet_loss_pct, m.crc_errors, m.resyncs)
        for m in rows
        if isinstance(m, Metric)
    ]
    # Daily history lands at Colombo noon so usage_1d buckets it into the right local day.
    usage = [
        (datetime.combine(u.usage_date, time(12), tzinfo=COLOMBO), u.subscription_id, u.down_gb, u.up_gb)
        for u in rows
        if isinstance(u, Usage)
    ]
    await ts.copy_records_to_table(
        "line_metric",
        columns=["time", "circuit_id", "rx_power_dbm", "tx_power_dbm", "snr_db", "sync_down_mbps",
                 "sync_up_mbps", "latency_ms", "jitter_ms", "packet_loss_pct", "crc_errors", "resyncs"],
        records=metrics,
    )
    await ts.copy_records_to_table(
        "usage_sample", columns=["time", "subscription_id", "down_gb", "up_gb"], records=usage
    )
    return len(metrics), len(usage)


async def main() -> None:
    direct = parse_neon_key(os.environ["NEON_KEY"]).direct
    await _create_tables(direct)

    conn = await asyncpg.connect(direct, timeout=30)
    try:
        if await conn.fetchval("SELECT 1 FROM org.subscriber WHERE id = 'SUB-100001'"):
            print("genesis: world already seeded, nothing to do", file=sys.stderr)
            return
        now = datetime.now(timezone.utc)
        seeder = SandboxSeeder(SeedClock(now))
        seeder.run(subscriber_count=int(os.environ.get("SEED_SUBSCRIBERS", "400")))
        seeder.rows.append(SimClock(id=1, speed=1.0, anchor_wall=now, anchor_sim=now))

        ts = await asyncpg.connect(os.environ["TIMESCALE_URL"], timeout=30)
        try:
            async with ts.transaction():
                n_metric, n_usage = await write_telemetry(ts, seeder.rows)
        finally:
            await ts.close()
        async with conn.transaction():
            n_org = await write_org(conn, seeder.rows)
    finally:
        await conn.close()
    print(f"genesis: {n_org} org rows, {n_metric} line samples, {n_usage} usage days", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
