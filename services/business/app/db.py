"""Connection pools: Neon through the pooler (statement cache off), Timescale local."""

from __future__ import annotations

import os

import asyncpg

from lanka_common.db import POOLER_KWARGS, parse_neon_key

neon: asyncpg.Pool | None = None
ts: asyncpg.Pool | None = None


async def open_pools() -> None:
    global neon, ts
    # 16 so a snapshot's ~15 parallel queries cost one round trip, not fifteen.
    neon = await asyncpg.create_pool(
        parse_neon_key(os.environ["NEON_KEY"]).pooled, min_size=4, max_size=16, **POOLER_KWARGS
    )
    ts = await asyncpg.create_pool(os.environ["TIMESCALE_URL"], min_size=1, max_size=8)


async def close_pools() -> None:
    for pool in (neon, ts):
        if pool is not None:
            await pool.close()
