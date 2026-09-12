"""Rebind llm_draft through the admin API, probe it, then put the original binding back.

    uv run python scripts/verify_hot_swap.py

Passes when the generation increments on each swap and the stub binding probes ok, all without
restarting a container.
"""

from __future__ import annotations

import sys

from lanka_http import staff

ROLE = "llm_draft"


def binding(admin) -> dict:
    roles = admin.get("/api/admin/models").raise_for_status().json()["roles"]
    return next(r for r in roles if r["role"] == ROLE)


def swap(admin, impl: str, model: str, params: dict, reason: str) -> dict:
    return admin.put(f"/api/admin/models/{ROLE}", json={
        "impl": impl, "model_version": model, "params": params, "reason": reason}).raise_for_status().json()


def main() -> int:
    admin = staff("admin1")
    before = binding(admin)
    print(f"before: {before['impl']}:{before['model_version']} generation {before['generation']}")

    swapped = swap(admin, "stub", "stub", {}, "verify_hot_swap")
    assert swapped["generation"] == before["generation"] + 1, swapped
    probe = admin.post(f"/api/admin/models/{ROLE}/probe").raise_for_status().json()
    assert probe["status"] == "ok", probe
    print(f"swapped: stub probes {probe['status']} in {probe['ms']} ms")

    restored = swap(admin, before["impl"], before["model_version"], before.get("params") or {}, "verify_hot_swap restore")
    assert restored["generation"] == before["generation"] + 2, restored
    print(f"restored: {restored['impl']}:{restored['model_version']} generation {restored['generation']}")
    print("hot swap OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
