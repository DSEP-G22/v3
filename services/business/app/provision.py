"""Turn a paid order into a live service, and apply payments to invoices.

Driven by payment.succeeded. Every handler is idempotent (keyed on the payment intent id),
because JetStream redelivers until acked.
"""

from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta
from typing import Any

import asyncpg

from app.genesis import write_org
from app.models import (
    BillingAccount,
    Circuit,
    CpeDevice,
    CustomerLink,
    Invoice,
    InvoiceLine,
    LedgerEntry,
    Payment,
    ServiceAddress,
    Subscriber,
    Subscription,
)
from app.seed import CITY_BY_EXCHANGE, entitlements_for, load_catalogue
from app.world import World

VAT = 0.18
CPE_BY_TECH = {"gpon": "LL-ONT-2600", "adsl": "ZY-VMG-3625", "lte": "HW-B535-232", "fwa": "HW-B535-232"}
_catalogue = load_catalogue()


def _rid(prefix: str, digits: int = 7) -> str:
    # ponytail: random numeric ids for real sign-ups; collision odds are negligible at demo
    # scale. Switch to a Postgres sequence per prefix if volume ever matters.
    return f"{prefix}-{secrets.randbelow(9 * 10 ** (digits - 1)) + 10 ** (digits - 1)}"


def first_charge(price: float) -> float:
    return round(price * (1 + VAT), 2)


def _plan_dict(plan) -> dict[str, Any]:
    return {"tier": plan.tier, "monthly_price_lkr": plan.monthly_price_lkr, "contract_months": plan.contract_months}


def _paid_invoice(account_id: str, label: str, price: float, today: date, now: datetime,
                  intent: dict[str, Any], balance_before: float) -> list[Any]:
    tax = round(price * VAT, 2)
    total = round(price + tax, 2)
    inv_id = f"INV-{today.year}-{_rid('U', 6)[2:]}"
    pay_id = _rid("PAY")
    return [
        Invoice(id=inv_id, account_id=account_id, period_start=today, period_end=today + timedelta(days=29),
                issued_on=today, due_on=today, subtotal_lkr=price, tax_lkr=tax, total_lkr=total,
                paid_lkr=total, status="paid"),
        InvoiceLine(id=_rid("INL"), invoice_id=inv_id, line_no=1, description=label, category="subscription",
                    quantity=1.0, unit_price_lkr=price, amount_lkr=price, is_unusual=False),
        InvoiceLine(id=_rid("INL"), invoice_id=inv_id, line_no=2, description="Value added tax at 18 percent",
                    category="tax", quantity=1.0, unit_price_lkr=tax, amount_lkr=tax, is_unusual=False),
        LedgerEntry(id=_rid("LED"), account_id=account_id, posted_at=now, description=f"Invoice {inv_id}",
                    kind="invoice", debit_lkr=total, credit_lkr=0.0,
                    balance_after_lkr=round(balance_before + total, 2), reference=inv_id),
        Payment(id=pay_id, account_id=account_id, invoice_id=inv_id, amount_lkr=total,
                method="card" if intent.get("method") == "card_4242" else "mobile_wallet",
                reference=intent["id"], posted_at=now, status="settled"),
        LedgerEntry(id=_rid("LED"), account_id=account_id, posted_at=now, description=f"Payment received, {pay_id}",
                    kind="payment", debit_lkr=0.0, credit_lkr=total, balance_after_lkr=balance_before,
                    reference=pay_id),
    ]


def build_new_service(order: dict[str, Any], sub_id: str, world: World, now: datetime,
                      intent: dict[str, Any]) -> list[Any]:
    plan = world.plans[order["plan_code"]]
    code = order["exchange_code"]
    _, district, density = CITY_BY_EXCHANGE[code]
    today = now.date()

    address = ServiceAddress(id=_rid("ADR", 6), line1=order["address_line"] or "Service address",
                             city=order["city"], district=district, exchange_code=code, density=density)
    subscriber = Subscriber(
        id=sub_id, full_name=order["full_name"] or order["email"],
        preferred_name=(order["full_name"] or "there").split()[0], nic_masked="not provided", msisdn=None,
        email=order["email"], segment="consumer", language_pref=order["language"] or "en",
        preferred_channel="web_portal", joined_on=today, service_address_id=address.id,
        marketing_opt_in=False, simulated=False, pay_profile="manual", usage_profile="median",
    )
    account = BillingAccount(id=_rid("ACC"), subscriber_id=sub_id, currency="LKR",
                             billing_cycle_day=min(today.day, 28), status="current", dunning_stage="none",
                             credit_limit=25000.0, outstanding_balance=0.0, autopay_enabled=False, opened_on=today)
    subscription = Subscription(
        id=_rid("SVC", 6), subscriber_id=sub_id, account_id=account.id, plan_code=plan.code, status="active",
        activated_on=today,
        contract_ends_on=today + timedelta(days=30 * plan.contract_months) if plan.contract_months else None,
        renewal_date=today + timedelta(days=30),
    )

    olt_id = splitter_id = site_id = None
    if plan.technology in ("gpon", "adsl"):
        olt = min((o for o in world.olts.values() if o.exchange_code == code),
                  key=lambda o: o.uplink_utilisation_pct)
        olt_id = olt.id
        splitter_id = min(s.id for s in world.splitters.values() if s.olt_id == olt.id)
    else:
        site_id = min(s.id for s in world.sites.values() if s.district == district)

    # Line starts syncing; the next sim tick brings it up, which is what the UI's
    # "Your line is being set up" state waits for.
    circuit = Circuit(id=_rid("CIR"), subscription_id=subscription.id, subscriber_id=sub_id,
                      technology=plan.technology, olt_id=olt_id, splitter_id=splitter_id, cell_site_id=site_id,
                      port=None, provisioned_down_mbps=plan.speed_down_mbps,
                      provisioned_up_mbps=plan.speed_up_mbps, status="in_service", line_state="syncing",
                      last_state_change=now, activated_on=today)
    model = world.device_models[CPE_BY_TECH[plan.technology]]
    cpe = CpeDevice(serial=f"LLK{secrets.randbelow(9 * 10**9) + 10**9}", circuit_id=circuit.id,
                    subscriber_id=sub_id, model=model.model,
                    mac=":".join(f"{secrets.randbelow(256):02X}" for _ in range(6)),
                    firmware_version=model.latest_firmware, wan_status="online", uptime_s=0, last_seen_at=now,
                    lan_clients=0, wifi_channel=6, wifi_band_steering=True, reboot_count_7d=0,
                    owned_by_operator=True, installed_on=today)

    rows: list[Any] = [address, subscriber, account, subscription, circuit, cpe]
    rows += entitlements_for(sub_id, _plan_dict(plan), _catalogue, lambda: _rid("ENT"))
    rows += _paid_invoice(account.id, f"{plan.display_name} first month", plan.monthly_price_lkr,
                          today, now, intent, 0.0)
    rows.append(CustomerLink(user_id=order["user_id"], subscriber_id=sub_id, linked_at=now, linked_by="self"))
    return rows


