"use client";

import { fetchEventSource } from "@microsoft/fetch-event-source";
import { useCallback, useEffect, useState } from "react";

import { authClient } from "@/lib/auth-client";

/** Short-lived JWT for the gateway, held in memory only (never in storage). */
let token: string | null = null;
let expires = 0;

export async function bearer(): Promise<string | null> {
  if (token && Date.now() < expires - 60_000) return token;
  const { data } = await authClient.token();
  token = data?.token ?? null;
  expires = Date.now() + 14 * 60_000;
  return token;
}

export function forgetToken() {
  token = null;
  expires = 0;
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

/** Load once, reload on demand. Errors come back as plain sentences. */
export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(path !== null);

  const reload = useCallback(async () => {
    if (path === null) return;
    try {
      setData(await api<T>(path));
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
