"""Single sign-on over OpenID Connect.

These run against a real identity provider -- a small one, started for the test, that
publishes a discovery document and a JWKS and signs its own tokens. Mocking the
verification away would leave the only part that matters untested: an ID token is
worth exactly what checking it is worth.
"""

from __future__ import annotations

import http.server
import json
import socket
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwk, jwt

from webgate.auth import oidc
from webgate.runtime_config import store as runtime


class FakeIdp:
    """Publishes keys and signs tokens, the way a real provider does."""

    def __init__(self) -> None:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.private = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        public = (
            key.public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            .decode()
        )
        as_jwk = dict(jwk.construct(public, "RS256").to_dict(), kid="k1", use="sig", alg="RS256")
        self.jwks = json.loads(
            json.dumps(
                {"keys": [as_jwk]}, default=lambda b: b.decode() if isinstance(b, bytes) else b
            )
        )
        self.claims_override: dict[str, Any] = {}
        self.sign_with_other_key = False
        self.last_token_request: dict[str, list[str]] = {}

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = int(s.getsockname()[1])
        self.url = f"http://127.0.0.1:{self.port}"

        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.wrong_private = other.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()

        idp = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _send(self, payload: dict[str, Any]) -> None:
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                path = urlparse(self.path).path
                if path == "/.well-known/openid-configuration":
                    self._send(
                        {
                            "issuer": idp.url,
                            "authorization_endpoint": f"{idp.url}/authorize",
                            "token_endpoint": f"{idp.url}/token",
                            "jwks_uri": f"{idp.url}/jwks",
                            "id_token_signing_alg_values_supported": ["RS256"],
                        }
                    )
                elif path == "/jwks":
                    self._send(idp.jwks)
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                idp.last_token_request = parse_qs(self.rfile.read(length).decode())
                self._send({"id_token": idp.mint(), "token_type": "Bearer"})

            def log_message(self, *_a: Any) -> None:
                pass

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def mint(self) -> str:
        claims = {
            "iss": self.url,
            "aud": "webgate-client",
            "sub": "user-1",
            "exp": int(time.time()) + 300,
            "iat": int(time.time()),
            "preferred_username": "alice",
            "email": "alice@example.com",
            "groups": ["infra-oncall", "everyone"],
            **self.claims_override,
        }
        key = self.wrong_private if self.sign_with_other_key else self.private
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k1"})

    def stop(self) -> None:
        self._server.shutdown()


@pytest.fixture
def idp() -> Any:
    provider = FakeIdp()
    yield provider
    provider.stop()


@pytest.fixture
def configured(idp: Any) -> Any:
    oidc._discovery.clear()
    oidc._jwks.clear()
    runtime._overrides.update(
        {
            "oidc_enabled": True,
            "oidc_issuer": idp.url,
            "oidc_client_id": "webgate-client",
            "oidc_client_secret": "shh",
            "oidc_scopes": "openid profile email groups",
            "oidc_username_claim": "preferred_username",
            "oidc_groups_claim": "groups",
            "oidc_group_map": '{"infra-oncall": "prod"}',
            "oidc_admin_groups": '["infra-admins"]',
            "oidc_display_name": "Acme SSO",
        }
    )
    yield idp
    runtime._overrides.clear()
    oidc._discovery.clear()
    oidc._jwks.clear()


# --------------------------------------------------------------------- starting out


@pytest.mark.asyncio
async def test_the_sign_in_url_carries_state_nonce_and_a_pkce_challenge(
    configured: Any, db_session: Any
) -> None:
    url = await oidc.begin(db_session, "https://webgate.example.com/api/auth/sso/callback")
    query = parse_qs(urlparse(url).query)

    assert query["response_type"] == ["code"]
    assert query["client_id"] == ["webgate-client"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] and query["nonce"] and query["code_challenge"]
    # The verifier itself must never leave the gateway.
    assert "code_verifier" not in query


