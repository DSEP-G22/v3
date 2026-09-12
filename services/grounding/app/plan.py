"""Which org facts a case calls for, and what counts as complete. Ported from v2.

The plan is configuration, never agent choice: an agent that picks its own tools stops as
soon as one appears to answer the question, and never learns the line is down because the
account was barred. The department gives a base list, the diagnosed fault adds to it.

Source of truth is the control service (editable in /admin); config/grounding_plan.yaml is
the seed and the fallback when control is unreachable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(os.environ.get("LANKA_CONFIG_DIR") or Path(__file__).resolve().parents[3] / "config")

TOOL_GROUPS: dict[str, str] = {
    "get_subscriber_profile": "identity",
    "get_payment_status": "commercial",
    "get_account_balance": "commercial",
    "get_billing_history": "commercial",
    "get_last_invoice_breakdown": "commercial",
    "get_ledger_window": "commercial",
    "get_plan_and_entitlements": "commercial",
    "get_usage_summary": "commercial",
    "get_circuit_status": "network",
    "get_cpe_diagnostics": "network",
    "get_line_quality": "network",
    "get_active_outages_for": "network",
    "get_planned_work_for": "network",
    "get_device_led_semantics": "network",
    "get_open_work_orders": "history",
    "get_next_appointment_slots": "history",
    "get_prior_tickets": "history",
    "get_sla_position": "history",
}


@dataclass(frozen=True)
class FetchPlan:
    department: str
    fault: str | None
    tools: tuple[str, ...]
    required_sections: tuple[str, ...]
    section_tools: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def group_of(self, tool: str) -> str:
        return TOOL_GROUPS.get(tool, "identity")


def load_file() -> dict[str, Any]:
    path = CONFIG_DIR / "grounding_plan.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {} if path.exists() else {}


class PlanResolver:
    def __init__(self, doc: dict[str, Any] | None = None) -> None:
        self.doc = doc or load_file()

    def resolve(self, department: str, fault: str | None = None) -> FetchPlan:
        by_department = self.doc.get("by_department") or {}
        base = by_department.get(department) or by_department.get("general") or {}
        extra = (self.doc.get("by_fault") or {}).get(fault or "") or {}
        tools: list[str] = []
        for tool in list(base.get("tools") or []) + list(extra.get("tools") or []):
            if tool not in tools:
                tools.append(tool)
        required = list(base.get("required_sections") or [])
        required += [s for s in extra.get("required_sections") or [] if s not in required]
        sections = {k: tuple(v) for k, v in (self.doc.get("sections") or {}).items()}
        return FetchPlan(department, fault, tuple(tools), tuple(required), sections)
