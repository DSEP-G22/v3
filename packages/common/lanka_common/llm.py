"""Text generators behind one async interface: Ollama (gpt-oss), OpenAI-compatible (Gemini
fallback) and a deterministic, grounded stub. Ported from v2 cst2/modelctl/llm.py.

Every generator's output goes through the punctuation scrub, so no model can put an em dash
in front of a customer. Each client caps concurrency and trips a circuit breaker after
repeated failures, so a sick endpoint fails fast instead of queueing every case behind it.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator
from typing import Any, Protocol

import httpx
from pydantic import BaseModel

from lanka_common.punctuation import normalise


class LLMUnavailable(RuntimeError):
    pass


class LLM(Protocol):
    name: str
    model: str

    async def generate(self, prompt: str, system: str | None = None) -> str: ...
    def stream(self, prompt: str, system: str | None = None) -> AsyncIterator[str]: ...
    async def generate_json(self, prompt: str, schema: type[BaseModel], system: str | None = None) -> BaseModel: ...
    async def ping(self) -> tuple[str, str]: ...


def extract_json(raw: str) -> dict[str, Any]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise LLMUnavailable(f"no JSON object in the model response: {raw[:160]!r}")
    return json.loads(raw[start : end + 1])


class _Breaker:
    def __init__(self, threshold: int = 3, cooldown_s: float = 30.0) -> None:
        self.threshold, self.cooldown_s = threshold, cooldown_s
        self.failures, self.opened_at = 0, 0.0

    def check(self) -> None:
        if self.failures >= self.threshold and time.monotonic() - self.opened_at < self.cooldown_s:
            raise LLMUnavailable("circuit open: the model endpoint failed repeatedly")

    def ok(self) -> None:
        self.failures = 0

    def fail(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = time.monotonic()


class Ollama:
    """Ollama /api/chat. Works against a local daemon signed in to Ollama cloud (the default,
    host.docker.internal:11434) or https://ollama.com with an API key."""

    name = "ollama"

    def __init__(self, base_url: str, model: str, api_key: str | None = None, think: str | None = None,
                 timeout_s: float = 90.0, concurrency: int = 4, num_ctx: int = 8192) -> None:
        self.base_url, self.model, self.think = base_url.rstrip("/"), model, think
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.AsyncClient(timeout=timeout_s, headers=headers)
        self._sem = asyncio.Semaphore(concurrency)
        self._breaker = _Breaker()
        self._options = {"num_ctx": num_ctx, "temperature": 0.2}

    def _body(self, prompt: str, system: str | None, stream: bool, fmt: Any = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model, "stream": stream, "options": self._options,
            "messages": ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}],
        }
        if self.think:
            body["think"] = self.think
        if fmt is not None:
            body["format"] = fmt
        return body

    async def generate(self, prompt: str, system: str | None = None) -> str:
        return "".join([piece async for piece in self.stream(prompt, system)])

    async def stream(self, prompt: str, system: str | None = None) -> AsyncIterator[str]:
        self._breaker.check()
        async with self._sem:
            try:
                async with self._http.stream("POST", f"{self.base_url}/api/chat",
                                             json=self._body(prompt, system, True)) as r:
                    r.raise_for_status()
                    async for line in r.aiter_lines():
                        if not line.strip():
                            continue
                        chunk = json.loads(line)
                        piece = (chunk.get("message") or {}).get("content") or ""
                        if piece:
                            yield normalise(piece)
                        if chunk.get("done"):
                            break
                self._breaker.ok()
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                self._breaker.fail()
                raise LLMUnavailable(f"ollama {self.model}: {type(exc).__name__}: {exc}") from exc

    async def generate_json(self, prompt: str, schema: type[BaseModel], system: str | None = None) -> BaseModel:
        self._breaker.check()
        async with self._sem:
            try:
                r = await self._http.post(f"{self.base_url}/api/chat",
                                          json=self._body(prompt, system, False, schema.model_json_schema()))
                r.raise_for_status()
                self._breaker.ok()
            except httpx.HTTPError as exc:
                self._breaker.fail()
                raise LLMUnavailable(f"ollama {self.model}: {exc}") from exc
        return schema.model_validate(extract_json(normalise(r.json()["message"]["content"])))

    async def ping(self) -> tuple[str, str]:
        try:
            r = await self._http.get(f"{self.base_url}/api/tags", timeout=5)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            return "down", f"{self.base_url} is not answering: {exc}"
        names = {m.get("name", "") for m in r.json().get("models", [])}
        if self.model in names or self.model.endswith("-cloud"):
            return "reachable", f"{self.model} is available"
        return "degraded", f"{self.model} is not among {len(names)} local models"


