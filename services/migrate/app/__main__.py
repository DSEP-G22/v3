"""One-shot migration: Neon schemas over the direct host, then the Timescale schema.

Service tables are created by their owners (business via the seed one-shot, auth at boot).
ponytail: idempotent DDL, not Alembic; add Alembic per service once a schema needs a real
upgrade path.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import asyncpg

from lanka_common.db import parse_neon_key

SCHEMAS = ("gw", "inquiry", "cases", "grounding", "response", "control", "knowledge", "org", "payments")
TIMESCALE_SQL = Path(__file__).with_name("timescale.sql")


async def main() -> None:
    conn = await asyncpg.connect(parse_neon_key(os.environ["NEON_KEY"]).direct, timeout=30)
    try:
        for schema in SCHEMAS:
            await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    finally:
        await conn.close()
    print(f"migrate: {len(SCHEMAS)} Neon schemas ready", file=sys.stderr)

    if url := os.environ.get("TIMESCALE_URL"):
        ts = await asyncpg.connect(url, timeout=30)
        try:
            await ts.execute(TIMESCALE_SQL.read_text(encoding="utf-8"))
        finally:
            await ts.close()
        print("migrate: timescale schema ready", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
