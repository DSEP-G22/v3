"use client";

import { fetchEventSource } from "@microsoft/fetch-event-source";
import { useCallback, useEffect, useState } from "react";

import { authClient } from "@/lib/auth-client";

/** Short-lived JWT for the gateway, held in memory only (never in storage). */
let token: string | null = null;
let expires = 0;
let pending: Promise<string | null> | null = null;

export async function bearer(): Promise<string | null> {
  if (token && Date.now() < expires - 60_000) return token;
  // One token request however many calls a page starts at once.
  pending ??= authClient.token().then(({ data }) => {
    token = data?.token ?? null;
    expires = Date.now() + 14 * 60_000;
    return token;
  }).finally(() => { pending = null; });
  return pending;
}

export function forgetToken() {
  token = null;
  expires = 0;
  cache.clear();
}

/** Last good response per path, so a page seen before renders at once and refreshes behind. */
const cache = new Map<string, unknown>();
const inflight = new Map<string, Promise<unknown>>();

/** GET with in-flight sharing: two components asking for the same path make one request. */
function load<T>(path: string): Promise<T> {
  let p = inflight.get(path) as Promise<T> | undefined;
  if (!p) {
    p = api<T>(path).then((d) => { cache.set(path, d); return d; }).finally(() => inflight.delete(path));
    inflight.set(path, p);
  }
  return p;
}

/** Warm the cache for a page the user is likely to open next (a hovered link, say). */
export function prefetch(path: string) {
  if (!cache.has(path)) void load(path).catch(() => undefined);
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  const t = await bearer();
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(t ? { authorization: `Bearer ${t}` } : {}),
      ...init.headers,
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : "Something went wrong. Try again.";
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const post = <T = unknown>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

/**
 * Stale while revalidate: a path seen before renders from memory at once and refreshes in the
 * background; only a first visit shows a loading state. Errors come back as plain sentences.
 */
export function useApi<T>(path: string | null) {
  const cached = path === null ? undefined : (cache.get(path) as T | undefined);
  const [data, setData] = useState<T | null>(cached ?? null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(path !== null && cached === undefined);
  const [shownPath, setShownPath] = useState(path);

  // A new path (another case, another filter): show its cached copy, or load it fresh.
  if (shownPath !== path) {
    setShownPath(path);
    setData(cached ?? null);
    setLoading(path !== null && cached === undefined);
  }

  const reload = useCallback(async () => {
    if (path === null) return;
    try {
      setData(await load<T>(path));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, "We could not reach Lanka Link."));
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, error, loading, reload };
}

/** Re-run fn every ms while the tab is visible (live boards). */
export function usePoll(fn: () => void, ms: number) {
  useEffect(() => {
    const t = setInterval(() => {
      if (!document.hidden) fn();
    }, ms);
    return () => clearInterval(t);
  }, [fn, ms]);
}

/** Per-user server events (account changes, replies, stage chips). Reconnects on its own. */
export function useEvents(onEvent: (kind: string, data: unknown) => void) {
  useStream("/stream", onEvent);
}

/** Any gateway SSE endpoint (a case's token stream, the sim lab). null disables it. */
export function useStream(path: string | null, onEvent: (kind: string, data: unknown) => void) {
  useEffect(() => {
    if (!path) return;
    const ctrl = new AbortController();
    void (async () => {
      const t = await bearer();
      if (!t) return;
      await fetchEventSource(`/api${path}`, {
        headers: { authorization: `Bearer ${t}` },
        signal: ctrl.signal,
        openWhenHidden: true,
        onmessage: (m) => {
          if (m.event) onEvent(m.event, m.data ? JSON.parse(m.data) : null);
        },
      });
    })();
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path]);
}