class OpenAICompatible:
    """Chat completions (Gemini's OpenAI endpoint, or any compatible provider)."""

    name = "gemini"

    def __init__(self, base_url: str, model: str, api_key: str | None, timeout_s: float = 60.0) -> None:
        self.base_url, self.model, self._key = base_url.rstrip("/"), model, api_key
        self._http = httpx.AsyncClient(timeout=timeout_s)
        self._breaker = _Breaker()

    def _headers(self) -> dict[str, str]:
        if not self._key:
            raise LLMUnavailable("no API key is configured for this endpoint")
        return {"Authorization": f"Bearer {self._key}"}

    async def generate(self, prompt: str, system: str | None = None) -> str:
        return "".join([p async for p in self.stream(prompt, system)])

    async def stream(self, prompt: str, system: str | None = None) -> AsyncIterator[str]:
        self._breaker.check()
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        try:
            async with self._http.stream("POST", f"{self.base_url}/chat/completions", headers=self._headers(),
                                         json={"model": self.model, "messages": messages, "stream": True,
                                               "temperature": 0.2}) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.startswith("data:") or line.strip() == "data: [DONE]":
                        continue
                    delta = json.loads(line[5:])["choices"][0].get("delta", {}).get("content")
                    if delta:
                        yield normalise(delta)
            self._breaker.ok()
        except (httpx.HTTPError, KeyError, json.JSONDecodeError) as exc:
            self._breaker.fail()
            raise LLMUnavailable(f"{self.model}: {exc}") from exc

    async def generate_json(self, prompt: str, schema: type[BaseModel], system: str | None = None) -> BaseModel:
        instruction = f"Reply with JSON only, matching this schema:\n{json.dumps(schema.model_json_schema())}"
        raw = await self.generate(prompt, f"{system}\n\n{instruction}" if system else instruction)
        return schema.model_validate(extract_json(raw))

    async def ping(self) -> tuple[str, str]:
        try:
            r = await self._http.get(f"{self.base_url}/models", headers=self._headers(), timeout=8)
            r.raise_for_status()
        except (httpx.HTTPError, LLMUnavailable) as exc:
            return "down", str(exc)
        return "reachable", f"{self.model} endpoint answered"


