"""The 18 typed, read-only tools over the mock telco. Ported from v2 cst2/orgdata/tools.py.

v3 change: each tool is a pure function over (Snapshot, World, now) instead of a series of
session queries, and `now` is the sim clock. Behaviour and payloads are otherwise v2's:

1. Every result carries `found`. A miss is a payload, never an exception.
2. Every money, data, speed and date value ships a pre-formatted `_display` sibling.
3. Causal relationships are pre-computed booleans, never left to the model to infer.

Docstrings double as tool descriptions a model reads.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app import formatting as fmt
from app.models import Subscription
from app.world import COLOMBO, Snapshot, World
from lanka_common.punctuation import normalise_deep

SLA_AT_RISK_FRACTION = 0.25
OPEN_INCIDENT = ("open", "mitigating", "monitoring")


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    group: str
    description: str
    args: tuple[str, ...]
    fn: Callable[..., dict[str, Any]]


REGISTRY: dict[str, ToolSpec] = {}


def tool(name: str, group: str, *args: str) -> Callable:
    def wrap(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        REGISTRY[name] = ToolSpec(name, group, (fn.__doc__ or "").strip(), args, fn)
        return fn

    return wrap


def available_tools() -> list[str]:
    return sorted(REGISTRY)


def not_found(ref: str, what: str = "customer") -> dict[str, Any]:
    return {
        "found": False,
        "reference": ref,
        "error": f"No {what} matches that reference in the operator records.",
    }


def call(
    name: str, snap: Snapshot | None, world: World, now: datetime, **kwargs: Any
) -> dict[str, Any]:
    """Run one tool. Raises only for an unknown tool; a missing customer is a payload."""
    spec = REGISTRY.get(name)
    if spec is None:
        raise KeyError(f"unknown organisational data tool: {name}")
    if snap is None and "subscriber_ref" in spec.args:
        return not_found(str(kwargs.get("subscriber_ref", "")))
    kwargs.pop("subscriber_ref", None)
    return normalise_deep(spec.fn(snap, world, _aware(now), **kwargs))


def _cycle_start(subscription: Subscription, today: date) -> date:
    start = subscription.renewal_date - timedelta(days=30)
    while start > today:
        start -= timedelta(days=30)
    return start


def _unpaid(snap: Snapshot) -> list:
    return sorted(
        (i for i in snap.invoices if i.status in ("unpaid", "overdue")), key=lambda i: i.due_on
    )


def _latest(rows: list, key: str):
    return max(rows, key=lambda r: _aware(getattr(r, key)), default=None)


# -- identity -----------------------------------------------------------------------------


@tool("get_subscriber_profile", "identity", "subscriber_ref")
def get_subscriber_profile(snap: Snapshot, world: World, now: datetime) -> dict[str, Any]:
    """Look up who the customer is: name, segment, service address, plan and account state.

    Call this first for every request, whatever the topic. It lets a reply open with the
    customer's name and confirm you are looking at the right account.
    """
    s, account, subscription, address = snap.subscriber, snap.account, snap.subscription, snap.address
    plan = world.plans.get(subscription.plan_code) if subscription else None
    exchange = world.exchanges.get(address.exchange_code or "") if address else None
    tenure_days = (now.date() - s.joined_on).days

    return {
        "found": True,
        "subscriber_id": s.id,
        "name": s.full_name,
        "preferred_name": s.preferred_name or s.full_name.split()[0],
        "segment": s.segment,
        "segment_display": fmt.titlecase_code(s.segment),
        "language_preference": s.language_pref,
        "preferred_channel": s.preferred_channel,
        "msisdn": s.msisdn,
        "email": s.email,
        "nic_masked": s.nic_masked,
        "customer_since": s.joined_on.isoformat(),
        "customer_since_display": fmt.day(s.joined_on),
        "tenure_years_display": f"{tenure_days / 365.25:.1f} years",
        "account_id": account.id if account else None,
        "account_status": account.status if account else None,
        "subscription_id": subscription.id if subscription else None,
        "subscription_status": subscription.status if subscription else None,
        "plan_code": plan.code if plan else None,
        "plan_name": plan.display_name if plan else None,
        "plan_tier": plan.tier if plan else None,
        "service_address": address.one_line() if address else None,
        "district": address.district if address else None,
        "exchange": exchange.name if exchange else None,
        "exchange_code": exchange.code if exchange else None,
        "internal_note": s.notes,
        "account_active": bool(account and account.status == "current"),
        "service_suspended": bool(subscription and subscription.status == "suspended"),
        "is_long_standing_customer": tenure_days > 365 * 3,
        "is_priority_customer": s.segment in ("vip", "enterprise"),
    }


# -- commercial ---------------------------------------------------------------------------


@tool("get_payment_status", "commercial", "subscriber_ref")
def get_payment_status(snap: Snapshot, world: World, now: datetime) -> dict[str, Any]:
    """Check whether the account is paid, overdue or suspended, and what is owed.

    Use this for every billing question, and ALSO for every connectivity problem. An account
    barred for an unpaid balance is the most common reason a working line stops working;
    suspended_for_nonpayment answers that directly.
    """
    account, subscription = snap.account, snap.subscription
    if account is None:
        return not_found(snap.subscriber.id, "billing account")

    overdue = _unpaid(snap)
    oldest_due = overdue[0].due_on if overdue else None
    days_overdue = (now.date() - oldest_due).days if oldest_due else 0
    last_payment = _latest([p for p in snap.payments if p.status == "settled"], "posted_at")
    failed = _latest([p for p in snap.payments if p.status == "failed"], "posted_at")
    last_dunning = _latest(snap.dunning, "occurred_at")

    suspended = bool(subscription and subscription.status == "suspended")
    for_nonpayment = suspended and account.status in ("suspended", "overdue")

    return {
        "found": True,
        "subscriber_id": snap.subscriber.id,
        "account_id": account.id,
        "payment_status": account.status,
        "payment_status_display": fmt.titlecase_code(account.status),
        "dunning_stage": account.dunning_stage,
        "outstanding_balance": account.outstanding_balance,
        "outstanding_balance_display": fmt.money(account.outstanding_balance, account.currency),
        "credit_limit_display": fmt.money(account.credit_limit, account.currency),
        "autopay_enabled": account.autopay_enabled,
        "overdue_invoice_count": len(overdue),
        "oldest_due_date": oldest_due.isoformat() if oldest_due else None,
        "oldest_due_date_display": fmt.day(oldest_due) if oldest_due else "nothing outstanding",
        "days_overdue": max(days_overdue, 0),
        "last_payment_amount_display": (
            fmt.money(last_payment.amount_lkr) if last_payment else "no payment on record"
        ),
        "last_payment_at_display": (
            fmt.relative(last_payment.posted_at, now) if last_payment else "never"
        ),
        "last_payment_method": last_payment.method if last_payment else None,
        "last_failed_payment_reason": failed.failure_reason if failed else None,
        "last_notice_stage": last_dunning.stage if last_dunning else None,
        "last_notice_at_display": (
            fmt.relative(last_dunning.occurred_at, now) if last_dunning else "no notice sent"
        ),
        "suspension_reason": subscription.suspension_reason if subscription else None,
        "suspended_for_nonpayment": for_nonpayment,
        "is_overdue": account.status == "overdue" or bool(overdue),
        "in_grace_period": account.status == "overdue" and not suspended,
        "payment_failed_recently": bool(failed and (now - _aware(failed.posted_at)).days <= 30),
        "balance_settled": account.outstanding_balance <= 0.0,
        "service_resumes_on_payment": for_nonpayment,
    }


@tool("get_account_balance", "commercial", "subscriber_ref")
def get_account_balance(snap: Snapshot, world: World, now: datetime) -> dict[str, Any]:
    """Get the current balance and the next amount due.

    Narrower than get_payment_status. Use it when the customer asks what they owe rather than
    why something stopped working.
    """
    account = snap.account
    if account is None:
        return not_found(snap.subscriber.id, "billing account")
    unpaid = _unpaid(snap)
    nxt = unpaid[0] if unpaid else None
    latest = _latest(snap.ledger, "posted_at")
    return {
        "found": True,
        "subscriber_id": snap.subscriber.id,
        "account_id": account.id,
        "currency": account.currency,
        "outstanding_balance": account.outstanding_balance,
        "outstanding_balance_display": fmt.money(account.outstanding_balance, account.currency),
        "billing_cycle_day": account.billing_cycle_day,
        "next_due_amount_display": fmt.money(nxt.total_lkr - nxt.paid_lkr) if nxt else fmt.money(0),
        "next_due_date_display": fmt.day(nxt.due_on) if nxt else "nothing due",
        "last_ledger_entry": latest.description if latest else None,
        "last_ledger_at_display": fmt.relative(latest.posted_at, now) if latest else "never",
        "balance_settled": account.outstanding_balance <= 0.0,
        "has_amount_due": bool(nxt),
    }


@tool("get_billing_history", "commercial", "subscriber_ref", "months")
def get_billing_history(
    snap: Snapshot, world: World, now: datetime, months: int = 6
) -> dict[str, Any]:
    """List recent invoices with what was billed and what was paid.

    Use it when the customer compares this month against previous months, disputes a charge,
    or asks whether a payment was received. bill_increased says outright whether the latest
    bill is higher than the one before it.
    """
    account = snap.account
    if account is None:
        return not_found(snap.subscriber.id, "billing account")
    invoices = sorted(snap.invoices, key=lambda i: i.issued_on, reverse=True)[: max(1, min(months, 24))]
    latest = invoices[0].total_lkr if invoices else 0.0
    previous = invoices[1].total_lkr if len(invoices) > 1 else latest
    delta = round(latest - previous, 2)
    unpaid = [i for i in invoices if i.status in ("unpaid", "overdue")]
    return {
        "found": True,
        "subscriber_id": snap.subscriber.id,
        "account_id": account.id,
        "invoice_count": len(invoices),
        "invoices": [
            {
                "invoice_no": i.id,
                "period_display": f"{fmt.day(i.period_start)} to {fmt.day(i.period_end)}",
                "issued_display": fmt.day(i.issued_on),
                "due_display": fmt.day(i.due_on),
                "total": i.total_lkr,
                "total_display": fmt.money(i.total_lkr),
                "paid_display": fmt.money(i.paid_lkr),
                "status": i.status,
                "status_display": fmt.titlecase_code(i.status),
            }
            for i in invoices
        ],
        "latest_total_display": fmt.money(latest),
        "previous_total_display": fmt.money(previous),
        "change_display": (
            f"{fmt.money(abs(delta))} {'higher' if delta > 0 else 'lower'} than last month"
            if delta
            else "the same as last month"
        ),
        "unpaid_total_display": fmt.money(sum(i.total_lkr - i.paid_lkr for i in unpaid)),
        "bill_increased": delta > 0.01,
        "bill_decreased": delta < -0.01,
        "has_unpaid_invoice": bool(unpaid),
    }


@tool("get_last_invoice_breakdown", "commercial", "subscriber_ref")
def get_last_invoice_breakdown(snap: Snapshot, world: World, now: datetime) -> dict[str, Any]:
    """Break the most recent invoice into its individual lines.

    This answers "why was I charged extra this month". Any line flagged is_unusual carries a
    reason, which is the fact the reply should quote.
    """
    if snap.account is None:
        return not_found(snap.subscriber.id, "billing account")
    invoice = max(snap.invoices, key=lambda i: i.issued_on, default=None)
    if invoice is None:
        return not_found(snap.subscriber.id, "invoice")
    lines = sorted(snap.invoice_lines.get(invoice.id, []), key=lambda line: line.line_no)
    unusual = [line for line in lines if line.is_unusual]
    return {
        "found": True,
        "subscriber_id": snap.subscriber.id,
        "invoice_no": invoice.id,
        "period_display": f"{fmt.day(invoice.period_start)} to {fmt.day(invoice.period_end)}",
        "issued_display": fmt.day(invoice.issued_on),
        "due_display": fmt.day(invoice.due_on),
        "status": invoice.status,
        "subtotal_display": fmt.money(invoice.subtotal_lkr),
        "tax_display": fmt.money(invoice.tax_lkr),
        "total_display": fmt.money(invoice.total_lkr),
        "outstanding_on_invoice_display": fmt.money(invoice.total_lkr - invoice.paid_lkr),
        "lines": [
            {
                "description": line.description,
                "category": line.category,
                "quantity": line.quantity,
                "amount": line.amount_lkr,
                "amount_display": fmt.money(line.amount_lkr),
                "is_unusual": line.is_unusual,
                "unusual_reason": line.unusual_reason,
            }
            for line in lines
        ],
        "unusual_charges": [
            {
                "description": line.description,
                "amount_display": fmt.money(line.amount_lkr),
                "reason": line.unusual_reason,
            }
            for line in unusual
        ],
        "unusual_total_display": fmt.money(sum(line.amount_lkr for line in unusual)),
        "has_unusual_charge": bool(unusual),
        "is_fully_paid": invoice.status == "paid",
    }


@tool("get_ledger_window", "commercial", "subscriber_ref", "days")
def get_ledger_window(
    snap: Snapshot, world: World, now: datetime, days: int = 120
) -> dict[str, Any]:
    """Show the running account ledger, every debit and credit in order.

    Use this for a disputed charge where the customer says a payment was made but is not
    reflected. Never confirm or deny a charge without reading the ledger first.
    """
    account = snap.account
    if account is None:
        return not_found(snap.subscriber.id, "billing account")
    since = now - timedelta(days=max(1, min(days, 730)))
    entries = sorted(
        (e for e in snap.ledger if _aware(e.posted_at) >= since),
        key=lambda e: _aware(e.posted_at),
        reverse=True,
    )[:60]
    return {
        "found": True,
        "subscriber_id": snap.subscriber.id,
        "account_id": account.id,
        "window_display": f"the last {days} days",
        "entry_count": len(entries),
        "entries": [
            {
                "posted_display": fmt.day(e.posted_at),
                "description": e.description,
                "kind": e.kind,
                "debit_display": fmt.money(e.debit_lkr) if e.debit_lkr else "",
                "credit_display": fmt.money(e.credit_lkr) if e.credit_lkr else "",
                "balance_after_display": fmt.money(e.balance_after_lkr),
                "reference": e.reference,
            }
            for e in entries
        ],
        "closing_balance_display": fmt.money(account.outstanding_balance),
        "has_recent_payment": any(e.kind == "payment" for e in entries),
        "has_recent_credit": any(e.kind == "credit" for e in entries),
    }


@tool("get_plan_and_entitlements", "commercial", "subscriber_ref")
def get_plan_and_entitlements(snap: Snapshot, world: World, now: datetime) -> dict[str, Any]:
    """Get the current plan, its speeds and allowance, add-ons, and what the customer is
    entitled to.

    Use it for upgrade, downgrade and cancellation questions. at_top_of_catalogue says when
    there is nothing faster to sell, so the honest answer is that they already have the best
    plan rather than an invented upgrade.
    """
    subscription = snap.subscription
    if subscription is None:
        return not_found(snap.subscriber.id, "subscription")
    plan = world.plans.get(subscription.plan_code)
    catalogue = sorted((p for p in world.plans.values() if p.active), key=lambda p: p.sort_order)
    faster = [
        p
        for p in catalogue
        if p.speed_down_mbps > (plan.speed_down_mbps if plan else 0) and p.family != "BizFibre"
    ]
    sla = world.sla.get(plan.sla_tier) if plan else None
    left = (subscription.contract_ends_on - now.date()).days if subscription.contract_ends_on else None
    ents = snap.entitlements
    addons = [a for a in snap.addons if a.active]

    return {
        "found": True,
        "subscriber_id": snap.subscriber.id,
        "subscription_id": subscription.id,
        "subscription_status": subscription.status,
        "plan_code": plan.code if plan else None,
        "plan_name": plan.display_name if plan else None,
        "plan_tier": plan.tier if plan else None,
        "technology_display": fmt.titlecase_code(plan.technology) if plan else None,
        "monthly_price_display": fmt.money(plan.monthly_price_lkr) if plan else None,
        "data_cap_display": fmt.data_volume(plan.data_cap_gb) if plan else None,
        "download_speed_display": fmt.speed(plan.speed_down_mbps) if plan else None,
        "upload_speed_display": fmt.speed(plan.speed_up_mbps) if plan else None,
        "renewal_date_display": fmt.day(subscription.renewal_date),
        "contract_ends_display": (
            fmt.day(subscription.contract_ends_on) if subscription.contract_ends_on else "no minimum term"
        ),
        "early_exit_fee_display": fmt.money(plan.early_exit_fee_lkr) if plan else None,
        "sla_tier": plan.sla_tier if plan else None,
        "sla_display": sla.display_name if sla else None,
        "addons": [
            {"code": a.code, "name": a.display_name, "price_display": fmt.money(a.monthly_price_lkr)}
            for a in addons
        ],
        "addons_display": fmt.sentence_list([a.display_name for a in addons]),
        "entitlements": [
            {
                "code": e.code,
                "name": e.display_name,
                "granted": e.granted,
                "limit_display": (
                    fmt.money(e.limit_value)
                    if e.granted and e.limit_value and e.limit_unit == "LKR"
                    else None
                ),
            }
            for e in ents
        ],
        "granted_entitlement_codes": [e.code for e in ents if e.granted],
        "upgrade_options": [
            {
                "plan_code": p.code,
                "plan_name": p.display_name,
                "speed_display": fmt.speed(p.speed_down_mbps),
                "price_display": fmt.money(p.monthly_price_lkr),
                "data_cap_display": fmt.data_volume(p.data_cap_gb),
            }
            for p in faster[:3]
        ],
        "at_top_of_catalogue": not faster,
        "upgrade_available": bool(faster),
        "in_contract": bool(left and left > 0),
        "contract_in_notice_period": bool(left is not None and 0 < left <= 30),
        "can_change_plan_free": any(e.code == "PLAN_CHANGE_ANYTIME" and e.granted for e in ents),
    }


@tool("get_usage_summary", "commercial", "subscriber_ref", "days")
def get_usage_summary(
    snap: Snapshot, world: World, now: datetime, days: int = 30
) -> dict[str, Any]:
    """Get data used in the current billing cycle against the plan allowance.

    Use it for any complaint about slow speed as well as for plan questions: a customer past
    the fair use threshold is shaped, which is a policy outcome rather than a fault. over_fup
    and over_cap say which applies.
    """
    subscription = snap.subscription
    if subscription is None:
        return not_found(snap.subscriber.id, "subscription")
    plan = world.plans.get(subscription.plan_code)
    cap = plan.data_cap_gb if plan else -1.0
    today = now.date()
    cycle_start = _cycle_start(subscription, today)

    rows = [u for u in snap.usage if u.usage_date >= cycle_start]
    used_down = round(sum(r.down_gb for r in rows), 2)
    used_up = round(sum(r.up_gb for r in rows), 2)
    total = round(used_down + used_up, 2)

    window = [u for u in snap.usage if u.usage_date >= today - timedelta(days=max(1, min(days, 90)))]
    daily_avg = round(sum(r.down_gb + r.up_gb for r in window) / max(len(window), 1), 2)
    pct = round((total / cap) * 100, 1) if cap > 0 else 0.0
    fup = plan.fup_threshold_pct if plan else 90.0
    days_left = max((subscription.renewal_date - today).days, 0)
    projected = round(total + daily_avg * days_left, 1)
    hours = [r.peak_hour for r in window]

    return {
        "found": True,
        "subscriber_id": snap.subscriber.id,
        "subscription_id": subscription.id,
        "cycle_start_display": fmt.day(cycle_start),
        "cycle_ends_display": fmt.day(subscription.renewal_date),
        "days_left_in_cycle": days_left,
        "data_used_gb": total,
        "data_used_display": fmt.data_volume(total),
        "download_used_display": fmt.data_volume(used_down),
        "upload_used_display": fmt.data_volume(used_up),
        "data_cap_display": fmt.data_volume(cap),
        "allowance_display": fmt.data_allowance(total, cap),
        "used_percent_display": fmt.percent(pct, 1) if cap > 0 else "not applicable",
        "daily_average_display": fmt.data_volume(daily_avg) + " a day",
        "projected_cycle_total_display": fmt.data_volume(projected),
        "busiest_hour_display": f"{max(set(hours), key=hours.count)}:00" if hours else "not recorded",
        "shaped_speed_display": fmt.speed(plan.fup_shaped_mbps) if plan else None,
        "is_uncapped": cap <= 0,
        "near_cap": bool(cap > 0 and fup <= pct < 100),
        "over_cap": bool(cap > 0 and pct >= 100),
        "over_fup": bool(cap > 0 and pct >= fup),
        "projected_to_exceed_cap": bool(cap > 0 and projected > cap),
        "usage_explains_slow_speed": bool(cap > 0 and pct >= fup),
    }


# -- network ------------------------------------------------------------------------------


@tool("get_circuit_status", "network", "subscriber_ref")
def get_circuit_status(snap: Snapshot, world: World, now: datetime) -> dict[str, Any]:
    """Check whether the customer's line currently carries service.

    IMPORTANT: this reports the symptom only. Always pair it with get_payment_status and
    get_active_outages_for before explaining a loss of service, because a barred account and
    an area outage both present here as a line that is simply down.
    """
    circuit = snap.circuit
    if circuit is None:
        return not_found(snap.subscriber.id, "circuit")
    olt = world.olts.get(circuit.olt_id or "")
    splitter = world.splitters.get(circuit.splitter_id or "")
    site = world.sites.get(circuit.cell_site_id or "")
    exchange = world.exchanges.get(olt.exchange_code) if olt else None
    return {
        "found": True,
        "subscriber_id": snap.subscriber.id,
        "circuit_id": circuit.id,
        "technology_display": fmt.titlecase_code(circuit.technology),
        "circuit_status": circuit.status,
        "line_state": circuit.line_state,
        "line_state_display": fmt.titlecase_code(circuit.line_state),
        "provisioned_speed_display": (
            f"{fmt.speed(circuit.provisioned_down_mbps)} down, "
            f"{fmt.speed(circuit.provisioned_up_mbps)} up"
        ),
        "last_state_change_display": fmt.relative(circuit.last_state_change, now),
        "olt_id": circuit.olt_id,
        "olt_uplink_status": olt.uplink_status if olt else None,
        "olt_uplink_utilisation_display": fmt.percent(olt.uplink_utilisation_pct, 1) if olt else None,
        "splitter_id": circuit.splitter_id,
        "splitter_condition": splitter.condition if splitter else None,
        "cell_site_id": circuit.cell_site_id,
        "cell_site_status": site.status if site else None,
        "exchange_display": exchange.name if exchange else None,
        "service_live": circuit.status == "in_service" and circuit.line_state == "up",
        "line_down": circuit.line_state == "down",
        "line_shaped": circuit.line_state == "shaped",
        "suspended_at_network_level": circuit.status == "suspended",
        "upstream_equipment_degraded": bool(
            (olt and olt.uplink_status in ("degraded", "down"))
            or (splitter and splitter.condition != "healthy")
            or (site and site.status in ("degraded", "on_battery", "down"))
        ),
        "uplink_congested": bool(olt and olt.uplink_utilisation_pct >= 85.0),
    }


@tool("get_cpe_diagnostics", "network", "subscriber_ref")
def get_cpe_diagnostics(snap: Snapshot, world: World, now: datetime) -> dict[str, Any]:
    """Get the state of the router or ONT at the customer's premises.

    Reports reachability, uptime, restarts this week, and whether firmware is behind. Pair it
    with get_device_led_semantics when the customer describes an indicator light.
    """
    device = snap.cpe
    if device is None:
        return not_found(snap.subscriber.id, "customer equipment")
    model = world.device_models.get(device.model)
    known = [
        k for k in world.known_issues if k.resolved_on is None and device.model in (k.applies_to_models or [])
    ]
    return {
        "found": True,
        "subscriber_id": snap.subscriber.id,
        "serial": device.serial,
        "model": device.model,
        "vendor": model.vendor if model else None,
        "kind_display": fmt.titlecase_code(model.kind) if model else None,
        "firmware_version": device.firmware_version,
        "latest_firmware": model.latest_firmware if model else None,
        "wan_status": device.wan_status,
        "wan_status_display": fmt.titlecase_code(device.wan_status),
        "uptime_display": fmt.duration(device.uptime_s),
        "last_seen_display": fmt.relative(device.last_seen_at, now),
        "connected_devices": device.lan_clients,
        "wifi_channel": device.wifi_channel,
        "reboots_last_7_days": device.reboot_count_7d,
        "installed_display": fmt.day(device.installed_on),
        "operator_owned": device.owned_by_operator,
        "replacement_model": model.replacement_model if model else None,
        "known_issues": [{"id": k.id, "title": k.title, "workaround": k.workaround} for k in known],
        "cpe_online": device.wan_status == "online",
        "cpe_offline": device.wan_status in ("offline", "unreachable"),
        "firmware_behind": bool(model and device.firmware_version != model.latest_firmware),
        "reboot_loop_suspected": device.reboot_count_7d >= 8,
        "known_issue_applies": bool(known),
        "replacement_available": bool(model and model.replacement_model),
    }


@tool("get_line_quality", "network", "subscriber_ref", "hours")
def get_line_quality(
    snap: Snapshot, world: World, now: datetime, hours: int = 48
) -> dict[str, Any]:
    """Get measured line telemetry: signal, sync speed, latency, loss and error counts.

    Use this before recommending an engineer visit. A line that measures healthy but slows
    every evening is congestion upstream, not a fault at the premises.
    """
    circuit = snap.circuit
    if circuit is None:
        return not_found(snap.subscriber.id, "circuit")
    since = now - timedelta(hours=max(1, min(hours, 720)))
    samples = sorted(
        (m for m in snap.metrics if since <= _aware(m.sampled_at) <= now),
        key=lambda m: _aware(m.sampled_at),
    )
    if not samples:
        return {
            "found": True,
            "subscriber_id": snap.subscriber.id,
            "circuit_id": circuit.id,
            "sample_count": 0,
            "note": "No telemetry has been recorded for this circuit in the requested window.",
            "line_healthy": False,
            "no_telemetry": True,
        }

    def avg(values: list[float | None]) -> float:
        clean = [v for v in values if v is not None]
        return round(sum(clean) / len(clean), 2) if clean else 0.0

    def local_hour(m) -> int:
        return _aware(m.sampled_at).astimezone(COLOMBO).hour

    evening_sync = avg([s.sync_down_mbps for s in samples if 20 <= local_hour(s) <= 23])
    daytime_sync = avg([s.sync_down_mbps for s in samples if 9 <= local_hour(s) <= 17])
    provisioned = circuit.provisioned_down_mbps or 1
    mean_sync = avg([s.sync_down_mbps for s in samples])
    achieved_pct = round(mean_sync / provisioned * 100, 1)
    dead = [s for s in samples if s.packet_loss_pct >= 99.0]
    rx = avg([s.rx_power_dbm for s in samples])
    snr = avg([s.snr_db for s in samples])
    loss = avg([s.packet_loss_pct for s in samples])
    crc = int(sum(s.crc_errors for s in samples))
    resyncs = int(sum(s.resyncs for s in samples))

    congestion = bool(daytime_sync and evening_sync and evening_sync < daytime_sync * 0.6)
    healthy = bool(not dead and loss < 1.0 and crc < 200 and achieved_pct >= 80.0 and (not rx or rx > -25.0))

    return {
        "found": True,
        "subscriber_id": snap.subscriber.id,
        "circuit_id": circuit.id,
        "window_display": f"the last {hours} hours",
        "sample_count": len(samples),
        "average_sync_display": fmt.speed(mean_sync),
        "provisioned_speed_display": fmt.speed(provisioned),
        "achieved_percent_display": fmt.percent(achieved_pct, 1),
        "daytime_sync_display": fmt.speed(daytime_sync),
        "evening_sync_display": fmt.speed(evening_sync),
        "average_latency_display": f"{avg([s.latency_ms for s in samples]):.0f} ms",
        "average_jitter_display": f"{avg([s.jitter_ms for s in samples]):.0f} ms",
        "packet_loss_display": fmt.percent(loss, 2),
        "signal_display": f"{rx:.1f} dBm" if rx else "not applicable",
        "signal_to_noise_display": f"{snr:.1f} dB" if snr else "not applicable",
        "crc_errors_total": crc,
        "resyncs_total": resyncs,
        "hours_with_no_service": len(dead),
        "line_healthy": healthy,
        "no_telemetry": False,
        "line_dead_in_window": bool(dead),
        "evening_congestion": congestion,
        "signal_degraded": bool(rx and rx < -25.0),
        "high_error_rate": crc >= 200,
        "speed_below_provisioned": achieved_pct < 80.0,
        "premises_fault_likely": bool(
            not healthy and not congestion and (crc >= 200 or (rx and rx < -25.0))
        ),
    }


def _scope_refs(snap: Snapshot, world: World, *, planned: bool) -> list[tuple[str, str]]:
    """Walk the subscriber's circuit up the network, as v2 did per tool."""
    circuit, address = snap.circuit, snap.address
    refs: list[tuple[str, str]] = []
    if circuit:
        if circuit.splitter_id and not planned:
            refs.append(("splitter", circuit.splitter_id))
        if circuit.olt_id:
            refs.append(("olt", circuit.olt_id))
            olt = world.olts.get(circuit.olt_id)
            if olt:
                refs.append(("exchange", olt.exchange_code))
        if circuit.cell_site_id:
            refs.append(("cell_site", circuit.cell_site_id))
    if address:
        if planned and address.exchange_code:
            refs.append(("exchange", address.exchange_code))
        refs.append(("district", address.district))
        if not planned:
            exchange = world.exchanges.get(address.exchange_code or "")
            if exchange:
                refs.append(("exchange", exchange.code))
                refs.append(("region", exchange.region))
    if not planned:
        refs.append(("national", "ALL"))
    return refs


