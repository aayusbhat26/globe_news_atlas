"""Proxy trust, CORS, host, docs, CSP and production config regressions."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request

from app.client_ip import get_client_ip, rate_limit_key
from app.config import Settings, settings
from app.main import app, hf_refresh_enabled
from app.middleware.rate_limit import limiter


def make_request(client=("203.0.113.9", 50000), headers: dict | None = None) -> Request:
    raw_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": raw_headers,
            "client": client,
        }
    )


def test_spoofed_x_forwarded_for_cannot_change_rate_limit_key(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", False)
    monkeypatch.delenv("RENDER", raising=False)

    first = make_request(headers={"x-forwarded-for": "198.51.100.1"})
    second = make_request(headers={"x-forwarded-for": "198.51.100.2"})

    assert get_client_ip(first) == "203.0.113.9"
    assert rate_limit_key(first) == rate_limit_key(second) == "203.0.113.9"
    assert limiter._key_func(first) == limiter._key_func(second)


def test_cf_header_is_ignored_without_proxy_trust(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", False)
    monkeypatch.delenv("RENDER", raising=False)
    request = make_request(
        client=("203.0.113.9", 50000),
        headers={"cf-connecting-ip": "198.51.100.77"},
    )
    assert get_client_ip(request) == "203.0.113.9"


def test_trusted_cf_header_is_used_instead_of_socket_peer(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    request = make_request(
        client=("10.0.0.5", 1234),
        headers={
            "cf-connecting-ip": "198.51.100.77",
            "x-forwarded-for": "203.0.113.200",
        },
    )
    assert get_client_ip(request) == "198.51.100.77"
    assert rate_limit_key(request) == "198.51.100.77"


def test_render_environment_enables_trust_without_setting(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", False)
    monkeypatch.setenv("RENDER", "true")
    request = make_request(
        client=("10.0.0.5", 1234),
        headers={"cf-connecting-ip": "198.51.100.88"},
    )
    assert get_client_ip(request) == "198.51.100.88"


def test_invalid_cf_header_falls_back_to_socket_peer(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    request = make_request(
        client=("10.0.0.5", 1234),
        headers={"cf-connecting-ip": "not-an-ip"},
    )
    assert get_client_ip(request) == "10.0.0.5"


def test_unknown_cors_origin_gets_no_allow_origin_header():
    client = TestClient(app)
    response = client.get(
        "/v1/snapshot?window=24h",
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_docs_and_openapi_are_available_in_development():
    client = TestClient(app)
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_docs_and_openapi_are_hidden_in_production(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    client = TestClient(app)
    for path in ("/docs", "/redoc", "/openapi.json"):
        response = client.get(path)
        assert response.status_code == 404, path
        assert response.headers["content-type"].startswith("application/json")


def test_spa_csp_and_embed_frame_ancestors():
    client = TestClient(app)
    index = client.get("/")
    if not index.headers.get("content-type", "").startswith("text/html"):
        pytest.skip("Frontend build is not present")
    csp = index.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "style-src 'self' 'unsafe-inline'" in csp
    assert "font-src 'self'" in csp
    assert "img-src 'self' data: https:" in csp
    assert "connect-src 'self'" in csp
    assert "frame-ancestors 'self'" in csp
    assert index.headers["x-frame-options"] == "SAMEORIGIN"

    embed = client.get("/embed/event/missing")
    assert embed.headers["content-security-policy"] == "frame-ancestors *"


def test_untrusted_host_header_is_rejected():
    client = TestClient(app)
    good = client.get("/health")
    assert good.status_code == 200
    bad = client.get("/health", headers={"Host": "evil.example"})
    assert bad.status_code == 400


def test_unknown_v1_path_returns_json_404():
    client = TestClient(app)
    response = client.get("/v1/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "Not Found"}

    post_response = client.post("/v1/does-not-exist", json={})
    assert post_response.status_code == 404
    assert post_response.headers["content-type"].startswith("application/json")

    bare = client.get("/v1")
    assert bare.status_code == 404
    assert bare.headers["content-type"].startswith("application/json")


def test_hf_refresh_runs_for_public_buckets_without_token(monkeypatch):
    monkeypatch.setattr(settings, "hf_token", None)
    monkeypatch.setattr(settings, "hf_repo", "owner/public-bucket")
    monkeypatch.setattr(settings, "hf_pull_serving", True)
    assert hf_refresh_enabled() is True

    monkeypatch.setattr(settings, "hf_pull_serving", False)
    assert hf_refresh_enabled() is False
    monkeypatch.setattr(settings, "hf_pull_serving", True)
    monkeypatch.setattr(settings, "hf_repo", None)
    assert hf_refresh_enabled() is False


def _production_settings(**overrides) -> dict:
    values = {
        "_env_file": None,
        "environment": "production",
        "auth_db_backend": "sqlite",
        "auth_secret": "x" * 40,
        "app_base_url": "https://app.example.com",
        "public_base_url": "https://api.example.com",
    }
    values.update(overrides)
    return values


def test_production_settings_require_secret_and_public_urls():
    with pytest.raises(ValidationError) as error:
        Settings(
            **_production_settings(
                auth_secret="too-short",
                app_base_url="",
                public_base_url="",
            )
        )
    message = str(error.value)
    assert "AUTH_SECRET" in message
    assert "APP_BASE_URL" in message
    assert "PUBLIC_BASE_URL" in message

    valid = Settings(**_production_settings())
    assert valid.is_production is True


def test_mysql_production_settings_require_connection_fields():
    with pytest.raises(ValidationError) as error:
        Settings(
            **_production_settings(
                auth_db_backend="mysql",
                auth_db_host=None,
                auth_db_name=None,
                auth_db_user=None,
                auth_db_password=None,
            )
        )
    message = str(error.value)
    assert "AUTH_DB_HOST" in message
    assert "AUTH_DB_NAME" in message
    assert "AUTH_DB_USER" in message
    assert "AUTH_DB_PASSWORD" in message

    configured = Settings(
        **_production_settings(
            auth_db_backend="mysql",
            auth_db_host="db.example.com",
            auth_db_name="atlas",
            auth_db_user="reader",
            auth_db_password="db-password",
        )
    )
    assert configured.auth_db_backend == "mysql"


def test_development_settings_do_not_require_production_secrets():
    local = Settings(
        _env_file=None,
        environment="development",
        auth_db_backend="sqlite",
        auth_secret=None,
        app_base_url=None,
        public_base_url=None,
    )
    assert local.is_production is False


def test_comma_separated_and_json_list_settings_are_accepted():
    comma = Settings(_env_file=None, allowed_hosts="a.example, b.example")
    assert comma.allowed_hosts == ["a.example", "b.example"]

    encoded = Settings(_env_file=None, allowed_origins='["https://one.example"]')
    assert encoded.allowed_origins == ["https://one.example"]
