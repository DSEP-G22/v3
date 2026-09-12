"""Executing an approved action against the mock telco (v1 action_svc's job).

Called by the gateway after a staff member approves a reply that carries an action.
Parameters were derived from org facts by grounding, never by a model; amounts are still
re-checked here against the registry's impact limits before any money moves.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta
from typing import Any

import asyncpg

from app.world import COLOMBO

LIMITS = {"apply_outage_credit": 12000.0, "issue_billing_credit": 5000.0, "waive_late_fee": 2500.0}


def _id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(5).upper()}"


async def _credit(conn: asyncpg.Connection, account_id: str, amount: float, reason_code: str, text: str,
                  actor: str, case_id: str, now: datetime) -> dict[str, Any]:
    balance = await conn.fetchval(
        "UPDATE org.billing_account SET outstanding_balance = outstanding_balance - $2 WHERE id = $1 "
        "RETURNING outstanding_balance", account_id, amount)
    note = _id("CRN")
    await conn.execute(
        """INSERT INTO org.credit_note (id, account_id, amount_lkr, reason_code, reason_text, issued_at, issued_by, ticket_ref)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""", note, account_id, amount, reason_code, text, now, actor, case_id)
    await conn.execute(
        """INSERT INTO org.ledger_entry (id, account_id, posted_at, description, kind, debit_lkr, credit_lkr,
                                         balance_after_lkr, reference)
           VALUES ($1, $2, $3, $4, 'credit', 0, $5, $6, $7)""",
        _id("LED"), account_id, now, text, amount, balance, note)
    return {"credit_note": note, "amount_lkr": amount}


async def execute(conn: asyncpg.Connection, action_id: str, params: dict[str, Any], case_id: str, actor: str,
                  now: datetime) -> dict[str, Any]:
    if (limit := LIMITS.get(action_id)) is not None and float(params.get("amount_lkr", 0)) > limit:
        raise ValueError(f"{action_id} is capped at LKR {limit:,.2f}")
    account = params.get("account_id")
    sub = await conn.fetchval("SELECT subscriber_id FROM org.billing_account WHERE id = $1", account) if account else None

    if action_id == "apply_outage_credit":
        result = await _credit(conn, account, float(params["amount_lkr"]), "outage_credit",
                               f"Service credit for incident {params.get('incident_id')}", actor, case_id, now)
    elif action_id == "issue_billing_credit":
        result = await _credit(conn, account, float(params["amount_lkr"]), params.get("reason_code", "goodwill"),
                               f"Billing credit for invoice {params.get('invoice_no')}", actor, case_id, now)
    elif action_id == "waive_late_fee":
        result = await _credit(conn, account, float(params["amount_lkr"]), "late_fee_waiver", "Late fee waived",
                               actor, case_id, now)
    elif action_id in ("schedule_technician_visit", "swap_cpe"):
        slot = params.get("slot_id")
        if slot:
            await conn.execute("UPDATE org.appointment_slot SET booked = booked + 1 WHERE id = $1 AND booked < capacity", slot)
        wo = _id("WO")
        await conn.execute(
            """INSERT INTO org.work_order (id, subscriber_id, circuit_id, ticket_ref, kind, status, priority, raised_at,
                                           scheduled_slot_id, sla_due_at, notes)
               VALUES ($1, (SELECT subscriber_id FROM org.circuit WHERE id = $2), $2, $3, $4, $5, 'high', $6, $7, $8, $9)""",
            wo, params.get("circuit_id"), case_id, "repair" if action_id == "schedule_technician_visit" else "cpe_swap",
            "scheduled" if slot else "raised", now, slot, now + timedelta(days=2),
            f"Raised from case {case_id} by {actor}.")
        result = {"work_order": wo}
    elif action_id == "change_plan":
        await conn.execute("UPDATE org.subscription SET plan_code = $2 WHERE id = $1",
                           params["subscription_id"], params["target_plan_code"])
        result = {"plan_code": params["target_plan_code"]}
    elif action_id == "pause_contract":
        await conn.execute("UPDATE org.subscription SET contract_ends_on = contract_ends_on + ($2 * 30) WHERE id = $1",
                           params["subscription_id"], int(params.get("months", 3)))
        result = {"paused_months": int(params.get("months", 3))}
    elif action_id == "restart_router":
        await conn.execute("UPDATE org.cpe_device SET uptime_s = 0, last_seen_at = $2 WHERE serial = $1",
                           params["device_serial"], now)
        result = {"restarted": params["device_serial"]}
    elif action_id == "push_cpe_firmware":
        await conn.execute("UPDATE org.cpe_device SET firmware_version = $2, reboot_count_7d = 0 WHERE serial = $1",
                           params["device_serial"], params["target_firmware"])
        result = {"firmware": params["target_firmware"]}
    elif action_id in ("run_line_diagnostic", "reprovision_circuit", "escalate_to_noc", "resend_invoice"):
        result = {"queued": action_id}
    else:
        raise ValueError(f"unknown action {action_id}")

    await conn.execute(
        """INSERT INTO org.sim_event_log (id, kind, target, payload, occurred_at, actor, note)
           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
        _id("EVT"), f"action:{action_id}", sub or params.get("circuit_id") or case_id,
        json.dumps({"params": params, "result": result}, default=str), now, actor,
        f"{action_id.replace('_', ' ').capitalize()} for case {case_id}.")
    return {"action_id": action_id, "subscriber_id": sub, **result, "at": now.astimezone(COLOMBO).isoformat()}
