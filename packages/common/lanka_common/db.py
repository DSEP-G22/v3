"""NEON_KEY parsing.

NEON_KEY may be a bare postgresql:// URL or the full `psql '...'` command Neon's console
shows, possibly with the `NEON_KEY =` prefix still attached. asyncpg rejects
`channel_binding`, so it is dropped. Services use the pooled host (PgBouncer transaction
mode: see POOLER_KWARGS); migrations use the direct host (`-pooler` stripped).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg

_URL = re.compile(r"postgres(?:ql)?://[^\s'\"]+")


@dataclass(frozen=True)
class NeonDsn:
    pooled: str
    direct: str

    def sqlalchemy(self, direct: bool = False) -> str:
        return (self.direct if direct else self.pooled).replace(
            "postgresql://", "postgresql+asyncpg://", 1
        )


def parse_neon_key(raw: str) -> NeonDsn:
    m = _URL.search(raw or "")
    if not m:
        raise ValueError("NEON_KEY holds no postgres URL")
    u = urlsplit(m.group(0))
    query = urlencode([(k, v) for k, v in parse_qsl(u.query) if k != "channel_binding"])
    pooled = u._replace(scheme="postgresql", query=query)
    direct = pooled._replace(netloc=pooled.netloc.replace("-pooler.", ".", 1))
    return NeonDsn(urlunsplit(pooled), urlunsplit(direct))


class PooledConnection(asyncpg.Connection):
    """Behind PgBouncer in transaction mode a connection carries no session state between
    transactions, so asyncpg's reset on every release (RESET ALL, UNLISTEN, advisory unlock)
    is a wasted round trip. At ~320 ms to the database that was a quarter of every query."""

    async def reset(self, *, timeout: float | None = None) -> None:
        return None


# asyncpg.create_pool kwargs for the Neon pooler. Neon's PgBouncer tracks protocol-level
# prepared statements, so asyncpg's statement cache stays on: one round trip per query, not two.
# Measured: 1.2 s -> 0.35 s for a one-row query.
POOLER_KWARGS = {"connection_class": PooledConnection}
