"""Scenarios: one implementation for operator injection (/sim) and random faults (business-sim).

v2's ten sandbox scenarios map one to one, plus five v3 additions. Every scenario that
changes a subscriber records an active_fault holding what is needed to undo it, so every
scenario can be cleared. Customers only ever see the effect (a dead line, an outage banner
built from OutageIncident.customer_message), never the scenario.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta
from typing import Any

import asyncpg

from app.world import COLOMBO

SCENARIOS: dict[str, str] = {
    "suspend_account": "Bar the service for non payment and put the line down.",
    "restore_account": "Clear the balance, lift the bar and bring the line back up.",
    "open_outage": "Open a fibre break incident on the customer's own OLT or cell site.",
    "resolve_outages": "Resolve every open incident.",
    "drop_cpe": "Take the customer's router offline as though it lost power.",
    "restore_cpe": "Bring the customer's router back online.",
    "congest_uplink": "Push the customer's OLT uplink into congestion.",
    "relieve_uplink": "Return every OLT uplink to normal.",
    "expire_contract": "Move the contract end date into the notice period.",
    "add_disputed_charge": "Add a duplicated equipment fee to the latest invoice.",
    "line_degradation": "Drift the optical signal down and raise line errors.",
    "firmware_crashloop": "Put the router into a firmware reboot loop.",
    "fup_exceeded": "Use up the data allowance so the line is shaped.",
    "overdue_invoice": "Raise an invoice that is already past its due date.",
    "planned_work": "Schedule maintenance on the customer's equipment starting soon.",
}
#: Network-wide scenarios: no subscriber, no fault record (they are clears themselves).
GLOBAL = {"resolve_outages", "relieve_uplink"}

_TARGET = """
SELECT s.id, s.simulated, a.id AS account_id, a.outstanding_balance, sv.id AS subscription_id,
       sv.plan_code, sv.contract_ends_on, p.monthly_price_lkr, p.data_cap_gb, c.id AS circuit_id,
       c.olt_id, c.cell_site_id, c.status AS circuit_status, d.serial, d.model, d.firmware_version,
       d.wan_status
FROM org.subscriber s
JOIN org.billing_account a ON a.subscriber_id = s.id
JOIN org.subscription sv ON sv.subscriber_id = s.id
JOIN org.plan_catalogue p ON p.code = sv.plan_code
LEFT JOIN org.circuit c ON c.subscriber_id = s.id
LEFT JOIN org.cpe_device d ON d.subscriber_id = s.id
WHERE s.id = $1
"""


def _id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(5).upper()}"


def _today(now: datetime):
    return now.astimezone(COLOMBO).date()


async def log(conn, kind: str, target: str, payload: dict[str, Any], now: datetime, actor: str, note: str) -> None:
    await conn.execute(
        """INSERT INTO org.sim_event_log (id, kind, target, payload, occurred_at, actor, note)
           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
        _id("EVT"), kind, target, json.dumps(payload, default=str), now, actor, note,
    )


# -- shared effects ---------------------------------------------------------------------------


async def overdue_invoice_row(conn, t, now: datetime, amount: float, days_overdue: int) -> str:
    today = _today(now)
    due = today - timedelta(days=days_overdue)
    subtotal = round(amount / 1.18, 2)
    inv = f"INV-{today.year}-{_id('S')[2:]}"
    await conn.execute(
        """INSERT INTO org.invoice (id, account_id, period_start, period_end, issued_on, due_on,
                                    subtotal_lkr, tax_lkr, total_lkr, paid_lkr, status)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 0, 'overdue')""",
        inv, t["account_id"], due - timedelta(days=44), due - timedelta(days=15), due - timedelta(days=14),
        due, subtotal, round(amount - subtotal, 2), amount,
    )
    await conn.execute(
        """INSERT INTO org.invoice_line (id, invoice_id, line_no, description, category, quantity,
                                         unit_price_lkr, amount_lkr, is_unusual)
           VALUES ($1, $2, 1, 'Monthly service charge including VAT', 'subscription', 1, $3, $3, false)""",
        _id("INL"), inv, amount,
    )
    balance = await conn.fetchval(
        """UPDATE org.billing_account SET outstanding_balance = outstanding_balance + $2,
               status = CASE WHEN status = 'current' THEN 'overdue' ELSE status END,
               dunning_stage = CASE WHEN dunning_stage = 'none' THEN 'reminder' ELSE dunning_stage END
           WHERE id = $1 RETURNING outstanding_balance""",
        t["account_id"], amount,
    )
    await conn.execute(
        """INSERT INTO org.ledger_entry (id, account_id, posted_at, description, kind, debit_lkr,
                                         credit_lkr, balance_after_lkr, reference)
           VALUES ($1, $2, $3, $4, 'invoice', $5, 0, $6, $7)""",
        _id("LED"), t["account_id"], now, f"Invoice {inv}", amount, balance, inv,
    )
    return inv


