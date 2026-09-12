import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jwt.algorithms import OKPAlgorithm

from app.jwks import InvalidToken, JwksVerifier

ISS = "http://localhost:8080"


def keypair(kid):
    priv = Ed25519PrivateKey.generate()
    jwk = json.loads(OKPAlgorithm.to_jwk(priv.public_key()))
    return priv, {**jwk, "kid": kid, "alg": "EdDSA"}


def token(priv, kid, **over):
    claims = {"sub": "u1", "iss": ISS, "aud": ISS, "exp": int(time.time()) + 60, "role": "agent"}
    claims.update(over)
    return jwt.encode(claims, priv, algorithm="EdDSA", headers={"kid": kid})


class Keys:
    def __init__(self, *jwks):
        self.jwks, self.calls = list(jwks), 0

    async def __call__(self):
        self.calls += 1
        return {"keys": self.jwks}


async def test_valid_token_and_cache():
    priv, jwk = keypair("k1")
    keys = Keys(jwk)
    v = JwksVerifier(keys, ISS)
    assert (await v.verify(token(priv, "k1")))["role"] == "agent"
    await v.verify(token(priv, "k1"))
    assert keys.calls == 1


async def test_rotation_picks_up_new_kid():
    p1, j1 = keypair("k1")
    p2, j2 = keypair("k2")
    keys = Keys(j1)
    v = JwksVerifier(keys, ISS, refresh_every_s=0)
    await v.verify(token(p1, "k1"))
    keys.jwks = [j1, j2]
    assert (await v.verify(token(p2, "k2")))["sub"] == "u1"


async def test_expired_rejected():
    priv, jwk = keypair("k1")
    v = JwksVerifier(Keys(jwk), ISS)
    with pytest.raises(InvalidToken):
        await v.verify(token(priv, "k1", exp=int(time.time()) - 10))


async def test_forged_signature_rejected():
    _, jwk = keypair("k1")
    forger, _ = keypair("k1")
    v = JwksVerifier(Keys(jwk), ISS)
    with pytest.raises(InvalidToken):
        await v.verify(token(forger, "k1"))


async def test_wrong_issuer_and_unknown_kid_throttled():
    priv, jwk = keypair("k1")
    keys = Keys(jwk)
    v = JwksVerifier(keys, ISS)
    with pytest.raises(InvalidToken):
        await v.verify(token(priv, "k1", iss="http://evil"))
    for _ in range(5):
        with pytest.raises(InvalidToken):
            await v.verify(token(priv, "nope"))
    assert keys.calls == 1


async def test_hs256_alg_confusion_rejected():
    _, jwk = keypair("k1")
    v = JwksVerifier(Keys(jwk), ISS)
    forged = jwt.encode({"sub": "u1", "iss": ISS, "aud": ISS, "exp": int(time.time()) + 60},
                        "secret", algorithm="HS256", headers={"kid": "k1"})
    with pytest.raises(InvalidToken):
        await v.verify(forged)
