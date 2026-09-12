"""Verify Better Auth EdDSA JWTs against the auth service's JWKS.

Keys are cached by kid. An unknown kid triggers one refetch (key rotation), throttled so a
stream of forged kids cannot hammer the auth service.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

import jwt

Fetch = Callable[[], Awaitable[dict[str, Any]]]


class InvalidToken(Exception):
    pass


class JwksVerifier:
    def __init__(self, fetch: Fetch, issuer: str, refresh_every_s: float = 30.0) -> None:
        self._fetch = fetch
        self._issuer = issuer
        self._keys: dict[str, jwt.PyJWK] = {}
        self._refreshed_at = float("-inf")
        self._refresh_every_s = refresh_every_s

    async def _refresh(self) -> None:
        if time.monotonic() - self._refreshed_at < self._refresh_every_s:
            return
        self._refreshed_at = time.monotonic()
        doc = await self._fetch()
        self._keys = {k["kid"]: jwt.PyJWK(k) for k in doc.get("keys", []) if "kid" in k}

    async def verify(self, token: str) -> dict[str, Any]:
        try:
            kid = jwt.get_unverified_header(token).get("kid")
        except jwt.PyJWTError as exc:
            raise InvalidToken("malformed token") from exc
        if kid not in self._keys:
            await self._refresh()
        key = self._keys.get(kid)
        if key is None:
            raise InvalidToken("unknown signing key")
        try:
            return jwt.decode(
                token,
                key.key,
                algorithms=["EdDSA"],
                issuer=self._issuer,
                audience=self._issuer,
                options={"require": ["exp", "sub", "iss"]},
            )
        except jwt.PyJWTError as exc:
            raise InvalidToken(str(exc)) from exc