async def suspend(conn, account_id: str, subscriber_id: str, now: datetime) -> None:
    await conn.execute(
        "UPDATE org.billing_account SET status = 'suspended', dunning_stage = 'suspend' WHERE id = $1", account_id
    )
    await conn.execute(
        """UPDATE org.subscription SET status = 'suspended', suspended_on = $2,
               suspension_reason = 'Unpaid balance beyond the final notice period'
           WHERE subscriber_id = $1""",
        subscriber_id, _today(now),
    )
    await conn.execute(
        """UPDATE org.circuit SET status = 'suspended', line_state = 'down', last_state_change = $2
           WHERE subscriber_id = $1""",
        subscriber_id, now,
    )
    await conn.execute(
        """INSERT INTO org.dunning_event (id, account_id, stage, occurred_at, channel, amount_at_time_lkr)
           SELECT $1, id, 'suspend', $2, 'sms', outstanding_balance FROM org.billing_account WHERE id = $3""",
        _id("DUN"), now, account_id,
    )


async def restore(conn, account_id: str, subscriber_id: str, now: datetime) -> None:
    await conn.execute(
        "UPDATE org.billing_account SET status = 'current', dunning_stage = 'none' WHERE id = $1", account_id
    )
    await conn.execute(
        """UPDATE org.subscription SET status = 'active', suspended_on = NULL, suspension_reason = NULL
           WHERE subscriber_id = $1""",
        subscriber_id,
    )
    # The line comes back only if the router is there to bring it up.
    await conn.execute(
        """UPDATE org.circuit c SET status = 'in_service', last_state_change = $2,
               line_state = CASE WHEN d.wan_status = 'online' THEN 'up' ELSE c.line_state END
           FROM org.cpe_device d WHERE d.circuit_id = c.id AND c.subscriber_id = $1""",
        subscriber_id, now,
    )


async def lines_up(conn, circuit_ids: list[str], now: datetime) -> None:
    await conn.execute(
        """UPDATE org.circuit c SET line_state = 'up', last_state_change = $2
           FROM org.cpe_device d
           WHERE d.circuit_id = c.id AND c.id = ANY($1::text[]) AND c.status = 'in_service'
             AND d.wan_status = 'online'""",
        circuit_ids, now,
    )


# -- handlers: (conn, ts, target, now, **kw) -> (result, fault | None) -------------------------
# fault = (target_kind, target_ref, detail needed to undo)


async def _suspend_account(conn, ts, t, now, amount_lkr: float = 8450.0):
    inv = await overdue_invoice_row(conn, t, now, float(amount_lkr), days_overdue=20)
    await suspend(conn, t["account_id"], t["id"], now)
    return {"invoice_no": inv, "amount_lkr": amount_lkr}, ("subscriber", t["id"], {"invoice_id": inv})


async def _restore_account(conn, ts, t, now):
    await conn.execute(
        """UPDATE org.invoice SET paid_lkr = total_lkr, status = 'paid'
           WHERE account_id = $1 AND status IN ('unpaid', 'overdue', 'partial')""",
        t["account_id"],
    )
    await conn.execute("UPDATE org.billing_account SET outstanding_balance = 0 WHERE id = $1", t["account_id"])
    await restore(conn, t["account_id"], t["id"], now)
    return {"account_id": t["account_id"]}, None


