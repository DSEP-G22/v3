"""Load World and Snapshots from Neon (org) and TimescaleDB (telemetry).

A snapshot is ~15 small queries run in parallel on the pool, so it costs about one Neon
round trip, then one local Timescale query. Snapshots are cached briefly in process and
dropped on any write that touches the subscriber.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from typing import Any

from app import db
from app.models import (
    Addon,
    AppointmentSlot,
    BillingAccount,
    CellSite,
    Circuit,
    CpeDevice,
    DeviceModelCatalogue,
    DunningEvent,
    Entitlement,
    Exchange,
    Invoice,
    InvoiceLine,
    KnownIssue,
    LedgerEntry,
    Olt,
    OutageIncident,
    Payment,
    PlanCatalogue,
    PlannedWork,
    PriorTicket,
    ServiceAddress,
    SlaTier,
    Splitter,
    Subscriber,
    Subscription,
    Technician,
    WorkOrder,
)
from app.world import Metric, Snapshot, Usage, World, build

SNAPSHOT_TTL_S = 10.0

_GLOBAL_TABLES = (
    PlanCatalogue, SlaTier, DeviceModelCatalogue, KnownIssue, Exchange, Olt, Splitter,
    CellSite, OutageIncident, PlannedWork, AppointmentSlot, Technician,
)


def _rows(cls, records) -> list[Any]:
    return [cls(**dict(r)) for r in records]


async def load_world() -> World:
    results = await asyncio.gather(
        *(db.neon.fetch(f'SELECT * FROM org."{cls.__tablename__}"') for cls in _GLOBAL_TABLES)
    )
    rows: list[Any] = []
    for cls, records in zip(_GLOBAL_TABLES, results):
        rows.extend(_rows(cls, records))
    world, _ = build(rows)
    return world


#: Identifier -> subscriber id. Found ids never change, so a hit saves a database round trip on
#: every screen; misses are not kept (a new customer may appear a moment later).
_ids: dict[str, str] = {}


async def resolve_id(ref: str) -> str | None:
    """Subscriber id from any identifier: id, MSISDN, email or billing account."""
    key = (ref or "").strip()
    if hit := _ids.get(key):
        return hit
    sid = await db.neon.fetchval(
        """SELECT s.id FROM org.subscriber s
           LEFT JOIN org.billing_account a ON a.subscriber_id = s.id
           WHERE s.id = $1 OR s.msisdn = $1 OR lower(s.email) = lower($1) OR a.id = $1
           LIMIT 1""",
        key,
    )
    if sid and len(_ids) < 50_000:
        _ids[key] = sid
    return sid


_ACCOUNT = "(SELECT id FROM org.billing_account WHERE subscriber_id = $1)"
_PER_SUBSCRIBER: tuple[tuple[type, str], ...] = (
    (Subscriber, "SELECT * FROM org.subscriber WHERE id = $1"),
    (BillingAccount, "SELECT * FROM org.billing_account WHERE subscriber_id = $1"),
    (Subscription, "SELECT * FROM org.subscription WHERE subscriber_id = $1 ORDER BY activated_on DESC LIMIT 1"),
    (ServiceAddress, "SELECT a.* FROM org.service_address a JOIN org.subscriber s ON s.service_address_id = a.id WHERE s.id = $1"),
    (Circuit, "SELECT * FROM org.circuit WHERE subscriber_id = $1"),
    (CpeDevice, "SELECT * FROM org.cpe_device WHERE subscriber_id = $1"),
    (Addon, "SELECT d.* FROM org.addon d JOIN org.subscription s ON s.id = d.subscription_id WHERE s.subscriber_id = $1"),
    (Entitlement, "SELECT * FROM org.entitlement WHERE subscriber_id = $1"),
    (Invoice, f"SELECT * FROM org.invoice WHERE account_id IN {_ACCOUNT}"),
    (InvoiceLine, f"SELECT l.* FROM org.invoice_line l JOIN org.invoice i ON i.id = l.invoice_id WHERE i.account_id IN {_ACCOUNT}"),
    (Payment, f"SELECT * FROM org.payment WHERE account_id IN {_ACCOUNT}"),
    (LedgerEntry, f"SELECT * FROM org.ledger_entry WHERE account_id IN {_ACCOUNT} ORDER BY posted_at DESC LIMIT 200"),
    (DunningEvent, f"SELECT * FROM org.dunning_event WHERE account_id IN {_ACCOUNT}"),
    (WorkOrder, "SELECT * FROM org.work_order WHERE subscriber_id = $1"),
    (PriorTicket, "SELECT * FROM org.prior_ticket WHERE subscriber_id = $1 ORDER BY opened_at DESC LIMIT 25"),
)

_cache: dict[str, tuple[float, Snapshot]] = {}


def invalidate(subscriber_id: str | None = None) -> None:
    if subscriber_id is None:
        _cache.clear()
    else:
        _cache.pop(subscriber_id, None)


async def load_snapshot(subscriber_id: str, world: World, now: datetime) -> Snapshot | None:
    # ponytail: in-process TTL cache; move to Valkey when business runs more than one replica.
    hit = _cache.get(subscriber_id)
    if hit and hit[0] > time.monotonic():
        return hit[1]

    results = await asyncio.gather(*(db.neon.fetch(q, subscriber_id) for _, q in _PER_SUBSCRIBER))
    rows: list[Any] = []
    for (cls, _), records in zip(_PER_SUBSCRIBER, results):
        rows.extend(_rows(cls, records))
    if not any(isinstance(r, Subscriber) for r in rows):
        return None

    circuit = next((r for r in rows if isinstance(r, Circuit)), None)
    subscription = next((r for r in rows if isinstance(r, Subscription)), None)
    metrics, usage = await asyncio.gather(
        db.ts.fetch(
            """SELECT bucket AS sampled_at, circuit_id, rx_power_dbm, tx_power_dbm, snr_db,
                      sync_down_mbps, sync_up_mbps, latency_ms, jitter_ms, packet_loss_pct,
                      crc_errors::int, resyncs::int
               FROM line_metric_1h WHERE circuit_id = $1 AND bucket > $2 AND bucket <= $3""",
            circuit.id if circuit else "",
            now - timedelta(days=30),
            now,
        ),
        db.ts.fetch(
            """SELECT subscription_id, (bucket AT TIME ZONE 'Asia/Colombo')::date AS usage_date,
                      down_gb, up_gb
               FROM usage_1d WHERE subscription_id = $1 AND bucket > $2 AND bucket <= $3""",
            subscription.id if subscription else "",
            now - timedelta(days=91),
            now,
        ),
    )
    rows.extend(Metric(**dict(r)) for r in metrics)
    rows.extend(Usage(**dict(r)) for r in usage)

    _, snaps = build(rows)
    snap = snaps[subscriber_id]
    _cache[subscriber_id] = (time.monotonic() + SNAPSHOT_TTL_S, snap)
    return snap