@pytest.mark.asyncio
async def test_it_refuses_when_nothing_is_configured(db_session: Any) -> None:
    runtime._overrides["oidc_enabled"] = False
    with pytest.raises(oidc.OidcError):
        await oidc.begin(db_session, "https://webgate.example.com/cb")


@pytest.mark.asyncio
async def test_an_unreachable_provider_says_so(db_session: Any) -> None:
    runtime._overrides.update({"oidc_enabled": True, "oidc_issuer": "http://127.0.0.1:1"})
    oidc._discovery.clear()
    with pytest.raises(oidc.OidcError) as exc:
        await oidc.begin(db_session, "https://webgate.example.com/cb")
    assert "identity provider" in str(exc.value)


# ---------------------------------------------------------------------- coming back


async def _round_trip(session: Any, idp: Any) -> dict[str, Any]:
    """A full sign-in, with the provider echoing the nonce the way a real one does.

    The nonce comes from the authorize request, which the test does not walk through,
    so the fake is told it here. Tests that want a mismatch override it afterwards.
    """
    url = await oidc.begin(session, "https://webgate.example.com/api/auth/sso/callback")
    state = parse_qs(urlparse(url).query)["state"][0]
    flow = await oidc.take_flow(session, state)
    idp.claims_override.setdefault("nonce", flow.nonce)
    return await oidc.complete(session, "the-code", flow)


@pytest.mark.asyncio
async def test_a_signed_token_from_the_provider_is_accepted(
    configured: Any, db_session: Any
) -> None:
    claims = await _round_trip(db_session, configured)
    assert claims["preferred_username"] == "alice"


@pytest.mark.asyncio
async def test_the_pkce_verifier_is_sent_and_matches_the_challenge(
    configured: Any, db_session: Any
) -> None:
    import base64
    import hashlib

    url = await oidc.begin(db_session, "https://webgate.example.com/cb")
    query = parse_qs(urlparse(url).query)
    flow = await oidc.take_flow(db_session, query["state"][0])
    configured.claims_override["nonce"] = flow.nonce
    await oidc.complete(db_session, "the-code", flow)

    sent = configured.last_token_request["code_verifier"][0]
    expected = base64.urlsafe_b64encode(hashlib.sha256(sent.encode()).digest()).decode().rstrip("=")
    assert expected == query["code_challenge"][0]


@pytest.mark.asyncio
async def test_a_token_signed_by_the_wrong_key_is_refused(configured: Any, db_session: Any) -> None:
    """The only thing standing between a forged identity and an admin session."""
    configured.sign_with_other_key = True
    with pytest.raises(oidc.OidcError) as exc:
        await _round_trip(db_session, configured)
    assert "did not verify" in str(exc.value)


@pytest.mark.asyncio
async def test_a_token_for_another_audience_is_refused(configured: Any, db_session: Any) -> None:
    configured.claims_override = {"aud": "some-other-app"}
    with pytest.raises(oidc.OidcError):
        await _round_trip(db_session, configured)


@pytest.mark.asyncio
async def test_an_expired_token_is_refused(configured: Any, db_session: Any) -> None:
    configured.claims_override = {"exp": int(time.time()) - 60}
    with pytest.raises(oidc.OidcError):
        await _round_trip(db_session, configured)


@pytest.mark.asyncio
async def test_a_token_from_another_sign_in_cannot_be_replayed(
    configured: Any, db_session: Any
) -> None:
    """Without the nonce check, a token captured from one flow works in another."""
    configured.claims_override = {"nonce": "a-nonce-from-somewhere-else"}
    with pytest.raises(oidc.OidcError) as exc:
        await _round_trip(db_session, configured)
    assert "different sign-in" in str(exc.value)


@pytest.mark.asyncio
async def test_an_unknown_state_is_refused(configured: Any, db_session: Any) -> None:
    with pytest.raises(oidc.OidcError) as exc:
        await oidc.take_flow(db_session, "never-issued")
    assert "no longer valid" in str(exc.value)


