"""Google OpenID Connect web-server flow with PKCE, state and nonce checks."""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode

import httpx
import jwt

from app.config import settings

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")
SCOPES = "openid email profile"

_jwk_client = jwt.PyJWKClient(
    JWKS_URI,
    cache_keys=True,
    cache_jwk_set=True,
    lifespan=3600,
    timeout=settings.google_oauth_timeout_seconds,
)


class GoogleAuthError(Exception):
    def __init__(self, code: str, message: str = "Google sign-in failed.") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class GoogleProfile:
    subject: str
    email: str
    email_verified: bool
    name: str
    picture: Optional[str]


def configured() -> bool:
    return settings.google_login_enabled


def redirect_uri(request_base_url: str) -> str:
    if settings.google_redirect_uri:
        return settings.google_redirect_uri
    base = (settings.public_base_url or request_base_url).rstrip("/")
    return f"{base}/v1/auth/google/callback"


def new_state() -> str:
    return secrets.token_urlsafe(32)


def new_nonce() -> str:
    return secrets.token_urlsafe(24)


def new_code_verifier() -> str:
    return secrets.token_urlsafe(64)[:96]


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorization_url(
    state: str, nonce: str, verifier: str, callback_url: str
) -> str:
    query = urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": callback_url,
            "response_type": "code",
            "scope": SCOPES,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge(verifier),
            "code_challenge_method": "S256",
            "access_type": "online",
            "prompt": "select_account",
        }
    )
    return f"{AUTHORIZATION_ENDPOINT}?{query}"


def exchange_code(code: str, verifier: str, callback_url: str) -> str:
    try:
        response = httpx.post(
            TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": callback_url,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
            headers={"Accept": "application/json", "User-Agent": "GlobeNewsAtlas/1.0"},
            timeout=settings.google_oauth_timeout_seconds,
        )
    except httpx.HTTPError as exc:
        raise GoogleAuthError("google_unreachable", "Could not reach Google.") from exc
    if response.status_code >= 400:
        raise GoogleAuthError("google_exchange_failed", "Google rejected the sign-in.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise GoogleAuthError("google_exchange_failed", "Google returned an invalid response.") from exc
    id_token = payload.get("id_token")
    if not isinstance(id_token, str) or not id_token:
        raise GoogleAuthError("google_no_id_token", "Google did not return an identity token.")
    return id_token


def verify_id_token(id_token: str, nonce: str) -> GoogleProfile:
    try:
        signing_key = _jwk_client.get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.google_client_id,
            issuer=list(ISSUERS),
            options={"require": ["exp", "iat", "aud", "iss", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise GoogleAuthError("google_invalid_token", "Google's identity token was invalid.") from exc
    except Exception as exc:
        raise GoogleAuthError("google_jwks_failed", "Could not verify Google's signing key.") from exc

    if not claims.get("nonce") or not secrets.compare_digest(
        str(claims.get("nonce")), nonce
    ):
        raise GoogleAuthError("google_nonce_mismatch", "Google's response did not match this sign-in.")
    if claims.get("email_verified") is not True:
        raise GoogleAuthError("google_email_unverified", "Google has not verified this email address.")
    email = str(claims.get("email") or "").strip().lower()
    subject = str(claims.get("sub") or "").strip()
    if not email or not subject:
        raise GoogleAuthError("google_incomplete_profile", "Google did not return an email address.")
    return GoogleProfile(
        subject=subject,
        email=email,
        email_verified=True,
        name=str(claims.get("name") or email.split("@", 1)[0]).strip()[:80],
        picture=(str(claims["picture"]) if claims.get("picture") else None),
    )