@tool("get_active_outages_for", "network", "subscriber_ref")
def get_active_outages_for(snap: Snapshot, world: World, now: datetime) -> dict[str, Any]:
    """Find any open incident affecting this specific customer.

    Walks the circuit up the network: splitter, OLT, exchange, district and region, or the
    cell site for mobile. outage_explains_symptom says whether an incident explains a dead
    line. When it is true, do not offer troubleshooting steps.
    """
    refs = _scope_refs(snap, world, planned=False)
    wanted = set(refs)
    incidents, seen = [], set()
    for scope, ref in refs:
        for inc in world.outages:
            if (inc.scope, inc.scope_ref) == (scope, ref) and inc.status in OPEN_INCIDENT and inc.id not in seen:
                seen.add(inc.id)
                incidents.append(inc)
    assert all((i.scope, i.scope_ref) in wanted for i in incidents)
    rendered = [
        {
            "incident_id": inc.id,
            "title": inc.title,
            "scope_display": f"{fmt.titlecase_code(inc.scope)} {inc.scope_ref}",
            "cause": inc.cause,
            "cause_category": inc.cause_category,
            "severity": inc.severity,
            "status": inc.status,
            "opened_display": fmt.relative(inc.opened_at, now),
            "eta_display": fmt.moment(_aware(inc.eta_at)) if inc.eta_at else "not yet estimated",
            "affected_customers": inc.affected_estimate,
            "customer_message": inc.customer_message,
            "credit_policy": inc.credit_policy,
        }
        for inc in incidents
    ]
    line_down = bool(snap.circuit and snap.circuit.line_state == "down")
    return {
        "found": True,
        "subscriber_id": snap.subscriber.id,
        "checked_scopes": [f"{s}:{r}" for s, r in refs],
        "incident_count": len(rendered),
        "incidents": rendered,
        "primary_incident_id": rendered[0]["incident_id"] if rendered else None,
        "primary_eta_display": rendered[0]["eta_display"] if rendered else None,
        "primary_message": rendered[0]["customer_message"] if rendered else None,
        "in_active_outage": bool(rendered),
        "outage_explains_symptom": bool(rendered and line_down),
        "outage_qualifies_for_credit": any(inc.credit_policy for inc in incidents),
        "restoration_estimated": any(inc.eta_at for inc in incidents),
    }