# ------------------------------------------------------------------ who they become


def test_groups_the_admin_has_not_mapped_grant_nothing(configured: Any) -> None:
    """A new directory group must not open a server group of the same name."""
    username, groups, is_admin = oidc.identity(
        {"preferred_username": "alice", "groups": ["infra-oncall", "prod", "everyone"]}
    )
    assert username == "alice"
    assert groups == ["prod"]  # from the mapping, not from the matching name
    assert is_admin is False


def test_membership_of_an_admin_group_grants_admin(configured: Any) -> None:
    _, _, is_admin = oidc.identity({"preferred_username": "alice", "groups": ["infra-admins"]})
    assert is_admin is True


def test_a_single_group_claim_is_accepted(configured: Any) -> None:
    """Some providers send one group as a bare string rather than a list."""
    _, groups, _ = oidc.identity({"preferred_username": "bob", "groups": "infra-oncall"})
    assert groups == ["prod"]


def test_the_username_falls_back_through_the_usual_claims(configured: Any) -> None:
    runtime._overrides["oidc_username_claim"] = "not_sent"
    assert oidc.identity({"email": "carol@example.com"})[0] == "carol@example.com"
    assert oidc.identity({"sub": "abc-123"})[0] == "abc-123"


def test_a_token_with_no_usable_username_says_which_setting_to_change(configured: Any) -> None:
    runtime._overrides["oidc_username_claim"] = "not_sent"
    with pytest.raises(oidc.OidcError) as exc:
        oidc.identity({"groups": ["infra-oncall"]})
    assert "username claim" in str(exc.value)


def test_a_broken_group_mapping_grants_nothing_rather_than_everything(configured: Any) -> None:
    runtime._overrides["oidc_group_map"] = "not json at all"
    assert oidc.identity({"preferred_username": "alice", "groups": ["infra-oncall"]})[1] == []


# --------------------------------------------------------------------- the handover


@pytest.mark.asyncio
async def test_the_session_token_never_travels_in_a_url(configured: Any, db_session: Any) -> None:
    """The callback hands the page a one-time code, not a session. A token in a
    redirect ends up in browser history and in every proxy log on the way."""
    url = await oidc.begin(db_session, "https://webgate.example.com/cb")
    flow = await oidc.take_flow(db_session, parse_qs(urlparse(url).query)["state"][0])
    code = await oidc.issue_handover(db_session, flow, user_id=7)

    assert code and "." not in code  # not a JWT
    assert await oidc.redeem_handover(db_session, code) == 7


@pytest.mark.asyncio
async def test_a_handover_code_works_once(configured: Any, db_session: Any) -> None:
    url = await oidc.begin(db_session, "https://webgate.example.com/cb")
    flow = await oidc.take_flow(db_session, parse_qs(urlparse(url).query)["state"][0])
    code = await oidc.issue_handover(db_session, flow, user_id=7)

    await oidc.redeem_handover(db_session, code)
    with pytest.raises(oidc.OidcError):
        await oidc.redeem_handover(db_session, code)


@pytest.mark.asyncio
async def test_an_unknown_handover_code_is_refused(configured: Any, db_session: Any) -> None:
    with pytest.raises(oidc.OidcError):
        await oidc.redeem_handover(db_session, "made-up")


# ------------------------------------------------------------------- what the UI sees


@pytest.mark.asyncio
async def test_the_sign_in_screen_is_told_before_anyone_authenticates(
    configured: Any, client: Any
) -> None:
    body = (await client.get("/api/config")).json()
    assert body["sso_enabled"] is True
    assert body["sso_name"] == "Acme SSO"


@pytest.mark.asyncio
async def test_nothing_is_advertised_when_sso_is_off(client: Any) -> None:
    runtime._overrides["oidc_enabled"] = False
    body = (await client.get("/api/config")).json()
    assert body["sso_enabled"] is False
    assert body["sso_name"] == ""
