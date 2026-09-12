"""business-sim: the rule-based world (python -m app.sim).

Each tick covers the sim window since the previous tick, however long, so "advance one
day" is simply one tick with a one day window: telemetry and usage for the whole window go
in as one generate_series INSERT each, and billing, dunning and payments work from sim
dates rather than counting ticks.

Rules live in config/sim_rules.yaml. Real sign-ups (simulated = false) never get random
faults and never pay automatically; they pay through the UI.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import random
import sys
import time
import zlib
from datetime import date, datetime, timedelta, timezone
from typing import Any

import asyncpg
import yaml

from app import provision, scenarios
from app.seed import CONFIG_DIR
from app.world import COLOMBO
from lanka_common import bus
from lanka_common.db import POOLER_KWARGS, parse_neon_key

RULES = yaml.safe_load((CONFIG_DIR / "sim_rules.yaml").read_text(encoding="utf-8"))
DIURNAL: list[float] = RULES["diurnal"]
STAGES = ("none", "reminder", "final_notice", "suspend")


def olt_multiplier(olt_id: str) -> float:
    """Stable per-OLT demand factor in [0.55, 0.95]; the busiest congest most evenings."""
    return 0.55 + (zlib.crc32(olt_id.encode()) % 1000) / 1000 * 0.4


def olt_utilisation(olt_id: str, at: datetime, boost: float = 0.0) -> float:
    hour = at.astimezone(COLOMBO).hour
    return round(min(99.0, 100 * min(1.0, olt_multiplier(olt_id) + boost) * DIURNAL[hour]), 1)


def _today(at: datetime) -> date:
    return at.astimezone(COLOMBO).date()


def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


# -- faults -------------------------------------------------------------------------------------


async def expire_faults(conn, ts, now: datetime) -> None:
    for f in await conn.fetch(
        "SELECT id FROM org.active_fault WHERE source = 'random' AND eta_at IS NOT NULL AND eta_at <= $1", now
    ):
        await scenarios.clear(conn, ts, f["id"], now, actor="sim")


async def random_faults(conn, ts, start: datetime, now: datetime, rng: random.Random) -> None:
    days = (now - start).total_seconds() / 86400
    pool: list[asyncpg.Record] | None = None
    for kind, rule in RULES["faults"].items():
        for _ in range(_poisson(rng, rule["per_day"] * days)):
            if pool is None:
                pool = await conn.fetch(
                    """SELECT s.id, c.olt_id FROM org.subscriber s JOIN org.circuit c ON c.subscriber_id = s.id
                       WHERE s.simulated AND c.status = 'in_service'"""
                )
            candidates = [r for r in pool if r["olt_id"]] if kind in ("congest_uplink",) else pool
            if not candidates:
                continue
            target = rng.choice(candidates)["id"]
            lo, hi = rule["hours"]
            eta = now + timedelta(hours=rng.uniform(lo, hi))
            try:
                await scenarios.apply(conn, ts, kind, target, now, source="random", eta=eta, actor="sim")
            except (ValueError, LookupError):
                continue


# -- money --------------------------------------------------------------------------------------


async def billing_run(conn, now: datetime) -> None:
    """Invoice every subscription whose renewal date has arrived (several cycles after a jump)."""
    today = _today(now)
    vat, due_days = RULES["billing"]["vat"], RULES["billing"]["due_days"]
    due_rows = await conn.fetch(
        """SELECT sv.id, sv.account_id, sv.renewal_date, p.display_name, p.monthly_price_lkr,
                  a.pending_charges_lkr, a.outstanding_balance,
                  coalesce((SELECT sum(monthly_price_lkr) FROM org.addon d
                            WHERE d.subscription_id = sv.id AND d.active), 0) AS addons
           FROM org.subscription sv JOIN org.plan_catalogue p ON p.code = sv.plan_code
           JOIN org.billing_account a ON a.id = sv.account_id
           WHERE sv.renewal_date <= $1 AND sv.status IN ('active', 'suspended')""",
        today,
    )
    for r in due_rows:
        renewal, balance, pending = r["renewal_date"], r["outstanding_balance"], r["pending_charges_lkr"]
        while renewal <= today:
            lines = [(f"{r['display_name']} monthly charge", "subscription", r["monthly_price_lkr"])]
            if r["addons"]:
                lines.append(("Add-ons", "addon", float(r["addons"])))
            if pending:
                lines.append(("Late payment fee", "one_off", float(pending)))
                pending = 0.0
            subtotal = round(sum(a for _, _, a in lines), 2)
            tax = round(subtotal * vat, 2)
            total = round(subtotal + tax, 2)
            inv = f"INV-{renewal.year}-{scenarios._id('R')[2:]}"
            await conn.execute(
                """INSERT INTO org.invoice (id, account_id, period_start, period_end, issued_on, due_on,
                                            subtotal_lkr, tax_lkr, total_lkr, paid_lkr, status)
                   VALUES ($1, $2, $3, $4, $3, $5, $6, $7, $8, 0, 'unpaid')""",
                inv, r["account_id"], renewal, renewal + timedelta(days=29), renewal + timedelta(days=due_days),
                subtotal, tax, total,
            )
            await conn.executemany(
                """INSERT INTO org.invoice_line (id, invoice_id, line_no, description, category, quantity,
                                                 unit_price_lkr, amount_lkr, is_unusual)
                   VALUES ($1, $2, $3, $4, $5, 1, $6, $6, false)""",
                [(scenarios._id("INL"), inv, i, d, c, a) for i, (d, c, a) in enumerate(lines, 1)]
                + [(scenarios._id("INL"), inv, len(lines) + 1, "Value added tax at 18 percent", "tax", tax)],
            )
            balance = round(balance + total, 2)
            await conn.execute(
                """INSERT INTO org.ledger_entry (id, account_id, posted_at, description, kind, debit_lkr,
                                                 credit_lkr, balance_after_lkr, reference)
                   VALUES ($1, $2, $3, $4, 'invoice', $5, 0, $6, $7)""",
                scenarios._id("LED"), r["account_id"],
                datetime.combine(renewal, datetime.min.time(), tzinfo=COLOMBO), f"Invoice {inv}", total, balance, inv,
            )
            renewal += timedelta(days=30)
        await conn.execute(
            "UPDATE org.subscription SET renewal_date = $2 WHERE id = $1", r["id"], renewal
        )
        await conn.execute(
            "UPDATE org.billing_account SET outstanding_balance = $2, pending_charges_lkr = 0 WHERE id = $1",
            r["account_id"], balance,
        )
        # A new cycle restores full speed.
        await conn.execute(
            "UPDATE org.circuit SET line_state = 'up', last_state_change = $2 WHERE subscription_id = $1 AND line_state = 'shaped'",
            r["id"], now,
        )


def pay_on(profile: str, invoice_id: str, issued: date, due: date) -> date | None:
    days = RULES["payment_days"]
    h = zlib.crc32(invoice_id.encode())
    if profile == "autopay":
        return issued
    if profile == "on_time":
        lo, hi = days["on_time"]
        return due + timedelta(days=lo + h % (hi - lo + 1))
    if profile == "late":
        lo, hi = days["late"]
        return due + timedelta(days=lo + h % (hi - lo + 1))
    return None  # never, manual


async def simulated_payments(conn, now: datetime) -> None:
    today = _today(now)
    rows = await conn.fetch(
        """SELECT i.id, i.issued_on, i.due_on, i.total_lkr - i.paid_lkr AS due, s.pay_profile, a.autopay_enabled
           FROM org.invoice i JOIN org.billing_account a ON a.id = i.account_id
           JOIN org.subscriber s ON s.id = a.subscriber_id
           WHERE s.simulated AND i.status IN ('unpaid', 'overdue', 'partial')
             AND s.pay_profile IN ('autopay', 'on_time', 'late')"""
    )
    for r in rows:
        when = pay_on(r["pay_profile"], r["id"], r["issued_on"], r["due_on"])
        if when is None or when > today or r["due"] <= 0:
            continue
        intent = {"id": f"sim-{r['id']}", "ref": r["id"], "amount_lkr": round(r["due"], 2),
                  "method": "card_4242" if r["autopay_enabled"] else "lankaqr"}
        await provision.on_invoice_payment(conn, intent, now)


async def dunning(conn, now: datetime) -> set[str]:
    """Walk accounts through reminder, final notice and suspension; restore settled ones.

    Returns the subscriber ids whose service state changed, so real users can be told.
    """
    today = _today(now)
    changed: set[str] = set()
    await conn.execute(
        "UPDATE org.invoice SET status = 'overdue' WHERE status IN ('unpaid', 'partial') AND due_on < $1", today
    )
    thresholds = RULES["dunning_days"]
    rows = await conn.fetch(
        """SELECT a.id, a.subscriber_id, a.dunning_stage, a.outstanding_balance, min(i.due_on) AS oldest
           FROM org.billing_account a JOIN org.invoice i ON i.account_id = a.id
           WHERE i.status = 'overdue' AND a.status <> 'terminated'
           GROUP BY a.id"""
    )
    for r in rows:
        late = (today - r["oldest"]).days
        target = "none"
        for stage in STAGES[1:]:
            if late >= thresholds[stage]:
                target = stage
        current = r["dunning_stage"] if r["dunning_stage"] in STAGES else "none"
        for stage in STAGES[STAGES.index(current) + 1 : STAGES.index(target) + 1]:
            if stage == "suspend":
                await scenarios.suspend(conn, r["id"], r["subscriber_id"], now)
                changed.add(r["subscriber_id"])
            else:
                await conn.execute(
                    """UPDATE org.billing_account SET dunning_stage = $2,
                           status = CASE WHEN status = 'current' THEN 'overdue' ELSE status END WHERE id = $1""",
                    r["id"], stage,
                )
                await conn.execute(
                    """INSERT INTO org.dunning_event (id, account_id, stage, occurred_at, channel, amount_at_time_lkr)
                       VALUES ($1, $2, $3, $4, 'sms', $5)""",
                    scenarios._id("DUN"), r["id"], stage, now, r["outstanding_balance"],
                )

    # Paid up: lift any bar and bring the line back. A suspension costs a late fee next bill.
    for r in await conn.fetch(
        """SELECT id, subscriber_id, status FROM org.billing_account
           WHERE status IN ('overdue', 'suspended') AND outstanding_balance <= 0.005"""
    ):
        await scenarios.restore(conn, r["id"], r["subscriber_id"], now)
        if r["status"] == "suspended":
            await conn.execute(
                "UPDATE org.billing_account SET pending_charges_lkr = pending_charges_lkr + $2 WHERE id = $1",
                r["id"], float(RULES["billing"]["late_fee_lkr"]),
            )
        await conn.execute(
            """INSERT INTO org.dunning_event (id, account_id, stage, occurred_at, channel, amount_at_time_lkr)
               VALUES ($1, $2, 'restored', $3, 'sms', 0)""",
            scenarios._id("DUN"), r["id"], now,
        )
        changed.add(r["subscriber_id"])
    return changed


# -- network ------------------------------------------------------------------------------------


async def network_state(conn, ts, start: datetime, now: datetime) -> None:
    # New lines finish syncing on the tick after they were provisioned.
    await conn.execute(
        "UPDATE org.circuit SET line_state = 'up', last_state_change = $2 WHERE line_state = 'syncing' AND last_state_change <= $1",
        start, now,
    )
    forced = {r["target_ref"]: json.loads(r["detail"]).get("utilisation", 96.0)
              for r in await conn.fetch("SELECT target_ref, detail FROM org.active_fault WHERE kind = 'congest_uplink'")}
    olts = await conn.fetch("SELECT id FROM org.olt")
    updates, samples = [], []
    step = timedelta(minutes=RULES["telemetry_minutes"])
    for o in olts:
        util = forced.get(o["id"]) or olt_utilisation(o["id"], now)
        status = "degraded" if util >= RULES["congestion_threshold_pct"] else "up"
        updates.append((o["id"], util, status, now))
        at = start + step
        while at <= now:
            u = forced.get(o["id"]) or olt_utilisation(o["id"], at)
            samples.append((at, o["id"], u, "degraded" if u >= RULES["congestion_threshold_pct"] else "up"))
            at += step
    await conn.executemany(
        "UPDATE org.olt SET uplink_utilisation_pct = $2, uplink_status = $3, last_seen_at = $4 WHERE id = $1", updates
    )
    if samples:
        await ts.copy_records_to_table(
            "olt_metric", columns=["time", "olt_id", "utilisation_pct", "uplink_status"], records=samples
        )


async def telemetry(conn, ts, start: datetime, now: datetime) -> None:
    rows = await conn.fetch(
        """SELECT c.id, c.technology, c.line_state, c.provisioned_down_mbps, c.provisioned_up_mbps, c.olt_id,
                  c.subscription_id, d.wan_status, p.fup_shaped_mbps, p.data_cap_gb, s.usage_profile
           FROM org.circuit c JOIN org.subscription sv ON sv.id = c.subscription_id
           JOIN org.plan_catalogue p ON p.code = sv.plan_code
           JOIN org.subscriber s ON s.id = c.subscriber_id
           LEFT JOIN org.cpe_device d ON d.circuit_id = c.id
           WHERE c.status IN ('in_service', 'suspended')"""
    )
    degraded = {json.loads(r["detail"])["circuit_id"]
                for r in await conn.fetch("SELECT detail FROM org.active_fault WHERE kind = 'line_degradation'")}
    forced = {r["target_ref"] for r in await conn.fetch("SELECT target_ref FROM org.active_fault WHERE kind = 'congest_uplink'")}

    ids, techs, states, down, up, mult, bad, hot = [], [], [], [], [], [], [], []
    usage_ids, usage_daily = [], []
    per_day, capped_share = RULES["usage_gb_per_day"], RULES["capped_share_of_allowance"]
    for r in rows:
        if r["wan_status"] in ("offline", "unreachable"):
            continue  # an offline router reports nothing: a gap, not zeros
        state = "down" if r["line_state"] == "down" else r["line_state"]
        speed = r["fup_shaped_mbps"] if state == "shaped" else r["provisioned_down_mbps"]
        ids.append(r["id"])
        techs.append(r["technology"])
        states.append(state)
        down.append(float(speed))
        up.append(float(min(r["provisioned_up_mbps"], speed)))
        mult.append(olt_multiplier(r["olt_id"]) if r["olt_id"] else 0.5)
        bad.append(r["id"] in degraded)
        hot.append(r["olt_id"] in forced)
        if state in ("up", "shaped"):
            profile = r["usage_profile"] if r["usage_profile"] in per_day else "median"
            cap = r["data_cap_gb"]
            daily = cap / 30 * capped_share[profile] if cap and cap > 0 else per_day[profile]
            usage_ids.append(r["subscription_id"])
            usage_daily.append(float(daily) * (0.2 if state == "shaped" else 1.0))

    threshold = RULES["congestion_threshold_pct"] / 100
    await ts.execute(
        """
        INSERT INTO line_metric (time, circuit_id, rx_power_dbm, tx_power_dbm, snr_db, sync_down_mbps,
                                 sync_up_mbps, latency_ms, jitter_ms, packet_loss_pct, crc_errors, resyncs)
        SELECT t, c.id,
               CASE WHEN c.state = 'down' OR c.tech <> 'gpon' THEN NULL
                    WHEN c.bad THEN -27 + (random() - 0.5) ELSE -18.5 + (random() - 0.5) * 1.6 END,
               CASE WHEN c.state = 'down' OR c.tech <> 'gpon' THEN NULL ELSE 2.3 + (random() - 0.5) * 0.4 END,
               CASE WHEN c.state = 'down' OR c.tech NOT IN ('adsl', 'vdsl') THEN NULL
                    WHEN c.bad THEN 16 + random() * 2 ELSE 30 + random() * 3 END,
               CASE WHEN c.state = 'down' THEN 0 ELSE c.down * x.factor END,
               CASE WHEN c.state = 'down' THEN 0 ELSE c.up * x.factor END,
               CASE WHEN c.state = 'down' THEN 0 WHEN x.congested THEN 170 + random() * 40 ELSE 18 + random() * 30 END,
               CASE WHEN c.state = 'down' THEN 0 WHEN x.congested THEN 18 + random() * 8 ELSE 2 + random() * 4 END,
               CASE WHEN c.state = 'down' THEN 100 WHEN c.bad THEN 2 + random() * 3 ELSE random() * 0.3 END,
               CASE WHEN c.state = 'down' THEN 0 WHEN c.bad THEN (40 + random() * 200)::int ELSE (random() * 2)::int END,
               CASE WHEN c.bad AND random() < 0.1 THEN 1 ELSE 0 END
        FROM unnest($1::text[], $2::text[], $3::text[], $4::real[], $5::real[], $6::real[], $7::bool[], $8::bool[])
             AS c(id, tech, state, down, up, mult, bad, hot)
        CROSS JOIN generate_series($9::timestamptz, $10::timestamptz, $11::interval) AS t
        CROSS JOIN LATERAL (
            SELECT (c.hot OR c.mult * ($12::real[])[extract(hour FROM t AT TIME ZONE 'Asia/Colombo')::int + 1] >= $13)
                   AS congested
        ) y
        CROSS JOIN LATERAL (
            SELECT y.congested,
                   CASE WHEN y.congested AND extract(hour FROM t AT TIME ZONE 'Asia/Colombo') BETWEEN 20 AND 23
                        THEN 0.45 + random() * 0.1 ELSE 0.92 + random() * 0.08 END AS factor
        ) x
        """,
        ids, techs, states, down, up, mult, bad, hot,
        start + timedelta(minutes=RULES["telemetry_minutes"]), now, timedelta(minutes=RULES["telemetry_minutes"]),
        DIURNAL, threshold,
    )

    slots_per_day = 1440 // RULES["usage_minutes"]
    weight_sum = sum(DIURNAL) * (60 // RULES["usage_minutes"])
    await ts.execute(
        """
        INSERT INTO usage_sample (time, subscription_id, down_gb, up_gb)
        SELECT t, u.id, share * 0.88, share * 0.12
        FROM unnest($1::text[], $2::real[]) AS u(id, daily)
        CROSS JOIN generate_series($3::timestamptz, $4::timestamptz, $5::interval) AS t
        CROSS JOIN LATERAL (
            SELECT u.daily * ($6::real[])[extract(hour FROM t AT TIME ZONE 'Asia/Colombo')::int + 1] / $7
                   * CASE WHEN extract(isodow FROM t AT TIME ZONE 'Asia/Colombo') >= 6 THEN $8 ELSE 1 END
                   * (0.7 + random() * 0.6) AS share
        ) s
        """,
        usage_ids, usage_daily, start + timedelta(minutes=RULES["usage_minutes"]), now,
        timedelta(minutes=RULES["usage_minutes"]), DIURNAL, weight_sum, RULES["weekend_factor"],
    )
    del slots_per_day


async def fup(conn, ts, now: datetime) -> None:
    """Crossing the allowance shapes the line until the next renewal."""
    rows = await conn.fetch(
        """SELECT sv.id, sv.renewal_date - 30 AS cycle_start, p.data_cap_gb
           FROM org.subscription sv JOIN org.plan_catalogue p ON p.code = sv.plan_code
           JOIN org.circuit c ON c.subscription_id = sv.id
           WHERE p.data_cap_gb > 0 AND c.line_state = 'up'"""
    )
    if not rows:
        return
    over = await ts.fetch(
        """SELECT x.id FROM unnest($1::text[], $2::date[], $3::real[]) AS x(id, start, cap)
           JOIN LATERAL (SELECT sum(down_gb + up_gb) AS used FROM usage_sample
                         WHERE subscription_id = x.id AND time >= x.start) u ON true
           WHERE u.used >= x.cap""",
        [r["id"] for r in rows], [r["cycle_start"] for r in rows], [float(r["data_cap_gb"]) for r in rows],
    )
    if over:
        await conn.execute(
            """UPDATE org.circuit SET line_state = 'shaped', last_state_change = $2
               WHERE subscription_id = ANY($1::text[]) AND line_state = 'up'""",
            [r["id"] for r in over], now,
        )


# -- loop ---------------------------------------------------------------------------------------


async def tick(neon: asyncpg.Pool, ts: asyncpg.Pool, nc, rng: random.Random) -> dict[str, Any] | None:
    clock = await neon.fetchrow("SELECT * FROM org.sim_clock WHERE id = 1")
    if clock is None:
        return None
    wall = datetime.now(timezone.utc)
    now = clock["anchor_sim"] + (wall - clock["anchor_wall"]) * clock["speed"]
    start = clock["last_tick_sim"] or now - timedelta(minutes=RULES["telemetry_minutes"])
    if now - start < timedelta(minutes=1):
        return None  # paused, or too little sim time passed to be worth a tick

    async with neon.acquire() as conn, ts.acquire() as tconn:
        async with conn.transaction():
            await expire_faults(conn, tconn, now)
            await random_faults(conn, tconn, start, now, rng)
            await billing_run(conn, now)
            await simulated_payments(conn, now)
            changed = await dunning(conn, now)
            await network_state(conn, tconn, start, now)
            await telemetry(conn, tconn, start, now)
            await fup(conn, tconn, now)
            await conn.execute("UPDATE org.sim_clock SET last_tick_sim = $1 WHERE id = 1", now)
        real = await conn.fetch(
            """SELECT l.user_id, l.subscriber_id FROM org.customer_link l JOIN org.subscriber s ON s.id = l.subscriber_id
               WHERE l.subscriber_id = ANY($1::text[]) AND NOT s.simulated""",
            list(changed),
        )
    for r in real:
        await nc.publish(f"user.{r['user_id']}.account", json.dumps({"subscriber_id": r["subscriber_id"]}).encode())
    return {"sim_from": start.isoformat(), "sim_to": now.isoformat(), "changed": len(changed)}


async def main() -> None:
    neon = await asyncpg.create_pool(parse_neon_key(os.environ["NEON_KEY"]).pooled, min_size=1, max_size=4,
                                     **POOLER_KWARGS)
    ts = await asyncpg.create_pool(os.environ["TIMESCALE_URL"], min_size=1, max_size=4)
    nc, _ = await bus.connect()
    rng = random.Random()
    print("business-sim: ticking", file=sys.stderr)
    while True:
        started = time.monotonic()
        try:
            result = await tick(neon, ts, nc, rng)
            if result and result["changed"]:
                print(f"tick {result}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 - a bad tick must not stop the world
            print(f"tick failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        # ponytail: fixed cadence; with Neon far away a tick can outlast it, then ticks run back to back.
        await asyncio.sleep(max(0.0, RULES["tick_seconds"] - (time.monotonic() - started)))


if __name__ == "__main__":
    asyncio.run(main())