@tool("get_planned_work_for", "network", "subscriber_ref")
def get_planned_work_for(snap: Snapshot, world: World, now: datetime) -> dict[str, Any]:
    """Find scheduled maintenance that will affect this customer.

    Use it whenever a customer reports a problem, so a reply can mention upcoming work and a
    brief loss of service inside a notified window is not mistaken for a fault.
    """
    refs = set(_scope_refs(snap, world, planned=True))
    works = sorted(
        {
            w.id: w
            for w in world.planned
            if (w.scope, w.scope_ref) in refs and _aware(w.window_end) >= now
        }.values(),
        key=lambda w: _aware(w.window_start),
    )
    in_progress = [w for w in works if _aware(w.window_start) <= now <= _aware(w.window_end)]
    return {
        "found": True,
        "subscriber_id": snap.subscriber.id,
        "planned_work_count": len(works),
        "planned_work": [
            {
                "reference": w.id,
                "title": w.title,
                "description": w.description,
                "window_display": fmt.window(_aware(w.window_start), _aware(w.window_end)),
                "expected_impact": w.expected_impact,
                "notice_sent": w.notice_sent,
                "scope_display": f"{fmt.titlecase_code(w.scope)} {w.scope_ref}",
            }
            for w in works
        ],
        "next_window_display": (
            fmt.window(_aware(works[0].window_start), _aware(works[0].window_end))
            if works
            else "none scheduled"
        ),
        "has_planned_work": bool(works),
        "work_in_progress_now": bool(in_progress),
    }


