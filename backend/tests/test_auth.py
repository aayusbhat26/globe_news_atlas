"""Reader account security regression tests."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app.auth import google as google_service
from app.auth.security import (
    _totp_at,
    now_ts,
    sanitize_next_path,
    verify_password,
    verify_totp,
)
from app.auth.store import auth_store
from app.config import settings
from app.main import app
from app.middleware.rate_limit import limiter

PASSWORD = "Verdant-Harbor-92!"
NEW_PASSWORD = "Cobalt-Lantern-47!"


@pytest.fixture()
def auth_env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "auth_db_backend", "sqlite")
    monkeypatch.setattr(settings, "auth_db_path", str(tmp_path / "auth.db"))
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "auth_secret", "test-secret-for-auth-regressions")
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "auth_check_breached_passwords", False)
    monkeypatch.setattr(settings, "email_provider", "dev")
    monkeypatch.setattr(settings, "app_base_url", "http://localhost:5173")
    monkeypatch.setattr(settings, "public_base_url", "http://localhost:8000")
    monkeypatch.setattr(settings, "google_client_id", None)
    monkeypatch.setattr(settings, "google_client_secret", None)
    monkeypatch.setattr(settings, "google_redirect_uri", None)
    monkeypatch.setattr(settings, "auth_cookie_secure", None)
    monkeypatch.setattr(settings, "auth_cookie_samesite", "lax")
    monkeypatch.setattr(settings, "auth_lockout_attempts", 8)
    monkeypatch.setattr(settings, "auth_session_ttl_hours", 168)
    monkeypatch.setattr(settings, "auth_session_remember_ttl_hours", 720)
    auth_store.reset_runtime_state()
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture()
def client(auth_env):
    with TestClient(app) as test_client:
        yield test_client


def csrf(client: TestClient) -> str:
    if not client.cookies.get("gna_csrf"):
        client.get("/v1/auth/csrf")
    return client.cookies.get("gna_csrf")


def post(client: TestClient, path: str, payload: dict, **kwargs):
    headers = {"X-CSRF-Token": csrf(client), **kwargs.pop("headers", {})}
    return client.post(path, json=payload, headers=headers, **kwargs)


def delete(client: TestClient, path: str):
    return client.delete(path, headers={"X-CSRF-Token": csrf(client)})


def token_from_link(link: str) -> str:
    return parse_qs(urlsplit(link).query)["token"][0]


def create_verified_account(client: TestClient, email: str = "reader@example.com") -> dict:
    response = post(
        client,
        "/v1/auth/signup",
        {
            "email": email,
            "password": PASSWORD,
            "display_name": "Ada Reader",
            "remember": False,
            "accept_terms": True,
            "website": "",
        },
    )
    assert response.status_code == 201, response.text
    token = token_from_link(response.json()["dev_verification_link"])
    verified = post(client, "/v1/auth/email/verify", {"token": token})
    assert verified.status_code == 200, verified.text
    return verified.json()


def login(client: TestClient, email: str = "reader@example.com", password: str = PASSWORD):
    return post(
        client,
        "/v1/auth/login",
        {"email": email, "password": password, "remember": False},
    )


def test_signup_requires_csrf(client):
    response = client.post(
        "/v1/auth/signup",
        json={
            "email": "reader@example.com",
            "password": PASSWORD,
            "accept_terms": True,
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "csrf_failed"


def test_signup_verify_and_session_cookie(client):
    response = post(
        client,
        "/v1/auth/signup",
        {
            "email": "reader@example.com",
            "password": PASSWORD,
            "display_name": "",
            "remember": False,
            "accept_terms": True,
            "website": "",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "check_email"
    assert body["dev_verification_link"].startswith("http://localhost:5173/verify-email")
    assert "gna_session" not in response.cookies

    token = token_from_link(body["dev_verification_link"])
    check = client.get(f"/v1/auth/email/verify/check?token={token}")
    assert check.status_code == 200
    assert check.json()["valid"] is True
    assert check.json()["email_masked"] == "r***@example.com"

    verified = post(client, "/v1/auth/email/verify", {"token": token})
    assert verified.status_code == 200
    assert verified.json()["user"]["email_verified"] is True
    assert verified.json()["user"]["display_name"] == "Reader"
    assert verified.cookies.get("gna_session")
    set_cookie = verified.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie

    me = client.get("/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "reader@example.com"

    replay = post(client, "/v1/auth/email/verify", {"token": token})
    assert replay.status_code == 400


def test_signup_rejects_weak_password_and_honeypot(client):
    weak = post(
        client,
        "/v1/auth/signup",
        {
            "email": "weak@example.com",
            "password": "short",
            "accept_terms": True,
        },
    )
    assert weak.status_code == 400
    assert weak.json()["detail"]["code"] == "weak_password"

    bot = post(
        client,
        "/v1/auth/signup",
        {
            "email": "bot@example.com",
            "password": PASSWORD,
            "accept_terms": True,
            "website": "https://spam.example",
        },
    )
    assert bot.status_code == 400
    assert bot.json()["detail"]["code"] == "signup_blocked"

    terms = client.post(
        "/v1/auth/signup",
        headers={"X-CSRF-Token": csrf(client)},
        json={"email": "terms@example.com", "password": PASSWORD, "accept_terms": False},
    )
    assert terms.status_code == 422


def test_duplicate_signup_uses_generic_message(client):
    first = post(
        client,
        "/v1/auth/signup",
        {
            "email": "reader@example.com",
            "password": PASSWORD,
            "accept_terms": True,
        },
    )
    assert first.status_code == 201

    second = post(
        client,
        "/v1/auth/signup",
        {
            "email": "READER@example.com",
            "password": "Another-Strong-91!",
            "accept_terms": True,
        },
    )
    assert second.status_code == 201
    assert second.json()["status"] == "check_email"
    assert second.json()["message"].startswith("If this address")


def test_login_failures_are_generic_and_lock_the_account(client):
    create_verified_account(client)
    post(client, "/v1/auth/logout", {})

    known = login(client, password="Wrong-Password-11!")
    unknown = login(client, email="nobody@example.com", password="Wrong-Password-11!")
    assert known.status_code == unknown.status_code == 401
    assert known.json()["detail"]["message"] == unknown.json()["detail"]["message"]

    for _ in range(settings.auth_lockout_attempts - 1):
        login(client, password="Wrong-Password-11!")

    locked = login(client)
    assert locked.status_code == 429
    assert locked.json()["detail"]["code"] == "account_locked"


def test_login_remember_and_csrf_rotation(client):
    create_verified_account(client)
    post(client, "/v1/auth/logout", {})
    before = csrf(client)
    result = post(
        client,
        "/v1/auth/login",
        {"email": "reader@example.com", "password": PASSWORD, "remember": True},
    )
    assert result.status_code == 200
    assert result.json()["two_factor_required"] is False
    after = csrf(client)
    assert before != after
    session = client.get("/v1/auth/me").json()
    assert session["expires_at"]


def test_origin_checks_apply_to_mutations(client):
    create_verified_account(client)
    bad = post(
        client,
        "/v1/auth/logout",
        {},
        headers={"Origin": "https://evil.example"},
    )
    assert bad.status_code == 403
    assert bad.json()["detail"]["code"] == "origin_rejected"

    good = post(
        client,
        "/v1/auth/logout",
        {},
        headers={"Origin": "http://localhost:5173"},
    )
    assert good.status_code == 200


def test_profile_and_password_change_revoke_other_sessions(client):
    create_verified_account(client)
    other = TestClient(app)
    csrf(other)
    assert login(other).status_code == 200

    profile = post(client, "/v1/auth/profile", {"display_name": "Ada Lovelace"})
    assert profile.status_code == 200
    assert profile.json()["user"]["display_name"] == "Ada Lovelace"

    change = post(
        client,
        "/v1/auth/password/change",
        {"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert change.status_code == 200
    assert change.json()["user"]["has_password"] is True

    assert client.get("/v1/auth/me").status_code == 200
    assert other.get("/v1/auth/me").json()["user"] is None
    assert login(other, password=PASSWORD).status_code == 401
    assert login(other, password=NEW_PASSWORD).status_code == 200


def test_session_list_and_revocation(client):
    create_verified_account(client)
    other = TestClient(app)
    csrf(other)
    login(other)

    sessions = client.get("/v1/auth/sessions").json()["sessions"]
    assert len(sessions) == 2
    current = next(item for item in sessions if item["current"])
    other_session = next(item for item in sessions if not item["current"])

    current_revoke = post(client, f"/v1/auth/sessions/{current['id']}/revoke", {})
    assert current_revoke.status_code == 400

    revoked = post(client, f"/v1/auth/sessions/{other_session['id']}/revoke", {})
    assert revoked.status_code == 200
    assert other.get("/v1/auth/me").json()["user"] is None

    assert login(other).status_code == 200
    revoke_others = post(client, "/v1/auth/sessions/revoke-others", {})
    assert revoke_others.status_code == 200
    assert other.get("/v1/auth/me").json()["user"] is None


def test_expired_session_is_rejected(client):
    create_verified_account(client)
    with auth_store.connection() as conn:
        conn.execute("UPDATE sessions SET expires_at = ?", (now_ts() - 5,))
    assert client.get("/v1/auth/me").json()["user"] is None


def test_password_reset_flow_and_token_single_use(client):
    create_verified_account(client)
    email = "reader@example.com"
    post(client, "/v1/auth/logout", {})

    forgot = post(client, "/v1/auth/password/forgot", {"email": email})
    assert forgot.status_code == 200
    assert forgot.json()["message"].startswith("If an account exists")
    link = forgot.json()["dev_reset_link"]
    token = token_from_link(link)

    check = client.get(f"/v1/auth/password/reset/check?token={token}")
    assert check.json()["valid"] is True
    assert check.json()["email_masked"] == "r***@example.com"

    reset = post(client, "/v1/auth/password/reset", {"token": token, "password": NEW_PASSWORD})
    assert reset.status_code == 200
    assert login(client, password=PASSWORD).status_code == 401
    assert login(client, password=NEW_PASSWORD).status_code == 200

    replay = post(client, "/v1/auth/password/reset", {"token": token, "password": PASSWORD})
    assert replay.status_code == 400


def test_two_factor_enrollment_login_and_recovery_code(client):
    create_verified_account(client)
    setup = post(client, "/v1/auth/2fa/setup", {"password": PASSWORD})
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    assert setup.json()["otpauth_uri"].startswith("otpauth://totp/")
    assert setup.json()["qr_data_uri"].startswith("data:image/svg+xml;base64,")

    step = now_ts() // 30
    enabled = post(client, "/v1/auth/2fa/enable", {"code": _totp_at(secret, step)})
    assert enabled.status_code == 200, enabled.text
    codes = enabled.json()["recovery_codes"]
    assert len(codes) == 10
    assert enabled.json()["user"]["totp_enabled"] is True

    assert post(client, "/v1/auth/logout", {}).status_code == 200
    challenged = login(client)
    assert challenged.status_code == 200
    payload = challenged.json()
    assert payload["two_factor_required"] is True
    challenge = payload["challenge_token"]
    assert payload["email_masked"] == "r***@example.com"

    wrong = post(
        client,
        "/v1/auth/login/2fa",
        {"challenge_token": challenge, "code": "000000", "remember": False},
    )
    assert wrong.status_code == 401

    replayed = post(
        client,
        "/v1/auth/login/2fa",
        {"challenge_token": challenge, "code": _totp_at(secret, step), "remember": True},
    )
    assert replayed.status_code == 401

    next_step = step + 1
    signed_in = post(
        client,
        "/v1/auth/login/2fa",
        {"challenge_token": challenge, "code": _totp_at(secret, next_step), "remember": True},
    )
    assert signed_in.status_code == 200, signed_in.text
    me = client.get("/v1/auth/me").json()["user"]
    assert me["totp_enabled"] is True
    assert me["recovery_codes_remaining"] == 10

    assert post(client, "/v1/auth/logout", {}).status_code == 200
    challenged = login(client).json()
    recovery = post(
        client,
        "/v1/auth/login/2fa",
        {"challenge_token": challenged["challenge_token"], "code": codes[0]},
    )
    assert recovery.status_code == 200, recovery.text
    assert client.get("/v1/auth/me").json()["user"]["recovery_codes_remaining"] == 9

    disable = post(
        client,
        "/v1/auth/2fa/disable",
        {"password": PASSWORD, "code": codes[1]},
    )
    assert disable.status_code == 200, disable.text
    assert disable.json()["user"]["totp_enabled"] is False


def test_delete_account(client):
    create_verified_account(client)
    deleted = post(
        client,
        "/v1/auth/account/delete",
        {"password": PASSWORD, "confirm_email": "reader@example.com"},
    )
    assert deleted.status_code == 200
    assert client.get("/v1/auth/me").json()["user"] is None
    assert login(client).status_code == 401


def test_google_id_token_claims_are_verified(monkeypatch):
    import time
    from types import SimpleNamespace

    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    monkeypatch.setattr(settings, "google_client_id", "test-client-id")
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    monkeypatch.setattr(
        google_service,
        "_jwk_client",
        SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=public_key)),
    )

    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": "test-client-id",
        "sub": "google-subject-42",
        "email": "Verified@Example.com",
        "email_verified": True,
        "name": "Verified Reader",
        "nonce": "expected-nonce",
        "iat": now,
        "exp": now + 300,
    }
    token = jwt.encode(claims, private_key, algorithm="RS256")
    profile = google_service.verify_id_token(token, "expected-nonce")
    assert profile.subject == "google-subject-42"
    assert profile.email == "verified@example.com"
    assert profile.name == "Verified Reader"

    with pytest.raises(google_service.GoogleAuthError) as wrong_nonce:
        google_service.verify_id_token(token, "different-nonce")
    assert wrong_nonce.value.code == "google_nonce_mismatch"

    unverified = jwt.encode(
        {**claims, "email_verified": False}, private_key, algorithm="RS256"
    )
    with pytest.raises(google_service.GoogleAuthError) as unverified_error:
        google_service.verify_id_token(unverified, "expected-nonce")
    assert unverified_error.value.code == "google_email_unverified"

    wrong_audience = jwt.encode(
        {**claims, "aud": "another-client"}, private_key, algorithm="RS256"
    )
    with pytest.raises(google_service.GoogleAuthError) as audience_error:
        google_service.verify_id_token(wrong_audience, "expected-nonce")
    assert audience_error.value.code == "google_invalid_token"


def test_google_start_and_callback(monkeypatch, client):
    monkeypatch.setattr(settings, "google_client_id", "test-client-id")
    monkeypatch.setattr(settings, "google_client_secret", "test-client-secret")
    monkeypatch.setattr(
        google_service,
        "exchange_code",
        lambda code, verifier, callback: "signed-id-token",
    )
    monkeypatch.setattr(
        google_service,
        "verify_id_token",
        lambda token, nonce: google_service.GoogleProfile(
            subject="google-subject-1",
            email="oauth.reader@example.com",
            email_verified=True,
            name="OAuth Reader",
            picture=None,
        ),
    )

    start = client.get("/v1/auth/google/start?next=/account", follow_redirects=False)
    assert start.status_code == 302
    location = start.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    query = parse_qs(urlsplit(location).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["client_id"] == ["test-client-id"]
    state = query["state"][0]
    assert start.cookies.get("gna_oauth_state") == state

    callback = client.get(
        f"/v1/auth/google/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert callback.status_code == 302, callback.text
    assert callback.headers["location"] == "http://localhost:5173/account"
    assert callback.cookies.get("gna_session")

    me = client.get("/v1/auth/me")
    assert me.status_code == 200
    user = me.json()["user"]
    assert user["email"] == "oauth.reader@example.com"
    assert user["email_verified"] is True
    assert user["google_linked"] is True
    assert user["has_password"] is False

    replay = client.get(
        f"/v1/auth/google/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert replay.status_code == 302
    assert "error=google_state" in replay.headers["location"]

    fresh = client.get("/v1/auth/google/start?next=/", follow_redirects=False)
    fresh_state = parse_qs(urlsplit(fresh.headers["location"]).query)["state"][0]
    bad = client.get(
        f"/v1/auth/google/callback?code=abc&state={fresh_state}",
        headers={"Cookie": "gna_oauth_state=wrong"},
        follow_redirects=False,
    )
    assert bad.status_code == 302
    assert "error=google_state" in bad.headers["location"]


def test_google_connect_requires_signed_in_user(monkeypatch, client):
    monkeypatch.setattr(settings, "google_client_id", "test-client-id")
    monkeypatch.setattr(settings, "google_client_secret", "test-client-secret")
    monkeypatch.setattr(
        google_service,
        "exchange_code",
        lambda code, verifier, callback: "signed-id-token",
    )
    monkeypatch.setattr(
        google_service,
        "verify_id_token",
        lambda token, nonce: google_service.GoogleProfile(
            subject="google-subject-connect",
            email="reader@example.com",
            email_verified=True,
            name="Ada Reader",
            picture=None,
        ),
    )
    create_verified_account(client)

    connect = post(client, "/v1/auth/google/connect", {})
    assert connect.status_code == 200
    location = connect.json()["url"]
    state = parse_qs(urlsplit(location).query)["state"][0]
    assert client.cookies.get("gna_oauth_state") == state

    callback = client.get(
        f"/v1/auth/google/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert callback.status_code == 302
    assert callback.headers["location"] == "http://localhost:5173/account"
    me = client.get("/v1/auth/me").json()["user"]
    assert me["google_linked"] is True

    unlinked = post(client, "/v1/auth/google/unlink", {"password": PASSWORD})
    assert unlinked.status_code == 200
    assert unlinked.json()["user"]["google_linked"] is False


def test_production_cookies_are_secure(client, monkeypatch):
    create_verified_account(client)
    post(client, "/v1/auth/logout", {})
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "auth_cookie_secure", True)
    csrf(client)
    response = login(client)
    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie", "")
    assert "Secure" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie


def test_email_sender_address_parsing():
    from app.auth.email import _split_address

    assert _split_address("Globe News Atlas <no-reply@example.com>") == (
        "Globe News Atlas",
        "no-reply@example.com",
    )
    assert _split_address("no-reply@example.com") == ("", "no-reply@example.com")


def test_password_primitives_and_path_sanitising():
    from app.auth.security import hash_password

    hashed = hash_password(PASSWORD)
    valid, needs_rehash = verify_password(PASSWORD, hashed)
    assert valid is True
    assert needs_rehash is False
    assert verify_password("not-the-password", hashed)[0] is False
    assert verify_password("anything", None)[0] is False
    assert sanitize_next_path("//evil.example") == "/"
    assert sanitize_next_path("https://evil.example") == "/"
    assert sanitize_next_path("/account?tab=security") == "/account?tab=security"


def test_totp_window_and_replay():
    secret = "JBSWY3DPEHPK3PXP"
    step = now_ts() // 30
    code = _totp_at(secret, step)
    ok, used_step = verify_totp(secret, code)
    assert ok is True and used_step == step
    assert verify_totp(secret, code, last_used_step=used_step)[0] is False
    assert verify_totp(secret, "000000")[0] is False
    assert verify_totp(secret, "not-a-code")[0] is False


def test_watchline_crud_and_capacity(client):
    create_verified_account(client, "watchline@example.com")
    status = client.get("/v1/watchline/entries")
    assert status.status_code == 200
    assert status.json()["entries"] == []

    first = post(
        client,
        "/v1/watchline/entries",
        {"kind": "place", "key": "India", "label": "India"},
    )
    assert first.status_code == 201, first.text
    entry = first.json()["entry"]
    assert entry["kind"] == "place"
    assert entry["key"] == "india"

    repeat = post(
        client,
        "/v1/watchline/entries",
        {"kind": "place", "key": "india", "label": "India"},
    )
    assert repeat.status_code == 201
    assert repeat.json()["status"] == "exists"

    for index in range(7):
        added = post(
            client,
            "/v1/watchline/entries",
            {"kind": "place", "key": f"Country {index}", "label": f"Country {index}"},
        )
        assert added.status_code == 201, added.text

    full = post(
        client,
        "/v1/watchline/entries",
        {"kind": "place", "key": "Atlantis", "label": "Atlantis"},
    )
    assert full.status_code == 409
    assert full.json()["detail"]["code"] == "watchline_full"

    removed = delete(client, f"/v1/watchline/entries/{entry['id']}")
    assert removed.status_code == 200
    assert len(removed.json()["entries"]) == 7

    feed = client.get("/v1/watchline?window=24h")
    assert feed.status_code == 200
    payload = feed.json()
    assert payload["capacity"] == 8
    assert payload["signed_in"] is True
    assert isinstance(payload["feed"], list)


def test_watchline_rejects_bad_storyline_and_requires_csrf(client):
    create_verified_account(client, "watchline2@example.com")
    bad = post(
        client,
        "/v1/watchline/entries",
        {"kind": "arc", "key": "not-an-arc", "label": ""},
    )
    assert bad.status_code == 400
    missing = post(
        client,
        "/v1/watchline/entries",
        {"kind": "arc", "key": "abcdef1234567890", "label": ""},
    )
    assert missing.status_code in {404, 400}

    anonymous = client.post(
        "/v1/watchline/entries",
        json={"kind": "place", "key": "India", "label": "India"},
    )
    assert anonymous.status_code == 403

    public = client.get("/v1/watchline/public", params={"keys": ["place:India", "place:France"]})
    assert public.status_code == 200
    assert public.json()["public"] is True
    assert len(public.json()["entries"]) == 2


def test_event_citation_and_lens_endpoints(client, monkeypatch):
    from app.services.snapshot_service import snapshot_service

    fake = {
        "id": "evt-test",
        "title": "A test event.",
        "status": "breaking",
        "category": "conflict",
        "severity": "low",
        "first_reported": "2026-10-23T00:00:00+00:00",
        "last_updated": "2026-10-23T01:00:00+00:00",
        "summary": "A verified test event for the citation endpoint.",
        "sources": [
            {
                "outlet_name": "Test News",
                "url": "https://example.com/a",
                "alignment": "centre",
                "title": "A test event",
            }
        ],
        "countries": ["India"],
        "spectrum": {"left": 0, "centre": 1, "right": 0, "unrated": 0},
        "outlet_count": 1,
        "source_count": 1,
        "coverage": [],
        "timeline": [],
    }
    monkeypatch.setattr(
        snapshot_service, "get_detail", lambda event_id: fake if event_id == "evt-test" else None
    )
    citation = client.get("/v1/events/evt-test/citation")
    assert citation.status_code == 200, citation.text
    payload = citation.json()
    assert "/event/evt-test" in payload["url"]
    assert "A test event" in payload["apa"]
    assert payload["bibtex"].startswith("@misc{")

    for path in ("/v1/lenses/thin", "/v1/storylines", "/v1/pulse", "/v1/rewind"):
        response = client.get(path)
        assert response.status_code == 200, (path, response.text)


def test_watchline_feed_marks_updates_since_last_visit(monkeypatch):
    from app.services.snapshot_service import snapshot_service
    from app.services.watchline_service import WatchlineService

    snapshot = {
        "available": True,
        "ts": "2026-10-23T00:00:00+00:00",
        "events": [
            {
                "id": "evt-india",
                "t": "A test dispatch",
                "at": "2026-10-22T20:00:00+00:00",
                "imp": 0.8,
                "oc": 3,
                "cat": "conflict",
                "loc": "India",
            }
        ],
        "arcs": [],
    }
    details = {"evt-india": {"countries": ["India"], "revision": 1}}
    monkeypatch.setattr(snapshot_service, "get_snapshot", lambda window: snapshot)
    monkeypatch.setattr(snapshot_service, "get_details", lambda: details)

    service = WatchlineService()
    entries = [
        {"id": "w1", "kind": "place", "key": "india", "label": "India", "created_at": None}
    ]
    from datetime import datetime, timezone

    published = datetime(2026, 10, 22, 20, 0, tzinfo=timezone.utc).timestamp()
    seen_at = int(published - 3600)

    feed = service.build_feed(entries, "24h", seen_at=seen_at)
    assert feed["matched_total"] == 1
    assert feed["new_count"] == 1
    assert feed["feed"][0]["fresh"] is True

    quiet = service.build_feed(entries, "24h", seen_at=int(published + 3600))
    assert quiet["new_count"] == 0
    assert quiet["feed"][0]["fresh"] is False