async def _open_outage(conn, ts, t, now, hours_to_fix: int = 6):
    scope, ref = ("olt", t["olt_id"]) if t["olt_id"] else ("cell_site", t["cell_site_id"])
    if not ref:
        raise ValueError("that subscriber is not attached to shared equipment")
    incident = _id("INC")
    await conn.execute(
        """INSERT INTO org.outage_incident (id, scope, scope_ref, title, cause, cause_category, severity,
                                           opened_at, eta_at, status, affected_estimate, customer_message,
                                           credit_policy)
           VALUES ($1, $2, $3, $4, 'A fibre break was reported on the feeder serving this equipment.',
                   'fibre_cut', 'major', $5, $6, 'open', 0, $7,
                   'Automatic credit for any full day of lost service.')""",
        incident, scope, ref, f"Service affecting incident on {ref}", now, now + timedelta(hours=hours_to_fix),
        "We are repairing a damaged cable that is affecting service in your area. "
        "Our engineers are on site and we will restore service as soon as we can.",
    )
    downed = await conn.fetch(
        """UPDATE org.circuit SET line_state = 'down', last_state_change = $2
           WHERE (olt_id = $1 OR cell_site_id = $1) AND line_state IN ('up', 'shaped', 'syncing')
           RETURNING id""",
        ref, now,
    )
    ids = [r["id"] for r in downed]
    await conn.execute("UPDATE org.outage_incident SET affected_estimate = $2 WHERE id = $1", incident, len(ids))
    return {"incident_id": incident, "scope": scope, "scope_ref": ref, "lines_down": len(ids)}, (
        scope, ref, {"incident_id": incident, "circuits": ids},
    )


async def _clear_open_outage(conn, ts, fault, detail, now):
    await conn.execute(
        "UPDATE org.outage_incident SET status = 'resolved', resolved_at = $2 WHERE id = $1",
        detail["incident_id"], now,
    )
    await lines_up(conn, detail["circuits"], now)


async def _resolve_outages(conn, ts, t, now):
    faults = await conn.fetch("SELECT * FROM org.active_fault WHERE kind = 'open_outage'")
    for f in faults:
        await clear(conn, ts, f["id"], now, actor="operator")
    rows = await conn.fetch(
        """UPDATE org.outage_incident SET status = 'resolved', resolved_at = $1
           WHERE status IN ('open', 'mitigating', 'monitoring') RETURNING id""",
        now,
    )
    return {"resolved": [f["id"] for f in faults] + [r["id"] for r in rows]}, None


async def _drop_cpe(conn, ts, t, now):
    if not t["serial"]:
        raise ValueError("that subscriber has no equipment on record")
    await conn.execute(
        """UPDATE org.cpe_device SET wan_status = 'offline', uptime_s = 0, lan_clients = 0, last_seen_at = $2
           WHERE serial = $1""",
        t["serial"], now,
    )
    await conn.execute(
        "UPDATE org.circuit SET line_state = 'down', last_state_change = $2 WHERE id = $1", t["circuit_id"], now
    )
    return {"serial": t["serial"], "model": t["model"]}, ("subscriber", t["id"], {"serial": t["serial"]})


async def _restore_cpe(conn, ts, t, now):
    await conn.execute(
        """UPDATE org.cpe_device SET wan_status = 'online', uptime_s = 600, lan_clients = 4, last_seen_at = $2,
               reboot_count_7d = 0 WHERE serial = $1""",
        t["serial"], now,
    )
    await lines_up(conn, [t["circuit_id"]], now)
    return {"serial": t["serial"]}, None


async def _congest_uplink(conn, ts, t, now, utilisation: float = 96.0):
    if not t["olt_id"]:
        raise ValueError("that subscriber is not served by an OLT")
    await conn.execute(
        "UPDATE org.olt SET uplink_utilisation_pct = $2, uplink_status = 'degraded' WHERE id = $1",
        t["olt_id"], float(utilisation),
    )
    return {"olt_id": t["olt_id"], "utilisation_pct": utilisation}, (
        "olt", t["olt_id"], {"utilisation": float(utilisation)},
    )