@tool("get_device_led_semantics", "network", "model", "led", "colour", "behaviour")
def get_device_led_semantics(
    snap: Snapshot | None,
    world: World,
    now: datetime,
    model: str = "",
    led: str | None = None,
    colour: str | None = None,
    behaviour: str | None = None,
) -> dict[str, Any]:
    """Translate an indicator light on a specific router model into what it means.

    Call this whenever a customer describes a light, or an image of the device has been
    analysed. The same colour means different things on different hardware, so never interpret
    a light without checking the model.
    """
    entry = world.device_models.get(model)
    if entry is None:
        return not_found(model, "device model")
    semantics = list(entry.led_semantics or [])

    def field(d: dict, key: str) -> str:
        # YAML reads a bare `off` as False; treat it as the string it was meant to be.
        value = d.get(key, "")
        if isinstance(value, bool):
            return "on" if value else "off"
        return str(value or "").lower()

    def wanted(value: Any) -> str:
        return "off" if value is False else str(value or "").lower()

    matches = semantics
    for key, value in (("led", led), ("colour", colour), ("behaviour", behaviour)):
        if value:
            matches = [s for s in matches if field(s, key) == wanted(value)]

    faults = [s["fault_id"] for s in matches if s.get("fault_id")]
    steps: list[str] = []
    escalate: str | None = None
    for fault_id in faults:
        remedy = (entry.remedies or {}).get(fault_id) or {}
        steps.extend(remedy.get("steps") or [])
        escalate = escalate or remedy.get("escalate_if")
    physical = any(f in ("fault_cabling", "fault_power_supply", "fault_no_coverage") for f in faults)
    ports = entry.port_layout or []

    return {
        "found": True,
        "model": entry.model,
        "vendor": entry.vendor,
        "kind_display": fmt.titlecase_code(entry.kind),
        "latest_firmware": entry.latest_firmware,
        "queried": {"led": led, "colour": colour, "behaviour": behaviour},
        "matches": [
            {k: s.get(k) for k in ("led", "colour", "behaviour", "meaning", "fault_id")}
            for s in matches
        ],
        "all_indicators": (
            [f"{s.get('led')} {s.get('colour')} {s.get('behaviour')}: {s.get('meaning')}" for s in semantics]
            if not matches
            else []
        ),
        "indicated_faults": faults,
        "primary_meaning": matches[0].get("meaning") if matches else None,
        "known_issues": entry.known_issues or [],
        "repair_steps": steps,
        "escalate_if": escalate,
        "port_layout": ports if physical else [],
        "port_layout_display": (
            "; ".join(
                f"{p.get('port')} ({p.get('colour')}, {p.get('position')}): {p.get('accepts')}"
                for p in ports
            )
            if physical
            else ""
        ),
        "indicator_recognised": bool(matches),
        "indicates_fault": bool(faults),
        "indicates_power_problem": "fault_power_supply" in faults,
        "indicates_suspension": "fault_service_suspended" in faults,
        "has_repair_steps": bool(steps),
        "customer_can_self_serve": bool(steps) and physical,
    }


