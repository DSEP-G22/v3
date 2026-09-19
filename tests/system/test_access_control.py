"""Security and access control: who may call what, and whose data they see.

Every staff surface is behind a role. A customer holds a valid token too, so the interesting
failures are not "no token" but "the wrong role" and "another customer's row".
"""

from __future__ import annotations

import time

import pytest

CUSTOMER_FORBIDDEN = ["/api/console/cases", "/api/console/ping", "/api/admin/models", "/api/lab/requests"]
AGENT_FORBIDDEN = ["/api/admin/models", "/api/admin/traces", "/api/lab/requests"]


@pytest.mark.parametrize("path", ["/api/me", "/api/app/billing", "/api/console/cases", "/api/admin/models"])
def test_no_token_is_rejected(anon, path):
    assert anon.get(path).status_code == 401


@pytest.mark.parametrize("path", CUSTOMER_FORBIDDEN)
def test_a_customer_cannot_reach_staff_surfaces(amara, path):
    assert amara.get(path).status_code == 403


@pytest.mark.parametrize("path", AGENT_FORBIDDEN)
def test_an_agent_cannot_reach_admin_surfaces(agent, path):
    assert agent.get(path).status_code == 403


def test_each_role_reaches_its_own_surface(agent, admin, operator):
    assert agent.get("/api/console/cases", params={"tab": "all"}).status_code == 200
    assert admin.get("/api/admin/models").status_code == 200
    assert operator.get("/api/lab/requests").status_code == 200


def test_a_customer_cannot_read_another_customers_ticket(amara, ravi):
    """Tenant isolation: ids are guessable, the rows behind them are not shared."""
    def tickets(who, name):
        rows = who.get("/api/app/tickets").raise_for_status().json()["tickets"]
        if not rows:  # a fresh database: open one, so the check never silently skips
            who.post("/api/app/messages", data={"text": f"isolation check for {name} {time.time()}"}).raise_for_status()
            rows = who.get("/api/app/tickets").raise_for_status().json()["tickets"]
        return rows

    mine, theirs = tickets(amara, "amara"), tickets(ravi, "ravi")
    assert ravi.get(f"/api/app/tickets/{mine[0]['id']}").status_code in (403, 404)
    assert amara.get(f"/api/app/tickets/{theirs[0]['id']}").status_code in (403, 404)


def test_a_tampered_token_is_rejected(anon, amara):
    bad = amara.headers["authorization"][:-3] + "xyz"
    assert anon.get("/api/me", headers={"authorization": bad}).status_code == 401


def test_sign_in_rejects_a_wrong_password(anon):
    r = anon.post("/api/auth/sign-in/email", headers={"origin": anon.base_url.__str__()},
                  json={"email": "amara@customers.lankalink.example.lk", "password": "not-the-password"})
    assert r.status_code >= 400
