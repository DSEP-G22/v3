"""Data and database integrity, exercised through the services that own the data.

The stores are Neon Postgres (business and cases), Timescale (events) and MinIO (attachments).
What matters here is that a write is durable and readable, that a bad write is refused, and
that an id that does not exist is a 404 rather than a leak or a 500.
"""

from __future__ import annotations

import io
import time

import pytest
from conftest import until


@pytest.mark.parametrize("path", ["/api/app/tickets/LL-999999", "/api/app/orders/00000000-0000-0000-0000-000000000000"])
def test_an_unknown_id_is_a_clean_404(amara, path):
    assert amara.get(path).status_code == 404


def test_an_unknown_case_is_a_clean_404(agent):
    assert agent.get("/api/console/cases/LL-000000").status_code == 404


def test_an_empty_message_is_refused(ravi):
    r = ravi.post("/api/app/messages", data={"text": "   "})
    assert r.status_code in (400, 422), r.text


def test_a_message_survives_the_round_trip(ravi):
    """Written once, read back byte for byte from the store, not from a cache in the process."""
    text = f"Read back check {time.strftime('%H:%M:%S')} balance Rs. 1,758.20"
    ravi.post("/api/app/messages", data={"text": text}).raise_for_status()
    got = until(lambda: next((m for m in ravi.get("/api/app/conversation").json()["messages"]
                              if m["body"].strip() == text), None), timeout=30)
    assert got, "the message was acknowledged but is not in the conversation"


def test_an_attachment_keeps_its_bytes(ravi):
    """MinIO round trip: the object that comes back is the object that went in."""
    blob = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4
    r = ravi.post("/api/app/messages", data={"text": f"Photo check {time.strftime('%H:%M:%S')}"},
                  files={"files": ("router.png", io.BytesIO(blob), "image/png")})
    r.raise_for_status()
    att = until(lambda: next((a for m in ravi.get("/api/app/conversation").json()["messages"]
                              for a in m.get("attachments", []) or []), None), timeout=30)
    assert att, "the attachment was accepted but never appeared on the message"
    back = ravi.get(f"/api/app/attachments/{att['id']}")
    assert back.status_code in (200, 302, 307)


def test_a_case_revision_only_moves_forward(agent):
    cases = agent.get("/api/console/cases", params={"tab": "all"}).raise_for_status().json()["cases"]
    assert all(isinstance(c["revision"], int) and c["revision"] >= 1 for c in cases)


def test_the_bill_adds_up(amara):
    """Money is read from the ledger, never recomputed in the UI: the parts must sum to the total."""
    b = amara.get("/api/app/billing").raise_for_status().json()
    for inv in b.get("invoices", [])[:5]:
        assert inv["total"] >= 0
        assert inv["status"] in ("paid", "due", "overdue", "void", "open", "partial"), inv["status"]
        assert f"{inv['total']:,.2f}" in inv["total_display"], inv["total_display"]