# -- history and field operations ----------------------------------------------------------


def _slot_display(slot) -> str:
    return (
        f"{fmt.day(slot.slot_date)}, {slot.window} "
        f"({slot.window_start_hour}:00 to {slot.window_end_hour}:00)"
    )


@tool("get_open_work_orders", "history", "subscriber_ref")
def get_open_work_orders(snap: Snapshot, world: World, now: datetime) -> dict[str, Any]:
    """List engineering work already raised for this customer.

    Check this before offering to book a visit. Promising an engineer when one is already
    booked for tomorrow reads as an organisation that does not know what it is doing.
    """
    orders = sorted(
        (w for w in snap.work_orders if w.status in ("raised", "scheduled", "dispatched", "on_site")),
        key=lambda w: _aware(w.raised_at),
        reverse=True,
    )
    rendered = []
    for order in orders:
        slot = world.slots.get(order.scheduled_slot_id or "")
        tech = world.technicians.get(order.assigned_technician_id or "")
        rendered.append(
            {
                "work_order": order.id,
                "kind_display": fmt.titlecase_code(order.kind),
                "status": order.status,
                "status_display": fmt.titlecase_code(order.status),
                "priority": order.priority,
                "raised_display": fmt.relative(order.raised_at, now),
                "appointment_display": _slot_display(slot) if slot else "not yet booked",
                "technician": tech.full_name if tech else None,
                "sla_due_display": fmt.moment(_aware(order.sla_due_at)),
                "notes": order.notes,
            }
        )
    scheduled = [r for r in rendered if r["status"] == "scheduled"]
    return {
        "found": True,
        "subscriber_id": snap.subscriber.id,
        "open_work_order_count": len(rendered),
        "work_orders": rendered,
        "next_appointment_display": scheduled[0]["appointment_display"] if scheduled else "no visit booked",
        "has_open_work_order": bool(rendered),
        "visit_already_booked": bool(scheduled),
        "engineer_on_the_way": any(r["status"] in ("dispatched", "on_site") for r in rendered),
    }


