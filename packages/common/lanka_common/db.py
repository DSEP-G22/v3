"""NEON_KEY parsing.

NEON_KEY may be a bare postgresql:// URL or the full `psql '...'` command Neon's console
shows, possibly with the `NEON_KEY =` prefix still attached. asyncpg rejects
`channel_binding`, so it is dropped. Services use the pooled host (PgBouncer transaction
mode: statement caches off); migrations use the direct host (`-pooler` stripped).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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


# asyncpg.create_pool / connect kwargs required behind the Neon pooler.
POOLER_KWARGS = {"statement_cache_size": 0}
