"""Function testing: the customer's use cases through the same API the browser calls."""

from __future__ import annotations

import re
import time

from conftest import case_for, until

SINHALA = re.compile(r"[඀-෿]")
#: Step numbers ("1.") may move in translation; amounts, waits and times may not.
LIST_MARKER = re.compile(r"(?m)^\s*\d{1,2}[.)]\s+")


def numbers(text: str) -> list[str]:
    return sorted(re.sub(r"\D", "", n) for n in re.findall(r"\d[\d,.:]*\d|\d", LIST_MARKER.sub("", text)))


def test_the_public_pages_need_no_account(anon):
    plans = anon.get("/api/public/plans").raise_for_status().json()
    assert plans["plans"] and all("price_lkr" in p for p in plans["plans"])


def test_who_am_i_names_the_role(amara, agent):
    assert amara.get("/api/me").raise_for_status().json()["role"] == "customer"
    assert agent.get("/api/me").raise_for_status().json()["role"] in ("agent", "lead", "admin")


def test_the_account_screens_carry_the_customers_own_record(amara):
    overview = amara.get("/api/app/overview").raise_for_status().json()
    billing = amara.get("/api/app/billing").raise_for_status().json()
    plan = amara.get("/api/app/plan").raise_for_status().json()
    usage = amara.get("/api/app/usage").raise_for_status().json()
    assert overview["first_name"] and overview["service"]["headline"]
    assert billing["summary"]["outstanding_display"].startswith("LKR")
    assert plan["current"]["name"] and plan["plans"]
    assert usage["daily"] and all({"date", "gb"} <= set(d) for d in usage["daily"])
    # The same ledger behind both screens: the overview never recomputes what billing says.
    assert overview["billing"]["outstanding_display"] == billing["summary"]["outstanding_display"]


def test_a_sinhala_message_becomes_a_case_with_a_draft(ravi, agent):
    """The headline path: message in, case in the console, a reply written for it."""
    text = f"මගේ අන්තර්ජාලය වැඩ කරන්නේ නැහැ ({time.strftime('%H:%M:%S')})"
    t0 = time.monotonic()
    ravi.post("/api/app/messages", data={"text": text}).raise_for_status()
    assert time.monotonic() - t0 < 3.0, "the acknowledgement must be immediate; the pipeline runs after it"

    assert case_for(agent, text), "the message never produced a case"
    detail = until(lambda: (d := case_for(agent, text, timeout=5)) and d.get("drafts") and d)
    assert detail, "no draft was written for the case"
    draft = detail["drafts"][-1]
    assert draft["text_en"].strip(), "the draft is empty"
    assert SINHALA.search(draft["text_out"]), "the reply must be in the language the customer wrote in"
    # Every number in the English draft has to survive translation: a wrong amount or wait is a lie.
    assert numbers(draft["text_en"]) == numbers(draft["text_out"]), draft["text_out"]


def test_the_conversation_keeps_what_was_said(ravi):
    msgs = ravi.get("/api/app/conversation").raise_for_status().json()["messages"]
    assert msgs and all("id" in m and "body" in m for m in msgs)


def test_a_ticket_can_be_read_back_whole(ravi):
    tickets = ravi.get("/api/app/tickets").raise_for_status().json()["tickets"]
    if not tickets:
        return
    one = ravi.get(f"/api/app/tickets/{tickets[0]['id']}").raise_for_status().json()
    assert one["ticket"]["id"] == tickets[0]["id"] and one["ticket"]["status"]
    assert one["messages"], "a ticket always carries the message that opened it"
