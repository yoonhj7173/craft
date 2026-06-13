"""Shared pytest fixtures — Clerk JWT stub + authenticated TestClient.

test_auth.py는 검증 로직 자체를 보느라 자체 토큰 헬퍼를 들고 있지만, 비즈니스 라우터
테스트(test_projects 등)는 "유효한 사용자로 인증된 클라이언트"만 있으면 된다. 그 공용
픽스처를 여기 둔다 — 로컬 RSA로 토큰을 서명하고 JWKS fetch를 stub해서 결정적으로 통과시킨다.

라이브 Postgres 전제(docker-compose). 테스트는 실제 DB에 행을 만들고 정리한다.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.auth import ClerkTokenVerifier, get_verifier
from app.main import app

TEST_ISSUER = "https://test-instance.clerk.accounts.dev"
TEST_JWKS_URL = f"{TEST_ISSUER}/.well-known/jwks.json"
KID = "conftest-kid-1"

_priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks_json() -> str:
    pub_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(_priv.public_key(), as_dict=True)
    pub_jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})
    return json.dumps({"keys": [pub_jwk]})


def _verifier() -> ClerkTokenVerifier:
    return ClerkTokenVerifier(issuer=TEST_ISSUER, jwks_url=TEST_JWKS_URL)


@pytest.fixture
def stub_jwks(monkeypatch):
    def fake_fetch_data(self):
        return json.loads(_jwks_json())

    monkeypatch.setattr("jwt.PyJWKClient.fetch_data", fake_fetch_data)


@pytest.fixture
def make_token() -> Callable[..., str]:
    """유효한 Clerk 스타일 JWT를 발급하는 헬퍼를 반환한다. `make_token(sub=...)`."""

    def _make(*, sub: str = "user_test", exp_delta: int = 3600) -> str:
        now = dt.datetime.now(tz=dt.timezone.utc)
        payload = {
            "sub": sub,
            "iss": TEST_ISSUER,
            "iat": now,
            "nbf": now,
            "exp": now + dt.timedelta(seconds=exp_delta),
        }
        return jwt.encode(payload, _priv, algorithm="RS256", headers={"kid": KID})

    return _make


@pytest.fixture
def client(stub_jwks):
    """인증 검증기를 테스트 키로 오버라이드한 TestClient."""
    app.dependency_overrides[get_verifier] = _verifier
    c = TestClient(app)
    yield c
    app.dependency_overrides.pop(get_verifier, None)


@pytest.fixture(autouse=True)
def _disable_rate_limit():
    """테스트는 레이트 리밋 비활성(다수 요청이 429로 flaky해지지 않게). 리밋 자체는 별도 검증."""
    from app.main import limiter
    limiter.enabled = False
    yield
    limiter.enabled = True


@pytest.fixture(autouse=True)
def _force_local_sandbox():
    """테스트는 절대 실 E2B를 치지 않는다 — E2B_API_KEY가 있어도 워크스페이스 싱글턴을 Local로 강제."""
    from app.services.sandbox import LocalSandboxProvider
    from app.services.workspace import workspace_service
    prev = workspace_service.provider
    workspace_service.provider = LocalSandboxProvider()
    yield
    for sid in list(getattr(workspace_service.provider, "_dirs", {}).keys()):
        workspace_service.provider.destroy(sid)
    workspace_service.provider = prev


@pytest.fixture
def auth(make_token):
    """`auth(sub)` → Authorization 헤더 dict. 테스트 가독성용 단축 헬퍼."""

    def _auth(sub: str = "user_test") -> dict[str, str]:
        return {"Authorization": f"Bearer {make_token(sub=sub)}"}

    return _auth