async def _clear_congestion(conn, ts, fault, detail, now):
    await conn.execute(
        "UPDATE org.olt SET uplink_utilisation_pct = 42, uplink_status = 'up' WHERE id = $1", fault["target_ref"]
    )


async def _relieve_uplink(conn, ts, t, now):
    faults = await conn.fetch("SELECT id FROM org.active_fault WHERE kind = 'congest_uplink'")
    for f in faults:
        await clear(conn, ts, f["id"], now, actor="operator")
    await conn.execute("UPDATE org.olt SET uplink_utilisation_pct = 42, uplink_status = 'up'")
    return {"cleared": len(faults)}, None


async def _expire_contract(conn, ts, t, now, days: int = 14):
    new = _today(now) + timedelta(days=days)
    await conn.execute("UPDATE org.subscription SET contract_ends_on = $2 WHERE id = $1", t["subscription_id"], new)
    prev = t["contract_ends_on"].isoformat() if t["contract_ends_on"] else None
    return {"contract_ends_on": new.isoformat()}, ("subscriber", t["id"], {"previous": prev})


async def _clear_expire_contract(conn, ts, fault, detail, now):
    prev = detail.get("previous")
    await conn.execute(
        "UPDATE org.subscription SET contract_ends_on = $2::date WHERE subscriber_id = $1",
        fault["target_ref"], datetime.fromisoformat(prev).date() if prev else None,
    )


async def _add_disputed_charge(conn, ts, t, now, amount_lkr: float = 7500.0):
    inv = await conn.fetchval(
        "SELECT id FROM org.invoice WHERE account_id = $1 ORDER BY issued_on DESC LIMIT 1", t["account_id"]
    )
    if inv is None:
        raise ValueError("that account has no invoice to add a charge to")
    line = _id("INL")
    amount = float(amount_lkr)
    await conn.execute(
        """INSERT INTO org.invoice_line (id, invoice_id, line_no, description, category, quantity,
                                         unit_price_lkr, amount_lkr, is_unusual, unusual_reason)
           SELECT $1, $2, coalesce(max(line_no), 0) + 1, 'Replacement router equipment fee', 'equipment',
                  1, $3, $3, true, 'Charged twice. The same fee also appears on the previous invoice.'
           FROM org.invoice_line WHERE invoice_id = $2""",
        line, inv, amount,
    )
    await conn.execute(
        """UPDATE org.invoice SET subtotal_lkr = subtotal_lkr + $2, total_lkr = total_lkr + $2,
               status = CASE WHEN status = 'paid' THEN 'partial' ELSE status END WHERE id = $1""",
        inv, amount,
    )
    await conn.execute(
        "UPDATE org.billing_account SET outstanding_balance = outstanding_balance + $2 WHERE id = $1",
        t["account_id"], amount,
    )
    return {"invoice_no": inv, "amount_lkr": amount}, (
        "subscriber", t["id"], {"invoice_id": inv, "line_id": line, "amount": amount, "account_id": t["account_id"]},
    )


async def _clear_disputed_charge(conn, ts, fault, detail, now):
    amount = detail["amount"]
    await conn.execute("DELETE FROM org.invoice_line WHERE id = $1", detail["line_id"])
    await conn.execute(
        """UPDATE org.invoice SET subtotal_lkr = subtotal_lkr - $2, total_lkr = total_lkr - $2,
               status = CASE WHEN paid_lkr >= total_lkr - $2 - 0.005 THEN 'paid' ELSE status END
           WHERE id = $1""",
        detail["invoice_id"], amount,
    )
    await conn.execute(
        "UPDATE org.billing_account SET outstanding_balance = outstanding_balance - $2 WHERE id = $1",
        detail["account_id"], amount,
    )


async def _line_degradation(conn, ts, t, now):
    # Telemetry reads this fault: rx drifts to about -27 dBm and CRC errors climb.
    return {"circuit_id": t["circuit_id"]}, ("subscriber", t["id"], {"circuit_id": t["circuit_id"]})