class Stub:
    """Deterministic, offline and still grounded (ported from v2 StubGenerator).

    Reads the machine readable hints the draft prompt embeds and writes a reply from the same
    causal booleans a model is told to use, so offline tests can assert grounding behaviour.
    """

    name = "stub"
    model = "stub-generator-1"

    async def generate(self, prompt: str, system: str | None = None) -> str:
        hints = _hints(prompt)
        s = set(hints.get("signals", []))
        lines = [f"Hello {hints.get('preferred_name') or 'there'},"]
        # The customer's own side first (a cable, the router), then anything on our side.
        head = ""
        if issue := hints.get("customer_issue"):
            head = f"Thank you for the details. From what you sent, {issue}."
            if steps := hints.get("customer_steps"):
                head += " Here is what to try on your side:\n" + "\n".join(
                    f"{i}. {step}" for i, step in enumerate(steps, 1)) + "\n"
            else:
                head += (" If you can, send a photo of the back of the router so we can see which socket the "
                         "cable belongs in.")
        if head:
            lines.append(head)
            if s & PROVIDER_STUB_SIGNALS:
                lines.append("There is also something on our side you should know about.")
        if "suspended_for_nonpayment" in s:
            lines.append(f"Your service is paused because {hints.get('outstanding_balance_display', 'a balance')} "
                         "is outstanding on the account. Service comes back once that payment is received.")
        if "outage_explains_symptom" in s or "in_active_outage" in s:
            lines.append("There is also an incident affecting your area at the moment. Our engineers are working "
                         f"on it and we expect service back by {hints.get('primary_eta_display', 'as soon as possible')}.")
        if "cpe_offline" in s and "outage_explains_symptom" not in s:
            lines.append("Your router has not reported in to our network, which points at the equipment itself "
                         "rather than the line.")
        if "has_unusual_charge" in s:
            lines.append("Your latest invoice has a charge on it that should not be there: "
                         f"{hints.get('unusual_total_display', 'the disputed amount')}.")
        if "at_top_of_catalogue" in s:
            lines.append("You are already on the fastest plan we offer, so there is no upgrade to move you to.")
        elif "over_fup" in s or "near_cap" in s:
            lines.append(f"You have used {hints.get('allowance_display', 'most of your allowance')} this cycle, "
                         "which is why speeds have dropped.")
        if "evening_congestion" in s:
            lines.append("Your line itself measures healthy. The evening slowdown is congestion on the shared "
                         "equipment in your area.")
        if "visit_already_booked" in s:
            lines.append(f"An engineer visit is already booked for {hints.get('next_appointment_display', 'your slot')}.")
        if len(lines) == 1:
            lines.append("Thank you for getting in touch. I have checked your account and everything reads as it "
                         "should. Tell me a little more and I will look further.")
        lines.append("If anything above does not match what you are seeing, reply and I will check again.")
        return normalise(lines[0] + " " + " ".join(lines[1:]))

    async def stream(self, prompt: str, system: str | None = None) -> AsyncIterator[str]:
        for part in re.split(r"(?<=[.!?])\s+", await self.generate(prompt, system)):
            yield part + " "

    async def generate_json(self, prompt: str, schema: type[BaseModel], system: str | None = None) -> BaseModel:
        payload: dict[str, Any] = {}
        for name, info in schema.model_fields.items():
            if info.is_required():
                payload[name] = False if info.annotation is bool else 0 if info.annotation in (int, float) else "stub"
        return schema.model_validate(payload)

    async def ping(self) -> tuple[str, str]:
        return "reachable", "the offline generator is always available"


PROVIDER_STUB_SIGNALS = frozenset({
    "suspended_for_nonpayment", "outage_explains_symptom", "in_active_outage", "has_unusual_charge",
    "evening_congestion", "over_fup", "near_cap", "visit_already_booked",
})


def _hints(prompt: str) -> dict[str, Any]:
    m = re.search(r"<!--grounding-hints\s*(\{.*?\})\s*-->", prompt, re.DOTALL)
    try:
        return json.loads(m.group(1)) if m else {}
    except json.JSONDecodeError:
        return {}


def build(impl: str, model: str, params: dict[str, Any] | None, env: dict[str, str]) -> LLM:
    """A generator for a binding row. Unknown or unconfigured impls raise LLMUnavailable."""
    params = params or {}
    if impl == "ollama":
        return Ollama(env.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434"), model,
                      api_key=env.get("OLLAMA_API_KEY") or None, think=params.get("think"))
    if impl == "gemini":
        return OpenAICompatible(env.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"),
                                model, env.get("GOOGLE_API_KEY"))
    if impl == "stub":
        return Stub()
    raise LLMUnavailable(f"no generator for implementation {impl!r}")
