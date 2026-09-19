"""Sign in through :8080 the way the browser does, for the HTTP scripts."""

from __future__ import annotations

import os
import time

import httpx

BASE = os.environ.get("LANKA_URL", "http://localhost:8080")
STAFF_PASSWORD = os.environ.get("SEED_STAFF_PASSWORD", "Console#2026")
CUSTOMER_PASSWORD = os.environ.get("SEED_CUSTOMER_PASSWORD", "Lanka#2026")


def session(email: str, password: str) -> httpx.Client:
    """Cookie sign-in, then a gateway JWT as the bearer on every later call."""
    c = httpx.Client(base_url=BASE, timeout=30, headers={"origin": BASE})
    # Better Auth rate limits sign-in. A test run opens half a dozen sessions at once, so back off.
    for attempt in range(6):
        r = c.post("/api/auth/sign-in/email", json={"email": email, "password": password})
        if r.status_code != 429:
            break
        time.sleep(float(r.headers.get("x-retry-after", 2)) + attempt)
    r.raise_for_status()
    token = c.get("/api/auth/token").raise_for_status().json()["token"]
    c.headers["authorization"] = f"Bearer {token}"
    return c


def staff(name: str) -> httpx.Client:
    return session(f"{name}@lankalink.example.lk", STAFF_PASSWORD)


def customer(name: str) -> httpx.Client:
    return session(f"{name}@customers.lankalink.example.lk", CUSTOMER_PASSWORD)