async def _firmware_crashloop(conn, ts, t, now):
    if not t["serial"]:
        raise ValueError("that subscriber has no equipment on record")
    await conn.execute(
        """UPDATE org.cpe_device SET wan_status = 'rebooting', reboot_count_7d = 12, uptime_s = 90,
               firmware_version = CASE WHEN model = 'LL-ONT-2400' THEN '4.1.2' ELSE firmware_version END
           WHERE serial = $1""",
        t["serial"],
    )
    return {"serial": t["serial"]}, ("subscriber", t["id"], {"serial": t["serial"], "firmware": t["firmware_version"]})


async def _clear_crashloop(conn, ts, fault, detail, now):
    await conn.execute(
        """UPDATE org.cpe_device SET wan_status = 'online', reboot_count_7d = 0, uptime_s = 600, last_seen_at = $3,
               firmware_version = $2 WHERE serial = $1""",
        detail["serial"], detail["firmware"], now,
    )


async def _fup_exceeded(conn, ts, t, now):
    cap = t["data_cap_gb"]
    if cap is None or cap <= 0:
        raise ValueError("that plan has no data allowance to exhaust")
    await ts.execute(
        "INSERT INTO usage_sample (time, subscription_id, down_gb, up_gb) VALUES ($1, $2, $3, $4)",
        now, t["subscription_id"], float(cap) * 0.9, float(cap) * 0.1,
    )
    await conn.execute(
        "UPDATE org.circuit SET line_state = 'shaped', last_state_change = $2 WHERE id = $1 AND line_state = 'up'",
        t["circuit_id"], now,
    )
    return {"subscription_id": t["subscription_id"], "used_gb": cap}, (
        "subscriber", t["id"], {"circuit_id": t["circuit_id"]},
    )


async def _clear_fup(conn, ts, fault, detail, now):
    await conn.execute(
        "UPDATE org.circuit SET line_state = 'up', last_state_change = $2 WHERE id = $1 AND line_state = 'shaped'",
        detail["circuit_id"], now,
    )


async def _overdue_invoice(conn, ts, t, now, amount_lkr: float | None = None):
    amount = round(float(amount_lkr or t["monthly_price_lkr"] * 1.18), 2)
    inv = await overdue_invoice_row(conn, t, now, amount, days_overdue=3)
    return {"invoice_no": inv, "amount_lkr": amount}, (
        "subscriber", t["id"], {"invoice_id": inv, "account_id": t["account_id"]},
    )


async def _clear_invoice(conn, ts, fault, detail, now):
    due = await conn.fetchval(
        "UPDATE org.invoice SET status = 'void' WHERE id = $1 AND status <> 'paid' RETURNING total_lkr - paid_lkr",
        detail["invoice_id"],
    )
    if due:
        await conn.execute(
            """UPDATE org.billing_account SET outstanding_balance = outstanding_balance - $2 WHERE id = $1""",
            detail["account_id"], due,
        )
    # A voided invoice may be the only thing holding the account overdue or suspended.
    acct = await conn.fetchrow("SELECT * FROM org.billing_account WHERE id = $1", detail["account_id"])
    if acct["outstanding_balance"] <= 0.005 and acct["status"] in ("overdue", "suspended"):
        await restore(conn, acct["id"], acct["subscriber_id"], now)


async def _planned_work(conn, ts, t, now, start_in_hours: int = 2, hours: int = 3):
    scope, ref = ("olt", t["olt_id"]) if t["olt_id"] else ("cell_site", t["cell_site_id"])
    pw = _id("PW")
    start = now + timedelta(hours=start_in_hours)
    await conn.execute(
        """INSERT INTO org.planned_work (id, scope, scope_ref, title, description, window_start, window_end,
                                         notice_sent, expected_impact)
           VALUES ($1, $2, $3, 'Network maintenance', 'Planned upgrade work on equipment serving your area.',
                   $4, $5, true, 'Up to thirty minutes of lost service inside the window.')""",
        pw, scope, ref, start, start + timedelta(hours=hours),
    )
    return {"planned_work": pw, "scope_ref": ref}, (scope, ref, {"planned_id": pw})


async def _clear_planned(conn, ts, fault, detail, now):
    await conn.execute("DELETE FROM org.planned_work WHERE id = $1", detail["planned_id"])


