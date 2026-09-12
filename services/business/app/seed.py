"""Deterministic genesis for the mock telco. Ported from v2 cst2/orgdata/seed.py.

A fixed random seed and one anchor instant (the sim clock at genesis) reproduce the same
world every time. Eight named personas each exercise one branch of the reasoning, then a
bulk population gives queues and dashboards realistic depth.

    SUB-100001  Amara Perera            healthy premium fibre. Do not invent a problem.
    SUB-100002  Ravi Fernando           suspended for non payment AND inside an OLT outage.
    SUB-100003  Nadia Silva             overdue but still connected, 489 of 500 GB used.
    SUB-100004  Dinesh Jayawardena      47 of 50 GB on a small mobile plan. Genuine upgrade.
    SUB-100005  Priya Kumar             already on the top plan. The right answer is no.
    SUB-100006  Kavindu Rathnayake      dead router, solid red power LED, CPE offline.
    SUB-100007  Thilini Wickramasinghe  enterprise SLA, evening congestion, line is healthy.
    SUB-100008  Mohamed Rizwan          duplicate equipment charge on the latest invoice.

v3 changes: rows are v3 models; telemetry comes out as Metric/Usage (TimescaleDB rows);
evening congestion follows Colombo local time; subscribers carry sim behaviour profiles.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from app.models import (
    Addon,
    AppointmentSlot,
    BillingAccount,
    CellSite,
    Circuit,
    CpeDevice,
    CreditNote,
    DeviceModelCatalogue,
    DunningEvent,
    Entitlement,
    Exchange,
    Interaction,
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
from app.world import COLOMBO, Metric, Usage

CONFIG_DIR = Path(os.environ.get("LANKA_CONFIG_DIR") or Path(__file__).resolve().parents[3] / "config")
RANDOM_SEED = 220922

FIRST_NAMES = [
    "Amara", "Ravi", "Nadia", "Dinesh", "Priya", "Kavindu", "Thilini", "Mohamed",
    "Sanduni", "Chamara", "Ishara", "Nuwan", "Dilani", "Praveen", "Hasitha", "Anusha",
    "Buddhika", "Malsha", "Tharindu", "Sewwandi", "Roshan", "Iresha", "Lakmal", "Nethmi",
    "Gayan", "Upeksha", "Sahan", "Rashmi", "Janaka", "Dulani", "Shanaka", "Piyumi",
]
LAST_NAMES = [
    "Perera", "Fernando", "Silva", "Jayawardena", "Kumar", "Rathnayake", "Wickramasinghe",
    "Rizwan", "Bandara", "Gunasekara", "Dissanayake", "Herath", "Weerasinghe", "Amarasinghe",
    "Ekanayake", "Senanayake", "Wijesekara", "Abeysinghe", "Karunaratne", "Mendis",
]
STREETS = [
    "Galle Road", "Marine Drive", "Duplication Road", "Havelock Road", "Baseline Road",
    "Kandy Road", "Negombo Road", "High Level Road", "Peradeniya Road", "Matara Road",
    "Nawala Road", "Rajagiriya Avenue", "Temple Lane", "Station Road", "Lake Drive",
]
CITY_BY_EXCHANGE = {
    "EX-CMB-CENTRAL": ("Colombo 03", "Colombo", "metro"),
    "EX-CMB-NORTH": ("Colombo 13", "Colombo", "metro"),
    "EX-DEH-WELLA": ("Dehiwala", "Colombo", "urban"),
    "EX-GAM-KADA": ("Kadawatha", "Gampaha", "urban"),
    "EX-KAN-PERA": ("Peradeniya", "Kandy", "urban"),
    "EX-GAL-FORT": ("Galle", "Galle", "urban"),
    "EX-KUR-TOWN": ("Kurunegala", "Kurunegala", "rural"),
}
OLT_VENDORS = [("Huawei", "MA5800-X7"), ("Nokia", "7360 ISAM FX-8"), ("ZTE", "C620")]
TECH_SKILLS = [
    ["gpon", "cpe_swap"],
    ["copper", "cpe_swap"],
    ["gpon", "copper", "splicing"],
    ["gpon", "splicing", "civils"],
    ["cpe_swap", "survey"],
]


def load_catalogue() -> dict[str, Any]:
    return yaml.safe_load((CONFIG_DIR / "orgdata_seed.yaml").read_text(encoding="utf-8")) or {}


def entitlements_for(
    subscriber_id: str, plan: dict[str, Any], catalogue: dict[str, Any], make_id
) -> list[Entitlement]:
    """What a plan entitles a subscriber to. Shared by genesis and real sign-ups."""
    meta = {e["code"]: e for e in catalogue["entitlements"]}
    tier = plan["tier"]
    granted: list[tuple[str, bool, float | None]] = [
        ("OUTAGE_CREDIT", True, plan["monthly_price_lkr"] * 0.5),
        ("GOODWILL_CREDIT", True, 1500.0 if tier in ("basic", "standard") else 5000.0),
        ("SAME_DAY_ENGINEER", tier in ("premium", "platinum"), None),
        ("FREE_CPE_SWAP", tier != "basic", None),
        ("PLAN_CHANGE_ANYTIME", plan["contract_months"] == 0, None),
        ("CONTRACT_PAUSE", tier in ("premium", "platinum"), None),
        ("LATE_FEE_WAIVER", tier != "basic", None),
    ]
    return [
        Entitlement(
            id=make_id(),
            subscriber_id=subscriber_id,
            code=code,
            display_name=meta[code]["display_name"],
            granted=allowed,
            limit_value=limit,
            limit_unit=meta[code].get("limit_unit"),
        )
        for code, allowed, limit in granted
    ]


@dataclass
class SeedClock:
    now: datetime

    @property
    def today(self) -> date:
        return self.now.date()

    def days_ago(self, days: float) -> datetime:
        return self.now - timedelta(days=days)

    def days_ahead(self, days: float) -> datetime:
        return self.now + timedelta(days=days)

    def hours_ago(self, hours: float) -> datetime:
        return self.now - timedelta(hours=hours)

    def date_ago(self, days: int) -> date:
        return (self.now - timedelta(days=days)).date()

    def date_ahead(self, days: int) -> date:
        return (self.now + timedelta(days=days)).date()


class SandboxSeeder:
    def __init__(self, clock: SeedClock | None = None, rng: random.Random | None = None) -> None:
        self.clock = clock or SeedClock(datetime.now(timezone.utc))
        self.rng = rng or random.Random(RANDOM_SEED)
        self.catalogue = load_catalogue()
        self.rows: list[Any] = []
        self._counters: dict[str, int] = {}
        self.olts_by_exchange: dict[str, list[str]] = {}
        self.splitters_by_olt: dict[str, list[str]] = {}
        self.sites_by_district: dict[str, list[str]] = {}

    def _next(self, bucket: str, start: int = 1) -> int:
        value = self._counters.get(bucket, start - 1) + 1
        self._counters[bucket] = value
        return value

    def add(self, row: Any) -> Any:
        self.rows.append(row)
        return row

    @staticmethod
    def short_code(exchange_code: str) -> str:
        """EX-CMB-CENTRAL becomes CMBCE, so the two Colombo exchanges do not collide."""
        parts = exchange_code.split("-")
        town = parts[1] if len(parts) > 1 else exchange_code
        detail = parts[2] if len(parts) > 2 else ""
        return f"{town[:3]}{detail[:2]}".upper()

    # -- reference data ------------------------------------------------------------------

    def seed_reference(self) -> None:
        for tier in self.catalogue.get("sla_tiers", []):
            self.add(SlaTier(**tier))
        for plan in self.catalogue.get("plans", []):
            self.add(PlanCatalogue(**plan, active=True, sellable=plan["family"] != "BizFibre"))
        for model in self.catalogue.get("device_models", []):
            self.add(DeviceModelCatalogue(**model))
        for issue in self.catalogue.get("known_issues", []):
            self.add(KnownIssue(**issue))
        for exchange in self.catalogue.get("exchanges", []):
            self.add(Exchange(**exchange, status="operational"))

    def seed_network(self) -> None:
        for exchange in self.catalogue.get("exchanges", []):
            code = exchange["code"]
            short = self.short_code(code)
            self.olts_by_exchange.setdefault(code, [])
            for index in range(1, 3):
                vendor, model = self.rng.choice(OLT_VENDORS)
                olt_id = f"OLT-{short}-{index:02d}"
                self.olts_by_exchange[code].append(olt_id)
                self.splitters_by_olt.setdefault(olt_id, [])
                self.add(
                    Olt(
                        id=olt_id,
                        exchange_code=code,
                        vendor=vendor,
                        model=model,
                        firmware=f"{self.rng.randint(6, 9)}.{self.rng.randint(0, 9)}.{self.rng.randint(0, 20)}",
                        port_count=self.rng.choice([64, 128, 256]),
                        uplink_status="up",
                        uplink_utilisation_pct=round(self.rng.uniform(28.0, 62.0), 1),
                        uplink_capacity_gbps=10.0,
                        last_seen_at=self.clock.hours_ago(self.rng.uniform(0.0, 0.5)),
                    )
                )
                for slot in range(1, 13):
                    splitter_id = f"SPL-{short}-{index:02d}-{slot:02d}"
                    self.splitters_by_olt[olt_id].append(splitter_id)
                    self.add(
                        Splitter(
                            id=splitter_id,
                            olt_id=olt_id,
                            ratio=self.rng.choice(["1:16", "1:32", "1:64"]),
                            location_note=f"Cabinet {slot} on {self.rng.choice(STREETS)}",
                            condition="healthy",
                            installed_on=self.clock.date_ago(self.rng.randint(400, 2400)),
                        )
                    )

        districts = sorted({v[1] for v in CITY_BY_EXCHANGE.values()})
        site_no = 100
        for district in districts:
            for _ in range(4):
                site_no += 1
                site_id = f"SITE-{district[:3].upper()}-{site_no}"
                self.sites_by_district.setdefault(district, []).append(site_id)
                self.add(
                    CellSite(
                        id=site_id,
                        name=f"{district} sector {site_no}",
                        region="Western" if district in ("Colombo", "Gampaha") else "Other",
                        district=district,
                        technologies=self.rng.choice([["4G"], ["4G", "5G"]]),
                        sector_count=3,
                        status="on_air",
                        latitude=round(6.7 + self.rng.uniform(-0.6, 1.6), 5),
                        longitude=round(79.9 + self.rng.uniform(-0.4, 1.2), 5),
                    )
                )

    def seed_field_ops(self) -> None:
        districts = sorted({v[1] for v in CITY_BY_EXCHANGE.values()})
        tech_no = 100
        for district in districts:
            for _ in range(9):
                tech_no += 1
                self.add(
                    Technician(
                        id=f"TECH-{tech_no:04d}",
                        full_name=f"{self.rng.choice(FIRST_NAMES)} {self.rng.choice(LAST_NAMES)}",
                        region="Western" if district in ("Colombo", "Gampaha") else "Other",
                        district=district,
                        skills=self.rng.choice(TECH_SKILLS),
                        shift=self.rng.choice(["day", "day", "day", "late"]),
                        availability=self.rng.choice(["available", "available", "on_job", "off_shift"]),
                        rating=round(self.rng.uniform(3.9, 4.9), 1),
                    )
                )

        windows = [("morning", 9, 12), ("afternoon", 13, 17), ("evening", 17, 20)]
        slot_no = 0
        for offset in range(0, 21):
            slot_date = self.clock.date_ahead(offset)
            if slot_date.weekday() == 6:
                continue  # no Sunday appointments
            for district in districts:
                for name, start, end in windows:
                    slot_no += 1
                    capacity = 6 if district == "Colombo" else 3
                    booked = min(capacity, max(0, int(self.rng.gauss(capacity * 0.6, 1.4))))
                    self.add(
                        AppointmentSlot(
                            id=f"SLOT-{slot_no:05d}",
                            slot_date=slot_date,
                            window=name,
                            window_start_hour=start,
                            window_end_hour=end,
                            district=district,
                            capacity=capacity,
                            booked=booked,
                            skill_required=None,
                        )
                    )

    # -- subscribers ---------------------------------------------------------------------

    def _address(self, exchange_code: str) -> ServiceAddress:
        city, district, density = CITY_BY_EXCHANGE[exchange_code]
        return self.add(
            ServiceAddress(
                id=f"ADR-{self._next('address'):06d}",
                line1=f"{self.rng.randint(1, 320)}/{self.rng.randint(1, 9)} {self.rng.choice(STREETS)}",
                line2=None,
                city=city,
                district=district,
                postcode=f"{self.rng.randint(10000, 82000)}",
                latitude=round(6.7 + self.rng.uniform(-0.6, 1.6), 5),
                longitude=round(79.9 + self.rng.uniform(-0.4, 1.2), 5),
                exchange_code=exchange_code,
                density=density,
            )
        )

    def plan(self, code: str) -> dict[str, Any]:
        for plan in self.catalogue["plans"]:
            if plan["code"] == code:
                return plan
        raise KeyError(code)

    def grant_entitlements(self, subscriber_id: str, plan: dict[str, Any]) -> None:
        for row in entitlements_for(
            subscriber_id, plan, self.catalogue, lambda: f"ENT-{self._next('entitlement'):06d}"
        ):
            self.add(row)

    def _billing_history(
        self,
        account: BillingAccount,
        plan: dict[str, Any],
        months: int,
        *,
        unpaid_months: int = 0,
        unusual_line: tuple[str, float, str] | None = None,
    ) -> float:
        """Write invoices, payments and a running ledger. Returns the closing balance."""
        balance = 0.0
        base = plan["monthly_price_lkr"]
        for back in range(months, 0, -1):
            period_end = self.clock.date_ago(back * 30)
            period_start = self.clock.date_ago(back * 30 + 29)
            issued = period_end
            due = period_end + timedelta(days=14)
            invoice_id = f"INV-{issued.year}-{self._next('invoice'):06d}"

            lines: list[tuple[str, str, float, float, bool, str | None]] = [
                (f"{plan['display_name']} monthly charge", "subscription", 1.0, base, False, None)
            ]
            if unusual_line and back == 1:
                label, amount, reason = unusual_line
                lines.append((label, "equipment", 1.0, amount, True, reason))

            subtotal = sum(qty * price for _, _, qty, price, _, _ in lines)
            tax = round(subtotal * 0.18, 2)
            total = round(subtotal + tax, 2)
            unpaid = back <= unpaid_months
            status = "unpaid" if unpaid else "paid"
            if unpaid and due < self.clock.today:
                status = "overdue"

            self.add(
                Invoice(
                    id=invoice_id,
                    account_id=account.id,
                    period_start=period_start,
                    period_end=period_end,
                    issued_on=issued,
                    due_on=due,
                    subtotal_lkr=round(subtotal, 2),
                    tax_lkr=tax,
                    total_lkr=total,
                    paid_lkr=0.0 if unpaid else total,
                    status=status,
                )
            )
            for index, (desc, category, qty, price, unusual, reason) in enumerate(lines, start=1):
                self.add(
                    InvoiceLine(
                        id=f"INL-{self._next('invoice_line'):07d}",
                        invoice_id=invoice_id,
                        line_no=index,
                        description=desc,
                        category=category,
                        quantity=qty,
                        unit_price_lkr=price,
                        amount_lkr=round(qty * price, 2),
                        is_unusual=unusual,
                        unusual_reason=reason,
                    )
                )
            self.add(
                InvoiceLine(
                    id=f"INL-{self._next('invoice_line'):07d}",
                    invoice_id=invoice_id,
                    line_no=len(lines) + 1,
                    description="Value added tax at 18 percent",
                    category="tax",
                    quantity=1.0,
                    unit_price_lkr=tax,
                    amount_lkr=tax,
                    is_unusual=False,
                    unusual_reason=None,
                )
            )

            balance = round(balance + total, 2)
            self.add(
                LedgerEntry(
                    id=f"LED-{self._next('ledger'):07d}",
                    account_id=account.id,
                    posted_at=datetime.combine(issued, datetime.min.time(), tzinfo=timezone.utc),
                    description=f"Invoice {invoice_id}",
                    kind="invoice",
                    debit_lkr=total,
                    credit_lkr=0.0,
                    balance_after_lkr=balance,
                    reference=invoice_id,
                )
            )

            if not unpaid:
                posted = datetime.combine(
                    due - timedelta(days=self.rng.randint(1, 10)), datetime.min.time(), tzinfo=timezone.utc
                )
                payment_id = f"PAY-{self._next('payment'):07d}"
                self.add(
                    Payment(
                        id=payment_id,
                        account_id=account.id,
                        invoice_id=invoice_id,
                        amount_lkr=total,
                        method=self.rng.choice(["card", "card", "mobile_wallet", "bank_transfer", "direct_debit"]),
                        reference=f"REF{self.rng.randint(10**8, 10**9 - 1)}",
                        posted_at=posted,
                        status="settled",
                    )
                )
                balance = round(balance - total, 2)
                self.add(
                    LedgerEntry(
                        id=f"LED-{self._next('ledger'):07d}",
                        account_id=account.id,
                        posted_at=posted,
                        description=f"Payment received, {payment_id}",
                        kind="payment",
                        debit_lkr=0.0,
                        credit_lkr=total,
                        balance_after_lkr=balance,
                        reference=payment_id,
                    )
                )

        account.outstanding_balance = round(balance, 2)
        return account.outstanding_balance

    def _usage(self, subscription: Subscription, plan: dict[str, Any], target_gb: float | None) -> None:
        """Ninety days of daily usage, the current cycle summing exactly to target_gb.

        The cycle boundary matches get_usage_summary's, inclusive of both ends, so a persona
        built to sit just under the cap does not report as over it.
        """
        cap = plan["data_cap_gb"]
        today = self.clock.today
        cycle_start = subscription.renewal_date - timedelta(days=30)
        while cycle_start > today:
            cycle_start -= timedelta(days=30)
        elapsed = (today - cycle_start).days
        days_in_cycle = elapsed + 1

        if target_gb is None:
            monthly = cap * self.rng.uniform(0.25, 0.7) if cap > 0 else self.rng.uniform(280, 900)
            target_gb = monthly * (days_in_cycle / 30.0)

        upload_ratio = self.rng.uniform(0.05, 0.18)
        shape = [max(0.05, self.rng.gauss(1.0, 0.18)) for _ in range(days_in_cycle)]
        scale = target_gb / (sum(shape) * (1.0 + upload_ratio))

        for back in range(89, -1, -1):
            if back <= elapsed:
                down = shape[elapsed - back] * scale
            else:
                previous = (cap * 0.5 / 30.0) if cap > 0 else self.rng.uniform(9.0, 26.0)
                down = max(0.05, self.rng.gauss(previous, previous * 0.18)) / (1.0 + upload_ratio)
            self.add(
                Usage(
                    subscription_id=subscription.id,
                    usage_date=self.clock.date_ago(back),
                    down_gb=round(down, 3),
                    up_gb=round(down * upload_ratio, 3),
                    peak_hour=self.rng.choice([20, 21, 21, 22]),
                )
            )

    def _line_metrics(
        self,
        circuit: Circuit,
        hours: int = 720,
        *,
        healthy: bool = True,
        evening_congestion: bool = False,
        dead_after_hours: int | None = None,
    ) -> None:
        for back in range(hours, -1, -1):
            sampled = self.clock.hours_ago(back)
            if dead_after_hours is not None and back <= dead_after_hours:
                self.add(Metric(circuit.id, sampled, None, None, None, 0.0, 0.0, 0.0, 0.0, 100.0, 0, 0))
                continue

            congested = evening_congestion and 20 <= sampled.astimezone(COLOMBO).hour <= 23
            factor = 0.35 if congested else self.rng.uniform(0.92, 1.0)
            if not healthy:
                factor *= self.rng.uniform(0.4, 0.75)
            self.add(
                Metric(
                    circuit_id=circuit.id,
                    sampled_at=sampled,
                    rx_power_dbm=round(self.rng.gauss(-19.5 if healthy else -26.5, 0.8), 2),
                    tx_power_dbm=round(self.rng.gauss(2.3, 0.3), 2),
                    snr_db=round(self.rng.gauss(31.0 if healthy else 17.0, 1.6), 1),
                    sync_down_mbps=round(circuit.provisioned_down_mbps * factor, 1),
                    sync_up_mbps=round(circuit.provisioned_up_mbps * factor, 1),
                    latency_ms=round(self.rng.gauss(190.0 if congested else 62.0, 12.0), 1),
                    jitter_ms=round(self.rng.gauss(22.0 if congested else 4.0, 2.0), 1),
                    packet_loss_pct=round(max(0.0, self.rng.gauss(0.2 if healthy else 3.4, 0.4)), 2),
                    crc_errors=self.rng.randint(0, 4) if healthy else self.rng.randint(60, 900),
                    resyncs=0 if healthy else self.rng.randint(1, 6),
                )
            )

    def build_subscriber(
        self,
        *,
        subscriber_id: str,
        full_name: str,
        plan_code: str,
        exchange_code: str,
        segment: str = "consumer",
        language_pref: str = "en",
        account_status: str = "current",
        subscription_status: str = "active",
        dunning_stage: str = "none",
        unpaid_months: int = 0,
        usage_target_gb: float | None = None,
        device_model: str = "LL-ONT-2400",
        cpe_wan_status: str = "online",
        line_state: str = "up",
        circuit_status: str = "in_service",
        healthy_line: bool = True,
        evening_congestion: bool = False,
        dead_after_hours: int | None = None,
        unusual_line: tuple[str, float, str] | None = None,
        firmware_behind: bool = False,
        notes: str | None = None,
        prior_ticket_count: int = 2,
        metric_hours: int = 720,
        pay_profile: str = "on_time",
        usage_profile: str = "median",
    ) -> Subscriber:
        plan = self.plan(plan_code)
        address = self._address(exchange_code)
        joined = self.clock.date_ago(self.rng.randint(200, 2600))

        subscriber = self.add(
            Subscriber(
                id=subscriber_id,
                full_name=full_name,
                preferred_name=full_name.split()[0],
                nic_masked=f"{self.rng.randint(80, 99)}xxxxxx{self.rng.randint(100, 999)}V",
                msisdn=f"07{self.rng.randint(10000000, 89999999)}",
                email=full_name.lower().replace(" ", ".") + f"{self.rng.randint(1, 99)}@example.lk",
                segment=segment,
                language_pref=language_pref,
                preferred_channel=self.rng.choice(["web_portal", "phone", "chat", "email"]),
                joined_on=joined,
                service_address_id=address.id,
                marketing_opt_in=self.rng.random() < 0.4,
                notes=notes,
                simulated=True,
                pay_profile=pay_profile,
                usage_profile=usage_profile,
            )
        )
        self.grant_entitlements(subscriber_id, plan)

        account = self.add(
            BillingAccount(
                id=f"ACC-{self._next('account', 4400000):07d}",
                subscriber_id=subscriber_id,
                currency="LKR",
                billing_cycle_day=self.rng.randint(1, 28),
                status=account_status,
                dunning_stage=dunning_stage,
                credit_limit=25000.0 if segment == "consumer" else 250000.0,
                outstanding_balance=0.0,
                autopay_enabled=pay_profile == "autopay",
                opened_on=joined,
            )
        )

        subscription = self.add(
            Subscription(
                id=f"SVC-{self._next('subscription', 880000):06d}",
                subscriber_id=subscriber_id,
                account_id=account.id,
                plan_code=plan_code,
                status=subscription_status,
                activated_on=joined,
                contract_ends_on=(
                    joined + timedelta(days=30 * plan["contract_months"]) if plan["contract_months"] else None
                ),
                suspended_on=self.clock.date_ago(3) if subscription_status == "suspended" else None,
                suspension_reason=(
                    "Unpaid balance beyond the final notice period" if subscription_status == "suspended" else None
                ),
                renewal_date=self.clock.date_ahead(self.rng.randint(2, 28)),
            )
        )

        for addon in self.rng.sample(self.catalogue["addons"], k=self.rng.choice([0, 0, 1, 1, 2])):
            self.add(
                Addon(
                    id=f"ADD-{self._next('addon'):06d}",
                    subscription_id=subscription.id,
                    code=addon["code"],
                    display_name=addon["display_name"],
                    monthly_price_lkr=addon["monthly_price_lkr"],
                    active=True,
                    added_on=self.clock.date_ago(self.rng.randint(30, 600)),
                )
            )

        balance = self._billing_history(
            account, plan, months=6, unpaid_months=unpaid_months, unusual_line=unusual_line
        )
        if unpaid_months:
            stages = ["reminder", "final_notice", "restrict", "suspend"]
            for index, stage in enumerate(stages[: min(unpaid_months + 1, len(stages))]):
                self.add(
                    DunningEvent(
                        id=f"DUN-{self._next('dunning'):06d}",
                        account_id=account.id,
                        stage=stage,
                        occurred_at=self.clock.days_ago(20 - index * 5),
                        channel=self.rng.choice(["sms", "email", "sms"]),
                        amount_at_time_lkr=balance,
                        note=None,
                    )
                )

        olt_id = splitter_id = cell_site_id = None
        if plan["technology"] in ("gpon", "adsl"):
            olt_id = self.rng.choice(self.olts_by_exchange[exchange_code])
            splitter_id = self.rng.choice(self.splitters_by_olt[olt_id])
        else:
            cell_site_id = self.rng.choice(self.sites_by_district[CITY_BY_EXCHANGE[exchange_code][1]])

        circuit = self.add(
            Circuit(
                id=f"CIR-{self._next('circuit', 9930000):07d}",
                subscription_id=subscription.id,
                subscriber_id=subscriber_id,
                technology=plan["technology"],
                olt_id=olt_id,
                splitter_id=splitter_id,
                cell_site_id=cell_site_id,
                port=f"0/{self.rng.randint(1, 15)}/{self.rng.randint(1, 64)}" if olt_id else None,
                provisioned_down_mbps=plan["speed_down_mbps"],
                provisioned_up_mbps=plan["speed_up_mbps"],
                status=circuit_status,
                line_state=line_state,
                last_state_change=self.clock.hours_ago(
                    dead_after_hours if dead_after_hours else self.rng.uniform(48, 900)
                ),
                activated_on=joined,
            )
        )

        model_meta = next(m for m in self.catalogue["device_models"] if m["model"] == device_model)
        firmware = (
            "4.1.2" if firmware_behind and device_model == "LL-ONT-2400" else model_meta["latest_firmware"]
        )
        online = cpe_wan_status == "online"
        self.add(
            CpeDevice(
                serial=f"LLK{self.rng.randint(10**9, 10**10 - 1)}",
                circuit_id=circuit.id,
                subscriber_id=subscriber_id,
                model=device_model,
                mac=":".join(f"{self.rng.randint(0, 255):02X}" for _ in range(6)),
                firmware_version=firmware,
                wan_status=cpe_wan_status,
                uptime_s=self.rng.randint(3600, 2_600_000) if online else 0,
                last_seen_at=(
                    self.clock.hours_ago(self.rng.uniform(0.01, 0.4))
                    if online
                    else self.clock.hours_ago(dead_after_hours or 72)
                ),
                lan_clients=self.rng.randint(2, 14) if online else 0,
                wifi_channel=self.rng.choice([1, 6, 11, 36, 44]),
                wifi_band_steering=True,
                reboot_count_7d=self.rng.randint(4, 19) if firmware_behind else self.rng.randint(0, 2),
                owned_by_operator=True,
                installed_on=joined,
            )
        )

        self._usage(subscription, plan, usage_target_gb)
        self._line_metrics(
            circuit,
            hours=metric_hours,
            healthy=healthy_line,
            evening_congestion=evening_congestion,
            dead_after_hours=dead_after_hours,
        )
        self._history(subscriber, prior_ticket_count)
        return subscriber

    def _history(self, subscriber: Subscriber, count: int) -> None:
        templates = [
            ("technical_support", "check_connection", "fault_line_sync",
             "Line dropped after a power cut and did not resynchronise.",
             "resolved_remote", "Remote resync cleared it within the hour."),
            ("billing", "check_invoice", "fault_billing_dispute",
             "Customer queried an unexpected charge on the monthly bill.",
             "explained", "Charge was a correct pro rata adjustment. Explained and accepted."),
            ("field_service", "schedule_visit", "fault_cabling",
             "Physical damage to the drop cable after roadworks.",
             "engineer_fixed", "Drop cable replaced on site."),
            ("network_operations", "report_outage", "fault_intermittent_connection",
             "Evening slowdown reported repeatedly over a fortnight.",
             "capacity_raised", "Traced to uplink congestion. Capacity request raised."),
            ("retention", "cancel_service", None,
             "Customer asked about cancelling after a price change.",
             "retained", "Retained on a matched discount for six months."),
        ]
        for index in range(count):
            dept, intent, fault, summary, code, note = templates[
                (self.rng.randrange(len(templates)) + index) % len(templates)
            ]
            opened = self.clock.days_ago(self.rng.randint(20, 620))
            self.add(
                PriorTicket(
                    ref=f"TCK-{opened.year}-{self._next('prior_ticket'):06d}",
                    subscriber_id=subscriber.id,
                    department=dept,
                    intent=intent,
                    fault=fault,
                    summary=summary,
                    opened_at=opened,
                    resolved_at=opened + timedelta(hours=self.rng.randint(2, 96)),
                    resolution_code=code,
                    resolution_note=note,
                    action_taken=self.rng.choice(
                        ["run_line_diagnostic", "restart_router", "issue_billing_credit", None]
                    ),
                    csat=self.rng.choice([3, 4, 4, 5, 5, None]),
                    reopened=self.rng.random() < 0.08,
                )
            )
            self.add(
                Interaction(
                    id=f"INT-{self._next('interaction'):07d}",
                    subscriber_id=subscriber.id,
                    channel=self.rng.choice(["phone", "chat", "email", "web_portal"]),
                    occurred_at=opened,
                    direction="inbound",
                    summary=summary,
                    outcome=code,
                    handled_by=f"agent{self.rng.randint(1, 24):02d}",
                )
            )

    # -- personas and bulk ------------------------------------------------------------------

    def seed_personas(self) -> None:
        b = self.build_subscriber
        b(subscriber_id="SUB-100001", full_name="Amara Perera", plan_code="FIBREMAX-300",
          exchange_code="EX-CMB-CENTRAL", usage_target_gb=180.0, device_model="LL-ONT-2600",
          pay_profile="autopay",
          notes="Healthy premium fibre line. Nothing is wrong. Do not invent a fault.")
        b(subscriber_id="SUB-100002", full_name="Ravi Fernando", plan_code="HOMENET-100",
          exchange_code="EX-CMB-CENTRAL", language_pref="si", account_status="suspended",
          subscription_status="suspended", dunning_stage="suspend", unpaid_months=2,
          usage_target_gb=137.0, device_model="ZY-VMG-3625", cpe_wan_status="offline",
          line_state="down", circuit_status="suspended", healthy_line=False, dead_after_hours=72,
          pay_profile="never", prior_ticket_count=3,
          notes=("Service barred for an unpaid balance. Also sits under an open outage on the "
                 "Colombo Central OLT. Both causes are real and both belong in the reply."))
        b(subscriber_id="SUB-100003", full_name="Nadia Silva", plan_code="HOMENET-100",
          exchange_code="EX-DEH-WELLA", account_status="overdue", dunning_stage="reminder",
          unpaid_months=1, usage_target_gb=489.0, device_model="ZY-VMG-3625", pay_profile="late",
          usage_profile="heavy",
          notes="Overdue but inside the grace period, so still connected. Close to the cap.")
        b(subscriber_id="SUB-100004", full_name="Dinesh Jayawardena", plan_code="MOBILEGO-50",
          exchange_code="EX-GAM-KADA", usage_target_gb=47.0, device_model="HW-B535-232",
          usage_profile="heavy",
          notes="Consistently near the allowance. A larger plan is a genuine recommendation.")
        b(subscriber_id="SUB-100005", full_name="Priya Kumar", plan_code="FIBREMAX-1000",
          exchange_code="EX-CMB-NORTH", segment="vip", usage_target_gb=1240.0,
          device_model="LL-ONT-2600", pay_profile="autopay", usage_profile="heavy",
          notes="Already on the fastest residential plan. There is nothing to upgrade to.")
        b(subscriber_id="SUB-100006", full_name="Kavindu Rathnayake", plan_code="FIBREMAX-300",
          exchange_code="EX-KAN-PERA", usage_target_gb=210.0, device_model="LL-ONT-2400",
          cpe_wan_status="offline", line_state="down", healthy_line=False, dead_after_hours=14,
          firmware_behind=True,
          notes=("Router shows a solid red power light and has not been seen for fourteen hours. "
                 "Firmware is behind and the model has a documented reboot loop."))
        b(subscriber_id="SUB-100007", full_name="Thilini Wickramasinghe", plan_code="BIZFIBRE-500",
          exchange_code="EX-CMB-CENTRAL", segment="enterprise", usage_target_gb=2100.0,
          device_model="LL-ONT-2600", evening_congestion=True, pay_profile="autopay",
          usage_profile="heavy", prior_ticket_count=4,
          notes=("Enterprise assured SLA. The line itself measures healthy. The evening "
                 "slowdown is uplink congestion on the OLT, not a fault at the premises."))
        b(subscriber_id="SUB-100008", full_name="Mohamed Rizwan", plan_code="HOMENET-100",
          exchange_code="EX-GAL-FORT", language_pref="ta", usage_target_gb=302.0,
          device_model="ZY-VMG-3625",
          unusual_line=("Replacement router equipment fee", 7500.0,
                        "Charged twice. The same fee also appears on the previous invoice."),
          notes="Equipment fee billed twice. A genuine billing error, not a misunderstanding.")

    def seed_bulk(self, count: int) -> None:
        exchanges = [e["code"] for e in self.catalogue["exchanges"]]
        plans = [p["code"] for p in self.catalogue["plans"]]
        weights = [12, 16, 30, 24, 12, 6]
        models = {
            "gpon": ["LL-ONT-2400", "LL-ONT-2600"],
            "adsl": ["ZY-VMG-3625"],
            "lte": ["HW-B535-232"],
            "fwa": ["HW-B535-232"],
        }
        for index in range(count):
            plan_code = self.rng.choices(plans, weights=weights, k=1)[0]
            plan = self.plan(plan_code)
            roll = self.rng.random()
            if roll < 0.06:
                account_status, sub_status, dunning, unpaid, pay = "suspended", "suspended", "suspend", 2, "never"
            elif roll < 0.18:
                account_status, sub_status, dunning, unpaid, pay = "overdue", "active", "reminder", 1, "late"
            else:
                account_status, sub_status, dunning, unpaid = "current", "active", "none", 0
                pay = self.rng.choice(["autopay", "autopay", "on_time", "on_time", "on_time", "late"])
            faulty = self.rng.random() < 0.05
            self.build_subscriber(
                subscriber_id=f"SUB-{100100 + index:06d}",
                full_name=f"{self.rng.choice(FIRST_NAMES)} {self.rng.choice(LAST_NAMES)}",
                plan_code=plan_code,
                exchange_code=self.rng.choice(exchanges),
                segment=self.rng.choices(["consumer", "sme", "enterprise", "vip"], weights=[82, 11, 4, 3], k=1)[0],
                language_pref=self.rng.choices(
                    ["en", "si", "ta", "si-Latn", "ta-Latn"], weights=[46, 30, 14, 7, 3], k=1
                )[0],
                account_status=account_status,
                subscription_status=sub_status,
                dunning_stage=dunning,
                unpaid_months=unpaid,
                device_model=self.rng.choice(models[plan["technology"]]),
                cpe_wan_status="offline" if faulty else "online",
                line_state="down" if faulty else "up",
                healthy_line=not faulty,
                dead_after_hours=self.rng.randint(2, 40) if faulty else None,
                prior_ticket_count=self.rng.choice([0, 1, 1, 2, 2, 3]),
                metric_hours=168,
                pay_profile=pay,
                usage_profile=self.rng.choices(["light", "median", "heavy"], weights=[30, 50, 20], k=1)[0],
            )

    def _olt_for(self, subscriber_id: str) -> str | None:
        return next(
            (r.olt_id for r in self.rows if isinstance(r, Circuit) and r.subscriber_id == subscriber_id),
            None,
        )

    def seed_incidents(self) -> None:
        """The first incident sits on SUB-100002's OLT, giving that persona two real causes."""
        year = self.clock.today.year
        central_olt = self._olt_for("SUB-100002") or self.olts_by_exchange["EX-CMB-CENTRAL"][0]
        kandy_site = self.sites_by_district["Kandy"][0]
        self.add(
            OutageIncident(
                id=f"INC-{year}-0418", scope="olt", scope_ref=central_olt,
                title="Fibre break on the Colombo Central feeder",
                cause="A contractor severed the primary feeder during road widening on Baseline Road.",
                cause_category="fibre_cut", severity="critical",
                opened_at=self.clock.hours_ago(9), eta_at=self.clock.now + timedelta(hours=6),
                resolved_at=None, status="mitigating", affected_estimate=1840,
                customer_message=(
                    "We are repairing a damaged fibre cable that is affecting broadband in "
                    "parts of Colombo Central. Our engineers are on site and we expect service "
                    "to return within six hours."
                ),
                credit_policy="Automatic credit for any full day of lost service.",
            )
        )
        self.add(
            OutageIncident(
                id=f"INC-{year}-0421", scope="cell_site", scope_ref=kandy_site,
                title="Kandy sector 105 running on battery",
                cause="Grid supply failure at the site with the generator awaiting refuelling.",
                cause_category="power_failure", severity="major",
                opened_at=self.clock.hours_ago(3), eta_at=self.clock.now + timedelta(hours=4),
                resolved_at=None, status="open", affected_estimate=610,
                customer_message=(
                    "A power failure is affecting mobile coverage around Kandy. The site is "
                    "running on backup power while we restore the mains supply."
                ),
                credit_policy=None,
            )
        )
        self.add(
            OutageIncident(
                id=f"INC-{year}-0409", scope="exchange", scope_ref="EX-KUR-TOWN",
                title="Kurunegala exchange upstream carrier fault",
                cause="Upstream transit provider reported a regional capacity loss.",
                cause_category="upstream_carrier", severity="major",
                opened_at=self.clock.days_ago(4), eta_at=None,
                resolved_at=self.clock.days_ago(4) + timedelta(hours=7), status="resolved",
                affected_estimate=2400,
                customer_message="Service was restored after our transit provider repaired their link.",
                credit_policy="Automatic credit applied to affected accounts.",
            )
        )
        self.add(
            PlannedWork(
                id=f"PW-{year}-0092", scope="olt", scope_ref=central_olt,
                title="Uplink capacity upgrade, Colombo Central",
                description=(
                    "We are doubling the uplink capacity serving Colombo Central to remove the "
                    "evening slowdown reported on this equipment."
                ),
                window_start=self.clock.days_ahead(6).replace(hour=1, minute=0),
                window_end=self.clock.days_ahead(6).replace(hour=5, minute=0),
                notice_sent=True,
                expected_impact="Up to thirty minutes of lost service inside the window.",
            )
        )
        self.add(
            PlannedWork(
                id=f"PW-{year}-0093", scope="exchange", scope_ref="EX-GAL-FORT",
                title="Galle Fort exchange power maintenance",
                description="Annual generator and battery testing at the Galle Fort exchange.",
                window_start=self.clock.days_ahead(11).replace(hour=2, minute=0),
                window_end=self.clock.days_ahead(11).replace(hour=4, minute=30),
                notice_sent=True,
                expected_impact="Brief interruption of a few minutes.",
            )
        )

    def seed_work_orders(self) -> None:
        for subscriber_id, kind, status, note in (
            ("SUB-100006", "cpe_swap", "scheduled",
             "Router unreachable and showing a solid red power light. Replacement authorised."),
            ("SUB-100002", "repair", "raised",
             "Line down at the premises. Held pending the outage on the feeder clearing."),
        ):
            circuit = next(
                (r for r in self.rows if isinstance(r, Circuit) and r.subscriber_id == subscriber_id), None
            )
            slot = next(
                (
                    r
                    for r in self.rows
                    if isinstance(r, AppointmentSlot)
                    and r.booked < r.capacity
                    and r.slot_date >= self.clock.date_ahead(1)
                ),
                None,
            )
            technician = next(
                (r for r in self.rows if isinstance(r, Technician) and r.availability == "available"), None
            )
            scheduled = status == "scheduled"
            self.add(
                WorkOrder(
                    id=f"WO-{self.clock.today.year}-{self._next('work_order', 4400):06d}",
                    subscriber_id=subscriber_id,
                    circuit_id=circuit.id if circuit else None,
                    ticket_ref=None,
                    kind=kind,
                    status=status,
                    priority="high",
                    raised_at=self.clock.hours_ago(11),
                    scheduled_slot_id=slot.id if (slot and scheduled) else None,
                    assigned_technician_id=technician.id if (technician and scheduled) else None,
                    sla_due_at=self.clock.days_ahead(2),
                    completed_at=None,
                    resolution_code=None,
                    notes=note,
                )
            )

    def seed_goodwill_history(self) -> None:
        self.add(
            CreditNote(
                id=f"CRN-{self._next('credit_note'):06d}",
                account_id=next(
                    r.id for r in self.rows if isinstance(r, BillingAccount) and r.subscriber_id == "SUB-100007"
                ),
                amount_lkr=2850.0,
                reason_code="outage_credit",
                reason_text="Service credit for the transit provider outage in the previous quarter.",
                issued_at=self.clock.days_ago(52),
                issued_by="lead02",
                ticket_ref=None,
            )
        )

    def run(self, subscriber_count: int = 400) -> dict[str, int]:
        self.seed_reference()
        self.seed_network()
        self.seed_field_ops()
        self.seed_personas()
        self.seed_bulk(max(0, subscriber_count - 8))
        self.seed_incidents()
        self.seed_work_orders()
        self.seed_goodwill_history()
        counts: dict[str, int] = {}
        for row in self.rows:
            counts[type(row).__name__] = counts.get(type(row).__name__, 0) + 1
        return counts
