"""Groq's 429: wait as long as it asks, then try again, before the binding gives up."""

from __future__ import annotations

import asyncio

import httpx

from lanka_common import llm


def test_a_429_is_retried_after_the_wait_it_asks_for(monkeypatch):
    calls, waits = [], []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "3"})
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"Hello"}}]}\n\ndata: [DONE]\n')

    async def no_sleep(s):
        waits.append(s)

    monkeypatch.setattr(llm.asyncio, "sleep", no_sleep)
    m = llm.build("groq", "openai/gpt-oss-20b", {}, {"GROQ_API_KEY": "k"})
    m._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert asyncio.run(m.generate("hi")) == "Hello"
    assert (len(calls), waits) == (2, [3.0])
    body = calls[0].read().decode()
    assert '"max_tokens":1024' in body.replace(" ", "") and "reasoning_effort" in body


def test_retry_after_is_capped_and_defaults():
    assert llm.retry_after("999") == llm.MAX_RETRY_WAIT_S
    assert llm.retry_after(None) == llm.retry_after("soon") == 5.0


def test_a_refusal_keeps_the_providers_reason():
    m = llm.build("groq", "openai/gpt-oss-20b", {}, {"GROQ_API_KEY": "k"})
    m._http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(400, json={"error": {"message": "model decommissioned"}})))
    try:
        asyncio.run(m.generate("hi"))
    except llm.LLMUnavailable as exc:
        assert "model decommissioned" in str(exc)
    else:
        raise AssertionError("a 400 must raise")