async def _clear_suspension(conn, ts, fault, detail, now):
    acct = await conn.fetchrow("SELECT * FROM org.billing_account WHERE subscriber_id = $1", fault["target_ref"])
    await _clear_invoice(conn, ts, fault, {"invoice_id": detail["invoice_id"], "account_id": acct["id"]}, now)
    acct = await conn.fetchrow("SELECT * FROM org.billing_account WHERE id = $1", acct["id"])
    if acct["status"] != "current" and acct["outstanding_balance"] <= 0.005:
        await restore(conn, acct["id"], acct["subscriber_id"], now)


async def _clear_drop_cpe(conn, ts, fault, detail, now):
    t = await conn.fetchrow(_TARGET, fault["target_ref"])
    await _restore_cpe(conn, ts, t, now)


async def _noop(conn, ts, fault, detail, now):
    return None


HANDLERS = {
    "suspend_account": _suspend_account,
    "restore_account": _restore_account,
    "open_outage": _open_outage,
    "resolve_outages": _resolve_outages,
    "drop_cpe": _drop_cpe,
    "restore_cpe": _restore_cpe,
    "congest_uplink": _congest_uplink,
    "relieve_uplink": _relieve_uplink,
    "expire_contract": _expire_contract,
    "add_disputed_charge": _add_disputed_charge,
    "line_degradation": _line_degradation,
    "firmware_crashloop": _firmware_crashloop,
    "fup_exceeded": _fup_exceeded,
    "overdue_invoice": _overdue_invoice,
    "planned_work": _planned_work,
}
CLEARERS = {
    "suspend_account": _clear_suspension,
    "open_outage": _clear_open_outage,
    "drop_cpe": _clear_drop_cpe,
    "congest_uplink": _clear_congestion,
    "expire_contract": _clear_expire_contract,
    "add_disputed_charge": _clear_disputed_charge,
    "line_degradation": _noop,
    "firmware_crashloop": _clear_crashloop,
    "fup_exceeded": _clear_fup,
    "overdue_invoice": _clear_invoice,
    "planned_work": _clear_planned,
}
assert set(HANDLERS) == set(SCENARIOS)
assert set(CLEARERS) | GLOBAL | {"restore_account", "restore_cpe"} == set(SCENARIOS)


async def apply(conn: asyncpg.Connection, ts, name: str, subscriber_id: str | None, now: datetime, *,
                source: str = "operator", eta: datetime | None = None, actor: str = "operator",
                **kwargs: Any) -> dict[str, Any]:
    if name not in SCENARIOS:
        raise KeyError(f"unknown scenario {name}")
    t = None
    if name not in GLOBAL:
        t = await conn.fetchrow(_TARGET, subscriber_id)
        if t is None:
            raise LookupError(f"no subscriber matches {subscriber_id}")
    result, fault = await HANDLERS[name](conn, ts, t, now, **kwargs)
    if fault is not None:
        target_kind, target_ref, detail = fault
        fid = _id("FLT")
        await conn.execute(
            """INSERT INTO org.active_fault (id, kind, target_kind, target_ref, started_at, eta_at, source, detail)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
            fid, name, target_kind, target_ref, now, eta, source, json.dumps(detail),
        )
        result["fault_id"] = fid
    await log(conn, name, subscriber_id or "network", result, now, actor, SCENARIOS[name])
    return {"scenario": name, **result}


async def clear(conn: asyncpg.Connection, ts, fault_id: str, now: datetime, *, actor: str = "operator") -> dict[str, Any]:
    fault = await conn.fetchrow("DELETE FROM org.active_fault WHERE id = $1 RETURNING *", fault_id)
    if fault is None:
        raise LookupError(f"no active fault {fault_id}")
    detail = json.loads(fault["detail"]) if isinstance(fault["detail"], str) else dict(fault["detail"] or {})
    await CLEARERS[fault["kind"]](conn, ts, fault, detail, now)
    await log(conn, f"clear:{fault['kind']}", fault["target_ref"], {"fault_id": fault_id}, now, actor,
              f"Cleared {fault['kind'].replace('_', ' ')}.")
    return {"cleared": fault_id, "kind": fault["kind"]}