@tool("get_next_appointment_slots", "history", "subscriber_ref", "days")
def get_next_appointment_slots(
    snap: Snapshot, world: World, now: datetime, days: int = 7
) -> dict[str, Any]:
    """Find engineer appointment slots with capacity near the customer's address.

    Only offer a specific date and time that appears here. Never promise a visit window that
    has not been confirmed as available.
    """
    address = snap.address
    if address is None:
        return not_found(snap.subscriber.id, "service address")
    today = now.date()
    horizon = today + timedelta(days=max(1, min(days, 30)))
    slots = sorted(
        (
            s
            for s in world.slots.values()
            if s.district == address.district and today <= s.slot_date <= horizon and s.booked < s.capacity
        ),
        key=lambda s: (s.slot_date, s.window_start_hour),
    )[:12]
    return {
        "found": True,
        "subscriber_id": snap.subscriber.id,
        "district": address.district,
        "slot_count": len(slots),
        "slots": [
            {
                "slot_id": s.id,
                "date_display": fmt.day(s.slot_date),
                "window": s.window,
                "window_display": f"{s.window_start_hour}:00 to {s.window_end_hour}:00",
                "places_left": s.capacity - s.booked,
            }
            for s in slots
        ],
        "earliest_display": _slot_display(slots[0]) if slots else "no slots available in this window",
        "slots_available": bool(slots),
        "same_day_available": bool(slots and slots[0].slot_date == today),
    }


