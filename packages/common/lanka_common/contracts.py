"""The ContextBundle contract: the only thing the drafting LLM is ever handed.

Ported from v2 cst2/contracts/bundle.py, with v1's payload/triage/diagnosis types folded in
as plain pydantic models. The rule this type exists to enforce: the LLM ingests nothing
directly. Everything it may know is assembled by the grounding service, in a fixed order,
with provenance and a completeness verdict. tests/architecture enforces that
`ContextBundle(` is constructed only in services/grounding/app/assemble.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

FactGroup = Literal["identity", "commercial", "network", "history"]
#: Render order for org facts: who the customer is before what is broken.
FACT_GROUP_ORDER: tuple[FactGroup, ...] = ("identity", "commercial", "network", "history")

Band = Literal["low", "normal", "high", "critical"]


def band_for(level: int) -> Band:
    return "critical" if level >= 9 else "high" if level >= 7 else "normal" if level >= 4 else "low"


#: Faults on the customer's own side of the line, in words a reply can open with. The draft
#: addresses these first, then anything on our side (PROVIDER_SIDE_SIGNALS).
#: Only equipment faults: "not working" alone is as likely an outage as a loose cable.
CUSTOMER_FAULTS: dict[str, str] = {
    "fault_cabling": "a cable on the router has come loose or been disconnected",
    "fault_power_supply": "the router's power cable has come loose or the router is not getting power",
    "fault_firmware_crashloop": "the router keeps restarting",
    "fault_wifi": "the Wi-Fi at the premises is not working as it should",
}
#: Record signals that describe the customer's own equipment rather than our network or account.
CUSTOMER_SIDE_SIGNALS: frozenset[str] = frozenset({
    "cpe_offline", "reboot_loop_suspected", "firmware_behind", "premises_fault_likely", "known_issue_applies",
})


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Provenance(Frozen):
    modality: str
    source: str
    span: tuple[int, int]
    confidence: float = 1.0


class LedState(Frozen):
    label: str = ""
    colour: str = ""
    behaviour: str = "solid"


class VisualSummary(Frozen):
    attachment_id: str
    summary_text: str
    device_model: str | None = None
    led_states: list[LedState] = Field(default_factory=list)
    confidence: float = 0.0


class Transcript(Frozen):
    attachment_id: str
    text: str
    text_en: str
    language: str
    confidence: float
    low_confidence: bool


class Payload(Frozen):
    """The fused multimodal message(s) for one case revision."""

    case_id: str
    revision: int
    original_text: str
    text_en: str
    language: str = "en"
    reply_language: str = "en"
    native_text: str | None = None
    fused_text: str
    provenance: list[Provenance] = Field(default_factory=list)
    transcripts: list[Transcript] = Field(default_factory=list)
    visual_summaries: list[VisualSummary] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    partial: bool = False
    opened_at: datetime | None = None


class Triage(Frozen):
    department: str
    base_level: int
    routed_by: str = ""
    sentiment: str = "neutral"
    signals: dict[str, Any] = Field(default_factory=dict)
    #: The distilled TriageModel's read of the request (level, band, score, confidence, source).
    customer_priority: dict[str, Any] = Field(default_factory=dict)


class Citation(Frozen):
    chunk_id: str
    source: str
    quote: str = ""


class Diagnosis(Frozen):
    intent: str = "report_fault"
    fault: str | None = None
    confidence: float = 0.0
    rationale: str = ""
    citations: list[Citation] = Field(default_factory=list)
    needs_human_diagnosis: bool = False
    via: str = "rules"


class OrgFact(Frozen):
    tool: str
    group: FactGroup = "identity"
    args: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    ok: bool = True
    error: str | None = None
    prefetched: bool = True

    @property
    def found(self) -> bool:
        return bool(self.ok and self.result.get("found", False))

    def signals(self) -> dict[str, bool]:
        return {k: v for k, v in self.result.items() if isinstance(v, bool) and k != "found"}


class SopPassage(Frozen):
    chunk_id: str
    text: str
    relevance: float
    source: str


class SlaPosition(Frozen):
    tier: str = "standard"
    tier_display: str = "Standard care"
    minutes_remaining: int | None = None
    response_due_display: str | None = None
    breached: bool = False
    at_risk: bool = False

    @property
    def display(self) -> str:
        if self.breached:
            return f"First response target passed ({self.tier_display})"
        if self.minutes_remaining is None:
            return self.tier_display
        hours, mins = divmod(max(self.minutes_remaining, 0), 60)
        return f"{f'{hours}h {mins}m' if hours else f'{mins}m'} left ({self.tier_display})"


class ActionEntry(Frozen):
    """An action the registry may offer. permits() is v1's ActionRegistryEntry.permits."""

    action_id: str
    department: str | None = None
    description: str = ""
    mapped_faults: list[str] = Field(default_factory=list)
    requires_fields: list[str] = Field(default_factory=list)
    impact_limits: dict[str, float] = Field(default_factory=dict)
    requires_entitlement: str | None = None
    requires_supervisor: bool = False
    enabled: bool = True

    def permits(self, params: dict[str, Any]) -> bool:
        if not self.enabled or any(f not in params for f in self.requires_fields):
            return False
        for key, limit in self.impact_limits.items():
            name = key.removeprefix("max_")
            if name in params and params[name] > limit:
                return False
        return True


class Completeness(Frozen):
    required: list[str] = Field(default_factory=list)
    present: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    degraded: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)

    @property
    def sufficient(self) -> bool:
        return not self.missing

    @property
    def score(self) -> float:
        return round(len(self.present) / len(self.required), 3) if self.required else 1.0


class Priority(Frozen):
    level: int
    band: Band
    base_level: int
    reasons: list[dict[str, Any]] = Field(default_factory=list)
    #: customer: the request itself, scored by the TriageModel. provider: what our records say
    #: is wrong on our side, scored by rules. combined: the queue order, the higher of the two.
    side: Literal["combined", "customer", "provider"] = "combined"
    source: str = "rules"
    score: int | None = None


class ContextBundle(Frozen):
    """Everything the generator may know about one case revision, and nothing else."""

    schema_version: str = "3.0.0"
    case_id: str
    revision: int = 1
    built_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    build_ms: int = 0

    payload: Payload
    department: str
    triage: Triage
    diagnosis: Diagnosis | None = None
    sop_passages: list[SopPassage] = Field(default_factory=list)
    org_facts: list[OrgFact] = Field(default_factory=list)
    sla: SlaPosition = Field(default_factory=SlaPosition)
    permitted_actions: list[ActionEntry] = Field(default_factory=list)
    completeness: Completeness = Field(default_factory=Completeness)
    priority: Priority
    customer_priority: Priority | None = None
    provider_priority: Priority | None = None

    @property
    def fault(self) -> str | None:
        return self.diagnosis.fault if self.diagnosis else None

    @property
    def reply_language(self) -> str:
        return self.payload.reply_language

    def fact(self, tool: str) -> OrgFact | None:
        return next((f for f in self.org_facts if f.tool == tool), None)

    def facts_in_group(self, group: FactGroup) -> list[OrgFact]:
        return [f for f in self.org_facts if f.group == group]

    def active_signals(self) -> dict[str, str]:
        """Every true causal boolean, mapped to the tool that established it."""
        active: dict[str, str] = {}
        for f in self.org_facts:
            for name, value in f.signals().items():
                if value:
                    active.setdefault(name, f.tool)
        return active