async def next_subscriber_id(conn: asyncpg.Connection) -> str:
    n = await conn.fetchval(
        "SELECT coalesce(max(substr(id, 5)::int), 200000) + 1 FROM org.subscriber WHERE id LIKE 'SUB-2%'"
    )
    return f"SUB-{n}"


async def on_new_service(conn: asyncpg.Connection, intent: dict[str, Any], world: World, now: datetime) -> str | None:
    """Returns the new subscriber id, or None when this intent was already handled."""
    order = await conn.fetchrow(
        'SELECT * FROM org."order" WHERE id = $1 AND status = \'pending_payment\' FOR UPDATE', intent["ref"]
    )
    if order is None:
        return None
    sub_id = await next_subscriber_id(conn)
    await write_org(conn, build_new_service(dict(order), sub_id, world, now, intent))
    await conn.execute('UPDATE org."order" SET status = \'active\', subscriber_id = $2 WHERE id = $1',
                       order["id"], sub_id)
    return sub_id


async def on_plan_change(conn: asyncpg.Connection, intent: dict[str, Any], world: World, now: datetime) -> str | None:
    order = await conn.fetchrow(
        'SELECT * FROM org."order" WHERE id = $1 AND status = \'pending_payment\' FOR UPDATE', intent["ref"]
    )
    if order is None:
        return None
    plan = world.plans[order["plan_code"]]
    sub_id = order["subscriber_id"]
    account_id = await conn.fetchval("SELECT id FROM org.billing_account WHERE subscriber_id = $1", sub_id)
    balance = await conn.fetchval("SELECT outstanding_balance FROM org.billing_account WHERE id = $1", account_id)
    await conn.execute("UPDATE org.subscription SET plan_code = $2 WHERE subscriber_id = $1", sub_id, plan.code)
    await conn.execute(
        "UPDATE org.circuit SET provisioned_down_mbps = $2, provisioned_up_mbps = $3 WHERE subscriber_id = $1",
        sub_id, plan.speed_down_mbps, plan.speed_up_mbps,
    )
    # ponytail: plan change charges one month of the new plan up front, no pro-rating.
    await write_org(conn, _paid_invoice(account_id, f"{plan.display_name} plan change", plan.monthly_price_lkr,
                                        now.date(), now, intent, balance))
    await conn.execute('UPDATE org."order" SET status = \'active\' WHERE id = $1', order["id"])
    return sub_id


async def on_invoice_payment(conn: asyncpg.Connection, intent: dict[str, Any], now: datetime) -> str | None:
    """Post a payment against an invoice. A suspension lifts on the next sim tick."""
    if await conn.fetchval("SELECT 1 FROM org.payment WHERE reference = $1", intent["id"]):
        return None
    inv = await conn.fetchrow("SELECT * FROM org.invoice WHERE id = $1 FOR UPDATE", intent["ref"])
    if inv is None:
        return None
    acct = await conn.fetchrow("SELECT * FROM org.billing_account WHERE id = $1 FOR UPDATE", inv["account_id"])
    amount = float(intent["amount_lkr"])
    paid = round(inv["paid_lkr"] + amount, 2)
    balance = round(acct["outstanding_balance"] - amount, 2)
    pay_id = _rid("PAY")
    await conn.execute("UPDATE org.invoice SET paid_lkr = $2, status = $3 WHERE id = $1",
                       inv["id"], paid, "paid" if paid >= inv["total_lkr"] - 0.005 else "partial")
    await conn.execute("UPDATE org.billing_account SET outstanding_balance = $2 WHERE id = $1", acct["id"], balance)
    await write_org(conn, [
        Payment(id=pay_id, account_id=acct["id"], invoice_id=inv["id"], amount_lkr=amount,
                method="card" if intent.get("method") == "card_4242" else "mobile_wallet",
                reference=intent["id"], posted_at=now, status="settled"),
        LedgerEntry(id=_rid("LED"), account_id=acct["id"], posted_at=now, description=f"Payment received, {pay_id}",
                    kind="payment", debit_lkr=0.0, credit_lkr=amount, balance_after_lkr=balance, reference=pay_id),
    ])
    return acct["subscriber_id"]