@tool("get_prior_tickets", "history", "subscriber_ref", "limit")
def get_prior_tickets(
    snap: Snapshot, world: World, now: datetime, limit: int = 5
) -> dict[str, Any]:
    """List this customer's recent resolved support history.

    Use it to avoid repeating advice that has already failed, and to recognise a repeat
    contact. A customer reporting the same fault a third time should not get the same first
    line troubleshooting a fourth time.
    """
    tickets = sorted(snap.prior_tickets, key=lambda t: _aware(t.opened_at), reverse=True)[
        : max(1, min(limit, 25))
    ]
    recent = [t for t in tickets if (now - _aware(t.opened_at)).days <= 30]
    faults = [t.fault for t in tickets if t.fault]
    repeated = [f for f in set(faults) if faults.count(f) > 1]
    rated = [t.csat for t in tickets if t.csat]
    return {
        "found": True,
        "subscriber_id": snap.subscriber.id,
        "ticket_count": len(tickets),
        "tickets": [
            {
                "reference": t.ref,
                "department": t.department,
                "intent": t.intent,
                "fault": t.fault,
                "summary": t.summary,
                "opened_display": fmt.day(t.opened_at),
                "resolved_display": fmt.day(t.resolved_at) if t.resolved_at else "not resolved",
                "resolution": t.resolution_note,
                "action_taken": t.action_taken,
                "satisfaction": t.csat,
                "reopened": t.reopened,
            }
            for t in tickets
        ],
        "recent_contact_count": len(recent),
        "repeated_faults": repeated,
        "average_satisfaction_display": (
            f"{sum(rated) / len(rated):.1f} out of 5" if rated else "not rated"
        ),
        "is_repeat_contact": len(recent) >= 1,
        "is_frequent_contact": len(recent) >= 3,
        "has_recurring_fault": bool(repeated),
        "has_reopened_ticket": any(t.reopened for t in tickets),
    }


