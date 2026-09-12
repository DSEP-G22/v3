"""Print the Neon round trip. Usage: uv run python scripts/neon-latency.py"""

from __future__ import annotations

import asyncio
import os
import re
import statistics
import time
from pathlib import Path

import asyncpg

from lanka_common.db import POOLER_KWARGS, parse_neon_key


def neon_key() -> str:
    if os.environ.get("NEON_KEY"):
        return os.environ["NEON_KEY"]
    env = Path(__file__).resolve().parents[1] / ".env"
    m = re.search(r"^\s*NEON_KEY\s*=\s*(.+)$", env.read_text(encoding="utf-8"), re.M)
    if not m:
        raise SystemExit("NEON_KEY not set in env or .env")
    return m.group(1)


async def main() -> None:
    dsn = parse_neon_key(neon_key())
    t = time.perf_counter()
    conn = await asyncpg.connect(dsn.pooled, **POOLER_KWARGS)
    connect_ms = (time.perf_counter() - t) * 1000
    rtts = []
    for _ in range(10):
        t = time.perf_counter()
        await conn.fetchval("SELECT 1")
        rtts.append((time.perf_counter() - t) * 1000)
    host = await conn.fetchval("SELECT inet_server_addr()::text")
    await conn.close()
    print(f"connect {connect_ms:.0f} ms, round trip p50 {statistics.median(rtts):.0f} ms, "
          f"min {min(rtts):.0f} ms (server {host})")


if __name__ == "__main__":
    asyncio.run(main())
