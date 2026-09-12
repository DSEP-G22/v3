"""In-memory shapes the tools read.

World holds the global tables (catalogue, network inventory, incidents, slots), loaded once
and refreshed on change. Snapshot holds everything about one subscriber. Tools are pure
functions over (Snapshot, World, now), so a warm /tools:batch makes zero database round trips.

Metric and Usage mirror the TimescaleDB rows (line_metric_1h, usage_1d); the seeder produces
the same shapes for tests and history backfill.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

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

#: Sri Lanka has no DST, so a fixed offset is exact and needs no tzdata (absent on Windows).
COLOMBO = timezone(timedelta(hours=5, minutes=30))


@dataclass
class Metric:
    circuit_id: str
    sampled_at: datetime
    rx_power_dbm: float | None
    tx_power_dbm: float | None
    snr_db: float | None
    sync_down_mbps: float
    sync_up_mbps: float
    latency_ms: float
    jitter_ms: float
    packet_loss_pct: float
    crc_errors: int
    resyncs: int


@dataclass
class Usage:
    subscription_id: str
    usage_date: date
    down_gb: float
    up_gb: float
    peak_hour: int = 21
    shaped_minutes: int = 0


@dataclass
class World:
    plans: dict[str, PlanCatalogue] = field(default_factory=dict)
    sla: dict[str, SlaTier] = field(default_factory=dict)
    device_models: dict[str, DeviceModelCatalogue] = field(default_factory=dict)
    known_issues: list[KnownIssue] = field(default_factory=list)
    exchanges: dict[str, Exchange] = field(default_factory=dict)
    olts: dict[str, Olt] = field(default_factory=dict)
    splitters: dict[str, Splitter] = field(default_factory=dict)
    sites: dict[str, CellSite] = field(default_factory=dict)
    outages: list[OutageIncident] = field(default_factory=list)
    planned: list[PlannedWork] = field(default_factory=list)
    slots: dict[str, AppointmentSlot] = field(default_factory=dict)
    technicians: dict[str, Technician] = field(default_factory=dict)


@dataclass
class Snapshot:
    subscriber: Subscriber
    account: BillingAccount | None = None
    subscription: Subscription | None = None
    address: ServiceAddress | None = None
    circuit: Circuit | None = None
    cpe: CpeDevice | None = None
    addons: list[Addon] = field(default_factory=list)
    entitlements: list[Entitlement] = field(default_factory=list)
    invoices: list[Invoice] = field(default_factory=list)
    invoice_lines: dict[str, list[InvoiceLine]] = field(default_factory=dict)
    payments: list[Payment] = field(default_factory=list)
    ledger: list[LedgerEntry] = field(default_factory=list)
    dunning: list[DunningEvent] = field(default_factory=list)
    work_orders: list[WorkOrder] = field(default_factory=list)
    prior_tickets: list[PriorTicket] = field(default_factory=list)
    usage: list[Usage] = field(default_factory=list)
    metrics: list[Metric] = field(default_factory=list)


_GLOBAL = {
    PlanCatalogue: ("plans", "code"),
    SlaTier: ("sla", "tier"),
    DeviceModelCatalogue: ("device_models", "model"),
    Exchange: ("exchanges", "code"),
    Olt: ("olts", "id"),
    Splitter: ("splitters", "id"),
    CellSite: ("sites", "id"),
    AppointmentSlot: ("slots", "id"),
    Technician: ("technicians", "id"),
}
_GLOBAL_LISTS = {KnownIssue: "known_issues", OutageIncident: "outages", PlannedWork: "planned"}


def resolve(snaps: dict[str, Snapshot], ref: str) -> Snapshot | None:
    """Find a subscriber by id, MSISDN, email or billing account number.

    ponytail: linear scan over in-memory snapshots (tests, sim); production resolves in SQL.
    """
    ref = (ref or "").strip()
    if ref in snaps:
        return snaps[ref]
    low = ref.lower()
    bare = f"0{ref}" if ref.isdigit() and not ref.startswith("0") else None
    for snap in snaps.values():
        sub = snap.subscriber
        if ref == sub.msisdn or bare == sub.msisdn or low == (sub.email or "").lower():
            return snap
        if snap.account and snap.account.id == ref:
            return snap
    return None


def build(rows: list[Any]) -> tuple[World, dict[str, Snapshot]]:
    """Assemble World and every Snapshot from a flat row list (seeder output or a DB dump)."""
    world = World()
    by_type: dict[type, list[Any]] = defaultdict(list)
    for row in rows:
        by_type[type(row)].append(row)

    for cls, (attr, key) in _GLOBAL.items():
        getattr(world, attr).update({getattr(r, key): r for r in by_type[cls]})
    for cls, attr in _GLOBAL_LISTS.items():
        getattr(world, attr).extend(by_type[cls])

    snaps = {s.id: Snapshot(subscriber=s) for s in by_type[Subscriber]}
    addresses = {a.id: a for a in by_type[ServiceAddress]}
    for snap in snaps.values():
        snap.address = addresses.get(snap.subscriber.service_address_id or "")

    accounts: dict[str, Snapshot] = {}
    subs_by_id: dict[str, Snapshot] = {}
    for a in by_type[BillingAccount]:
        snaps[a.subscriber_id].account = a
        accounts[a.id] = snaps[a.subscriber_id]
    for s in by_type[Subscription]:
        snaps[s.subscriber_id].subscription = s
        subs_by_id[s.id] = snaps[s.subscriber_id]
    for c in by_type[Circuit]:
        snaps[c.subscriber_id].circuit = c
    for d in by_type[CpeDevice]:
        snaps[d.subscriber_id].cpe = d
    for e in by_type[Entitlement]:
        snaps[e.subscriber_id].entitlements.append(e)
    for w in by_type[WorkOrder]:
        snaps[w.subscriber_id].work_orders.append(w)
    for t in by_type[PriorTicket]:
        snaps[t.subscriber_id].prior_tickets.append(t)
    for a in by_type[Addon]:
        subs_by_id[a.subscription_id].addons.append(a)
    for u in by_type[Usage]:
        subs_by_id[u.subscription_id].usage.append(u)

    invoice_owner: dict[str, Snapshot] = {}
    for i in by_type[Invoice]:
        accounts[i.account_id].invoices.append(i)
        invoice_owner[i.id] = accounts[i.account_id]
    for line in by_type[InvoiceLine]:
        invoice_owner[line.invoice_id].invoice_lines.setdefault(line.invoice_id, []).append(line)
    for p in by_type[Payment]:
        accounts[p.account_id].payments.append(p)
    for le in by_type[LedgerEntry]:
        accounts[le.account_id].ledger.append(le)
    for d in by_type[DunningEvent]:
        accounts[d.account_id].dunning.append(d)

    circuits = {s.circuit.id: s for s in snaps.values() if s.circuit}
    for m in by_type[Metric]:
        circuits[m.circuit_id].metrics.append(m)
    return world, snaps