@tool("get_sla_position", "history", "subscriber_ref", "opened_at")
def get_sla_position(
    snap: Snapshot, world: World, now: datetime, opened_at: str | None = None
) -> dict[str, Any]:
    """Get the service level target that applies to this customer and how much time is left.

    Drives escalation and whether a service credit is owed. Enterprise and priority customers
    hold far shorter targets than consumer accounts.
    """
    plan = world.plans.get(snap.subscription.plan_code) if snap.subscription else None
    tier = world.sla.get(plan.sla_tier if plan else "") or world.sla.get("standard")
    if tier is None:
        return not_found(snap.subscriber.id, "service level tier")
    opened = now
    if opened_at:
        try:
            opened = _aware(datetime.fromisoformat(opened_at.replace("Z", "+00:00"))) or now
        except ValueError:
            pass
    due = opened + timedelta(minutes=tier.first_response_mins)
    remaining = int((due - now).total_seconds() // 60)
    at_risk = 0 < remaining <= tier.first_response_mins * SLA_AT_RISK_FRACTION
    return {
        "found": True,
        "subscriber_id": snap.subscriber.id,
        "tier": tier.tier,
        "tier_display": tier.display_name,
        "first_response_target_display": fmt.duration(tier.first_response_mins * 60),
        "resolution_target_display": fmt.duration(tier.resolution_mins * 60),
        "opened_display": fmt.moment(opened),
        "response_due_display": fmt.moment(due),
        "minutes_remaining": remaining,
        "time_remaining_display": fmt.duration(max(remaining, 0) * 60) if remaining > 0 else "target passed",
        "credit_on_breach_display": fmt.percent(tier.credit_pct_on_breach, 0),
        "priority_boost": tier.priority_boost,
        "sla_breached": remaining <= 0,
        "sla_at_risk": bool(at_risk),
        "credit_owed_on_breach": remaining <= 0 and tier.credit_pct_on_breach > 0,
        "is_premium_sla": tier.tier in ("priority", "enterprise"),
    }
