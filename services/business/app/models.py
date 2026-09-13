"""The mock telco, ported from v2 cst2/orgdata/schema.py.

Every table lives in the Neon `org` schema: MetaData(schema="org") qualifies each table and
every unqualified ForeignKey target, because search_path does not pass through the pooler.

Changes from v2: line_metric and usage moved to TimescaleDB (see app/telemetry.py), the v1
customer link is gone, and customer_link, order, sim_clock and active_fault are new.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "org"


class OrgBase(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


# -- commercial ---------------------------------------------------------------------------


class Subscriber(OrgBase):
    __tablename__ = "subscriber"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # SUB-100234
    full_name: Mapped[str] = mapped_column(String)
    preferred_name: Mapped[str | None] = mapped_column(String, nullable=True)
    nic_masked: Mapped[str] = mapped_column(String)
    msisdn: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    segment: Mapped[str] = mapped_column(String, default="consumer")  # consumer|sme|enterprise|vip
    language_pref: Mapped[str] = mapped_column(String, default="en")
    preferred_channel: Mapped[str] = mapped_column(String, default="web_portal")
    joined_on: Mapped[date] = mapped_column(Date)
    service_address_id: Mapped[str | None] = mapped_column(
        ForeignKey("service_address.id"), nullable=True
    )
    marketing_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: True for simulated population; real sign-ups are False and excluded from random faults.
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    #: autopay | on_time | late | never (simulated payment behaviour)
    pay_profile: Mapped[str] = mapped_column(String, default="on_time")
    #: light | median | heavy (usage behaviour)
    usage_profile: Mapped[str] = mapped_column(String, default="median")


class BillingAccount(OrgBase):
    __tablename__ = "billing_account"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # ACC-4471209
    subscriber_id: Mapped[str] = mapped_column(ForeignKey("subscriber.id"), index=True)
    currency: Mapped[str] = mapped_column(String, default="LKR")
    billing_cycle_day: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String, default="current")  # current|overdue|suspended|terminated
    dunning_stage: Mapped[str] = mapped_column(String, default="none")
    credit_limit: Mapped[float] = mapped_column(Float, default=25000.0)
    outstanding_balance: Mapped[float] = mapped_column(Float, default=0.0)
    autopay_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    opened_on: Mapped[date] = mapped_column(Date)
    #: Charges (a late fee) waiting for the next invoice.
    pending_charges_lkr: Mapped[float] = mapped_column(Float, default=0.0)


class PlanCatalogue(OrgBase):
    __tablename__ = "plan_catalogue"

    code: Mapped[str] = mapped_column(String, primary_key=True)  # FIBREMAX-300
    family: Mapped[str] = mapped_column(String)
    display_name: Mapped[str] = mapped_column(String)
    tier: Mapped[str] = mapped_column(String)
    technology: Mapped[str] = mapped_column(String)  # gpon|adsl|fwa|lte
    monthly_price_lkr: Mapped[float] = mapped_column(Float)
    data_cap_gb: Mapped[float] = mapped_column(Float, default=-1.0)  # -1 uncapped
    speed_down_mbps: Mapped[int] = mapped_column(Integer)
    speed_up_mbps: Mapped[int] = mapped_column(Integer)
    fup_threshold_pct: Mapped[float] = mapped_column(Float, default=90.0)
    fup_shaped_mbps: Mapped[int] = mapped_column(Integer, default=2)
    contract_months: Mapped[int] = mapped_column(Integer, default=12)
    early_exit_fee_lkr: Mapped[float] = mapped_column(Float, default=0.0)
    sla_tier: Mapped[str] = mapped_column(String, default="standard")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    #: Shown on the public plans page and at onboarding.
    sellable: Mapped[bool] = mapped_column(Boolean, default=True)


class Subscription(OrgBase):
    __tablename__ = "subscription"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # SVC-880031
    subscriber_id: Mapped[str] = mapped_column(ForeignKey("subscriber.id"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("billing_account.id"), index=True)
    plan_code: Mapped[str] = mapped_column(ForeignKey("plan_catalogue.code"))
    status: Mapped[str] = mapped_column(String, default="active")
    activated_on: Mapped[date] = mapped_column(Date)
    contract_ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    suspended_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    suspension_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    renewal_date: Mapped[date] = mapped_column(Date)


class Addon(OrgBase):
    __tablename__ = "addon"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    subscription_id: Mapped[str] = mapped_column(ForeignKey("subscription.id"), index=True)
    code: Mapped[str] = mapped_column(String)
    display_name: Mapped[str] = mapped_column(String)
    monthly_price_lkr: Mapped[float] = mapped_column(Float, default=0.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    added_on: Mapped[date] = mapped_column(Date)


class Entitlement(OrgBase):
    __tablename__ = "entitlement"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    subscriber_id: Mapped[str] = mapped_column(ForeignKey("subscriber.id"), index=True)
    code: Mapped[str] = mapped_column(String)
    display_name: Mapped[str] = mapped_column(String)
    granted: Mapped[bool] = mapped_column(Boolean, default=True)
    limit_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    limit_unit: Mapped[str | None] = mapped_column(String, nullable=True)


class SlaTier(OrgBase):
    __tablename__ = "sla_tier"

    tier: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String)
    first_response_mins: Mapped[int] = mapped_column(Integer)
    resolution_mins: Mapped[int] = mapped_column(Integer)
    credit_pct_on_breach: Mapped[float] = mapped_column(Float, default=0.0)
    priority_boost: Mapped[int] = mapped_column(Integer, default=0)


# -- billing ------------------------------------------------------------------------------


class Invoice(OrgBase):
    __tablename__ = "invoice"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # INV-2026-000112
    account_id: Mapped[str] = mapped_column(ForeignKey("billing_account.id"))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    issued_on: Mapped[date] = mapped_column(Date)
    due_on: Mapped[date] = mapped_column(Date)
    subtotal_lkr: Mapped[float] = mapped_column(Float, default=0.0)
    tax_lkr: Mapped[float] = mapped_column(Float, default=0.0)
    total_lkr: Mapped[float] = mapped_column(Float, default=0.0)
    paid_lkr: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String, default="unpaid")  # paid|unpaid|partial|overdue|void

    __table_args__ = (Index("ix_invoice_account_issued", "account_id", "issued_on"),)


class InvoiceLine(OrgBase):
    __tablename__ = "invoice_line"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoice.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String, default="subscription")
    quantity: Mapped[float] = mapped_column(Float, default=1.0)
    unit_price_lkr: Mapped[float] = mapped_column(Float, default=0.0)
    amount_lkr: Mapped[float] = mapped_column(Float, default=0.0)
    is_unusual: Mapped[bool] = mapped_column(Boolean, default=False)
    unusual_reason: Mapped[str | None] = mapped_column(String, nullable=True)


class Payment(OrgBase):
    __tablename__ = "payment"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("billing_account.id"))
    invoice_id: Mapped[str | None] = mapped_column(ForeignKey("invoice.id"), nullable=True)
    amount_lkr: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String, default="card")
    reference: Mapped[str] = mapped_column(String)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String, default="settled")  # settled|pending|failed|reversed
    failure_reason: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (Index("ix_payment_account_posted", "account_id", "posted_at"),)


class LedgerEntry(OrgBase):
    __tablename__ = "ledger_entry"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("billing_account.id"))
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    description: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)  # invoice|payment|credit|adjustment|late_fee|reversal
    debit_lkr: Mapped[float] = mapped_column(Float, default=0.0)
    credit_lkr: Mapped[float] = mapped_column(Float, default=0.0)
    balance_after_lkr: Mapped[float] = mapped_column(Float, default=0.0)
    reference: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (Index("ix_ledger_account_posted", "account_id", "posted_at"),)


class CreditNote(OrgBase):
    __tablename__ = "credit_note"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("billing_account.id"))
    amount_lkr: Mapped[float] = mapped_column(Float)
    reason_code: Mapped[str] = mapped_column(String)
    reason_text: Mapped[str] = mapped_column(String)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    issued_by: Mapped[str] = mapped_column(String, default="system")
    ticket_ref: Mapped[str | None] = mapped_column(String, nullable=True)


class DunningEvent(OrgBase):
    __tablename__ = "dunning_event"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("billing_account.id"))
    stage: Mapped[str] = mapped_column(String)  # reminder|final_notice|restrict|suspend|terminate|restored
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    channel: Mapped[str] = mapped_column(String, default="sms")
    amount_at_time_lkr: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (Index("ix_dunning_account_at", "account_id", "occurred_at"),)


# -- network ------------------------------------------------------------------------------


class ServiceAddress(OrgBase):
    __tablename__ = "service_address"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    line1: Mapped[str] = mapped_column(String)
    line2: Mapped[str | None] = mapped_column(String, nullable=True)
    city: Mapped[str] = mapped_column(String)
    district: Mapped[str] = mapped_column(String)
    postcode: Mapped[str | None] = mapped_column(String, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    exchange_code: Mapped[str | None] = mapped_column(ForeignKey("exchange.code"), nullable=True)
    density: Mapped[str] = mapped_column(String, default="urban")

    def one_line(self) -> str:
        return ", ".join(p for p in (self.line1, self.line2, self.city, self.district) if p)


class Exchange(OrgBase):
    __tablename__ = "exchange"

    code: Mapped[str] = mapped_column(String, primary_key=True)  # EX-CMB-CENTRAL
    name: Mapped[str] = mapped_column(String)
    region: Mapped[str] = mapped_column(String)
    district: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="operational")
    commissioned_on: Mapped[date] = mapped_column(Date)


class Olt(OrgBase):
    __tablename__ = "olt"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # OLT-CMBCE-01
    exchange_code: Mapped[str] = mapped_column(ForeignKey("exchange.code"))
    vendor: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)
    firmware: Mapped[str] = mapped_column(String)
    port_count: Mapped[int] = mapped_column(Integer, default=128)
    uplink_status: Mapped[str] = mapped_column(String, default="up")  # up|degraded|down|maintenance
    uplink_utilisation_pct: Mapped[float] = mapped_column(Float, default=40.0)
    uplink_capacity_gbps: Mapped[float] = mapped_column(Float, default=10.0)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Splitter(OrgBase):
    __tablename__ = "splitter"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    olt_id: Mapped[str] = mapped_column(ForeignKey("olt.id"))
    ratio: Mapped[str] = mapped_column(String, default="1:32")
    location_note: Mapped[str] = mapped_column(String, default="")
    condition: Mapped[str] = mapped_column(String, default="healthy")  # healthy|degraded|faulty
    installed_on: Mapped[date] = mapped_column(Date)


class CellSite(OrgBase):
    __tablename__ = "cell_site"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    region: Mapped[str] = mapped_column(String)
    district: Mapped[str] = mapped_column(String)
    technologies: Mapped[list] = mapped_column(JSON, default=list)
    sector_count: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[str] = mapped_column(String, default="on_air")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)


class Circuit(OrgBase):
    __tablename__ = "circuit"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # CIR-9930014
    subscription_id: Mapped[str] = mapped_column(ForeignKey("subscription.id"))
    subscriber_id: Mapped[str] = mapped_column(ForeignKey("subscriber.id"), index=True)
    technology: Mapped[str] = mapped_column(String)
    olt_id: Mapped[str | None] = mapped_column(ForeignKey("olt.id"), nullable=True, index=True)
    splitter_id: Mapped[str | None] = mapped_column(ForeignKey("splitter.id"), nullable=True)
    cell_site_id: Mapped[str | None] = mapped_column(ForeignKey("cell_site.id"), nullable=True)
    port: Mapped[str | None] = mapped_column(String, nullable=True)
    provisioned_down_mbps: Mapped[int] = mapped_column(Integer, default=100)
    provisioned_up_mbps: Mapped[int] = mapped_column(Integer, default=50)
    status: Mapped[str] = mapped_column(String, default="in_service")
    line_state: Mapped[str] = mapped_column(String, default="up")  # up|down|syncing|shaped
    last_state_change: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    activated_on: Mapped[date] = mapped_column(Date)


class DeviceModelCatalogue(OrgBase):
    __tablename__ = "device_model"

    model: Mapped[str] = mapped_column(String, primary_key=True)
    vendor: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String, default="router")
    technologies: Mapped[list] = mapped_column(JSON, default=list)
    supports_wifi6: Mapped[bool] = mapped_column(Boolean, default=False)
    lan_ports: Mapped[int] = mapped_column(Integer, default=4)
    led_semantics: Mapped[list] = mapped_column(JSON, default=list)
    latest_firmware: Mapped[str] = mapped_column(String, default="1.0.0")
    known_issues: Mapped[list] = mapped_column(JSON, default=list)
    replacement_model: Mapped[str | None] = mapped_column(String, nullable=True)
    port_layout: Mapped[list] = mapped_column(JSON, default=list)
    remedies: Mapped[dict] = mapped_column(JSON, default=dict)


class CpeDevice(OrgBase):
    __tablename__ = "cpe_device"

    serial: Mapped[str] = mapped_column(String, primary_key=True)
    circuit_id: Mapped[str] = mapped_column(ForeignKey("circuit.id"))
    subscriber_id: Mapped[str] = mapped_column(ForeignKey("subscriber.id"), index=True)
    model: Mapped[str] = mapped_column(ForeignKey("device_model.model"))
    mac: Mapped[str] = mapped_column(String)
    firmware_version: Mapped[str] = mapped_column(String)
    wan_status: Mapped[str] = mapped_column(String, default="online")
    uptime_s: Mapped[int] = mapped_column(Integer, default=0)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lan_clients: Mapped[int] = mapped_column(Integer, default=0)
    wifi_channel: Mapped[int] = mapped_column(Integer, default=6)
    wifi_band_steering: Mapped[bool] = mapped_column(Boolean, default=True)
    reboot_count_7d: Mapped[int] = mapped_column(Integer, default=0)
    owned_by_operator: Mapped[bool] = mapped_column(Boolean, default=True)
    installed_on: Mapped[date] = mapped_column(Date)


class OutageIncident(OrgBase):
    __tablename__ = "outage_incident"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    scope: Mapped[str] = mapped_column(String)  # national|region|district|exchange|olt|splitter|cell_site
    scope_ref: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    cause: Mapped[str] = mapped_column(String)
    cause_category: Mapped[str] = mapped_column(String, default="equipment_fault")
    severity: Mapped[str] = mapped_column(String, default="major")
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    eta_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String, default="open")
    affected_estimate: Mapped[int] = mapped_column(Integer, default=0)
    customer_message: Mapped[str] = mapped_column(Text, default="")
    credit_policy: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (Index("ix_outage_scope", "scope", "scope_ref", "status"),)


class PlannedWork(OrgBase):
    __tablename__ = "planned_work"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    scope: Mapped[str] = mapped_column(String)
    scope_ref: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notice_sent: Mapped[bool] = mapped_column(Boolean, default=True)
    expected_impact: Mapped[str] = mapped_column(String, default="brief loss of service")


# -- field operations ---------------------------------------------------------------------


class Technician(OrgBase):
    __tablename__ = "technician"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    full_name: Mapped[str] = mapped_column(String)
    region: Mapped[str] = mapped_column(String)
    district: Mapped[str] = mapped_column(String)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    shift: Mapped[str] = mapped_column(String, default="day")
    availability: Mapped[str] = mapped_column(String, default="available")
    rating: Mapped[float] = mapped_column(Float, default=4.5)


class AppointmentSlot(OrgBase):
    __tablename__ = "appointment_slot"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    slot_date: Mapped[date] = mapped_column(Date)
    window: Mapped[str] = mapped_column(String)
    window_start_hour: Mapped[int] = mapped_column(Integer, default=9)
    window_end_hour: Mapped[int] = mapped_column(Integer, default=12)
    district: Mapped[str] = mapped_column(String)
    capacity: Mapped[int] = mapped_column(Integer, default=6)
    booked: Mapped[int] = mapped_column(Integer, default=0)
    skill_required: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (Index("ix_slot_district_date", "district", "slot_date"),)


class WorkOrder(OrgBase):
    __tablename__ = "work_order"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    subscriber_id: Mapped[str] = mapped_column(ForeignKey("subscriber.id"))
    circuit_id: Mapped[str | None] = mapped_column(ForeignKey("circuit.id"), nullable=True)
    ticket_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    kind: Mapped[str] = mapped_column(String, default="repair")
    status: Mapped[str] = mapped_column(String, default="raised")
    priority: Mapped[str] = mapped_column(String, default="normal")
    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    scheduled_slot_id: Mapped[str | None] = mapped_column(
        ForeignKey("appointment_slot.id"), nullable=True
    )
    assigned_technician_id: Mapped[str | None] = mapped_column(
        ForeignKey("technician.id"), nullable=True
    )
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_code: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (Index("ix_work_order_subscriber", "subscriber_id", "status"),)


# -- support history ----------------------------------------------------------------------


class Interaction(OrgBase):
    __tablename__ = "interaction"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    subscriber_id: Mapped[str] = mapped_column(ForeignKey("subscriber.id"), index=True)
    channel: Mapped[str] = mapped_column(String)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    direction: Mapped[str] = mapped_column(String, default="inbound")
    summary: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    handled_by: Mapped[str | None] = mapped_column(String, nullable=True)


class PriorTicket(OrgBase):
    __tablename__ = "prior_ticket"

    ref: Mapped[str] = mapped_column(String, primary_key=True)
    subscriber_id: Mapped[str] = mapped_column(ForeignKey("subscriber.id"), index=True)
    department: Mapped[str] = mapped_column(String)
    intent: Mapped[str] = mapped_column(String)
    fault: Mapped[str | None] = mapped_column(String, nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_code: Mapped[str | None] = mapped_column(String, nullable=True)
    resolution_note: Mapped[str] = mapped_column(Text, default="")
    action_taken: Mapped[str | None] = mapped_column(String, nullable=True)
    csat: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reopened: Mapped[bool] = mapped_column(Boolean, default=False)


class KnownIssue(OrgBase):
    __tablename__ = "known_issue"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    applies_to_models: Mapped[list] = mapped_column(JSON, default=list)
    applies_to_faults: Mapped[list] = mapped_column(JSON, default=list)
    symptom: Mapped[str] = mapped_column(Text)
    workaround: Mapped[str] = mapped_column(Text, default="")
    permanent_fix: Mapped[str | None] = mapped_column(Text, nullable=True)
    open_since: Mapped[date] = mapped_column(Date)
    resolved_on: Mapped[date | None] = mapped_column(Date, nullable=True)


# -- v3: accounts, orders, simulation ------------------------------------------------------


class CustomerLink(OrgBase):
    """Better Auth user id to subscriber. The gateway caches this in Valkey."""

    __tablename__ = "customer_link"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    subscriber_id: Mapped[str] = mapped_column(ForeignKey("subscriber.id"), unique=True)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    linked_by: Mapped[str] = mapped_column(String, default="self")


class Order(OrgBase):
    __tablename__ = "order"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # ORD-000123
    user_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String, default="new_service")  # new_service|plan_change
    plan_code: Mapped[str] = mapped_column(ForeignKey("plan_catalogue.code"))
    full_name: Mapped[str] = mapped_column(String, default="")
    email: Mapped[str] = mapped_column(String, default="")
    language: Mapped[str] = mapped_column(String, default="en")
    address_line: Mapped[str] = mapped_column(String, default="")
    intent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    district: Mapped[str | None] = mapped_column(String, nullable=True)
    city: Mapped[str | None] = mapped_column(String, nullable=True)
    exchange_code: Mapped[str | None] = mapped_column(ForeignKey("exchange.code"), nullable=True)
    subscriber_id: Mapped[str | None] = mapped_column(String, nullable=True)
    amount_lkr: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String, default="pending_payment")  # pending_payment|provisioning|active|cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OrderSite(OrgBase):
    """Where and when to install a new service: what the installer needs beyond the address line."""

    __tablename__ = "order_site"

    order_id: Mapped[str] = mapped_column(ForeignKey("order.id"), primary_key=True)
    landmark: Mapped[str] = mapped_column(String, default="")
    phone: Mapped[str] = mapped_column(String, default="")
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    install_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    install_slot: Mapped[str] = mapped_column(String, default="")  # morning|afternoon|evening


class SimClock(OrgBase):
    """Single row. sim_now = anchor_sim + (wall - anchor_wall) * speed.

    Every control (pause, speed, advance) re-anchors at the current sim instant, so sim time
    only ever moves forward.
    """

    __tablename__ = "sim_clock"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    speed: Mapped[float] = mapped_column(Float, default=1.0)  # 0 = paused
    anchor_wall: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    anchor_sim: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    #: Sim instant the last business-sim tick covered up to.
    last_tick_sim: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ActiveFault(OrgBase):
    """A scenario or random fault currently overriding telemetry for a target."""

    __tablename__ = "active_fault"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String)  # scenario name or random fault kind
    target_kind: Mapped[str] = mapped_column(String)  # subscriber|olt|cell_site|exchange
    target_ref: Mapped[str] = mapped_column(String, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    eta_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String, default="operator")  # operator|random
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class SimEvent(OrgBase):
    """Audit of every injection, tick-level state change and clock move."""

    __tablename__ = "sim_event_log"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String)
    target: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor: Mapped[str] = mapped_column(String, default="sim")
    note: Mapped[str] = mapped_column(String, default="")
