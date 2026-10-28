"""Account lifecycle, sessions and security settings for readers."""

from __future__ import annotations

import hmac
import logging
import re
import sqlite3
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from app.config import settings
from app.auth import email as email_service
from app.auth import google as google_service
from app.auth.database import DatabaseIntegrityError
from app.auth.errors import AuthError
from app.auth.security import (
    device_label,
    email_token_hash,
    generate_recovery_codes,
    generate_totp_secret,
    hash_password,
    hash_token,
    is_password_breached,
    iso_ts,
    mask_email,
    new_opaque_token,
    normalize_recovery_code,
    now_ts,
    otpauth_uri,
    password_errors,
    qr_data_uri,
    recovery_code_hash,
    sanitize_next_path,
    decrypt_secret,
    encrypt_secret,
    verify_password,
    verify_totp,
)
from app.auth.store import auth_store
from app.schemas.auth import TERMS_VERSION

logger = logging.getLogger("app.auth.service")

VERIFY_PURPOSE = "verify_email"
RESET_PURPOSE = "reset_password"
VERIFY_TTL_HOURS = 24
RESET_TTL_MINUTES = 30
TOTP_PENDING_TTL_SECONDS = 10 * 60
CHALLENGE_TTL_SECONDS = 5 * 60
CHALLENGE_MAX_ATTEMPTS = 5
RESEND_COOLDOWN_SECONDS = 60
# Google-only accounts must prove a recent sign-in before sensitive changes.
REAUTH_WINDOW_SECONDS = 10 * 60
GENERIC_LOGIN_ERROR = "Email or password is incorrect."
GENERIC_SIGNUP_MESSAGE = (
    "If this address can be used, we have sent a confirmation link."
)
GENERIC_RESET_MESSAGE = (
    "If an account exists for that address, a reset link is on its way."
)


@dataclass
class SessionContext:
    session_id: str
    token: str
    user: Any
    expires_at: int
    auth_method: str


@dataclass
class LoginResult:
    user: Optional[Dict[str, Any]]
    token: Optional[str]
    expires_at: Optional[int]
    two_factor_required: bool = False
    challenge_token: Optional[str] = None


@dataclass
class GoogleCallbackResult:
    user: Dict[str, Any]
    token: Optional[str]
    expires_at: Optional[int]
    next_path: str
    challenge_token: Optional[str] = None


def _normalise_email(value: str) -> str:
    return str(value or "").strip().lower()


def _display_name(value: str, email: str) -> str:
    cleaned = re.sub(r"[\x00-\x1f\x7f]", " ", value or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned:
        return cleaned[:80]
    local = email.split("@", 1)[0]
    words = [part for part in re.split(r"[._+\-]+", local) if part]
    derived = " ".join(word[:1].upper() + word[1:] for word in words)
    return (derived or "Reader")[:80]


def _dev_link(url: Optional[str], delivery: str) -> Optional[str]:
    if not url or settings.environment == "production":
        return None
    if delivery not in {"dev", "failed", "unconfigured"}:
        return None
    return url


def _assert_password_policy(password: str, email: str) -> None:
    problems = password_errors(password, email)
    if problems:
        raise AuthError(400, "weak_password", problems[0])
    if is_password_breached(password):
        raise AuthError(
            400,
            "breached_password",
            "That password appears in a known data breach. Choose a different one.",
        )


def _require_recent_session(
    session_started_at: Optional[int], action: str
) -> None:
    """Gate password creation/deletion for accounts with no local credential."""
    timestamp = now_ts()
    if (
        not session_started_at
        or timestamp - int(session_started_at) > REAUTH_WINDOW_SECONDS
    ):
        raise AuthError(
            403,
            "reauth_required",
            f"Sign in again with Google before {action}.",
        )


def serialize_user(row: Any) -> Dict[str, Any]:
    user_id = row["user_id"]
    google_linked = auth_store.get_identity_for_user(user_id, "google") is not None
    totp_enabled = bool(row["totp_enabled_at"])
    recovery_remaining = (
        auth_store.count_recovery_codes(user_id) if totp_enabled else 0
    )
    return {
        "id": user_id,
        "email": row["email"],
        "display_name": row["display_name"],
        "email_verified": bool(row["email_verified_at"]),
        "has_password": bool(row["password_hash"]),
        "totp_enabled": totp_enabled,
        "google_linked": google_linked,
        "recovery_codes_remaining": recovery_remaining,
        "created_at": iso_ts(int(row["user_created_at"])),
        "last_login_at": iso_ts(int(row["last_login_at"]) if row["last_login_at"] else None),
    }


def _session_duration(remember: bool) -> int:
    hours = (
        settings.auth_session_remember_ttl_hours
        if remember
        else settings.auth_session_ttl_hours
    )
    return max(1, int(hours)) * 3600


def _create_session(
    user_id: str,
    remember: bool,
    auth_method: str,
    ip: Optional[str],
    user_agent: Optional[str],
) -> Tuple[str, int]:
    token = new_opaque_token(48)
    timestamp = now_ts()
    absolute = timestamp + max(1, settings.auth_absolute_session_days) * 86400
    expires_at = min(timestamp + _session_duration(remember), absolute)
    auth_store.create_session(
        user_id=user_id,
        token_hash=hash_token(token),
        auth_method=auth_method,
        remember=remember,
        ip=ip,
        user_agent=user_agent,
        expires_at=expires_at,
        absolute_expires_at=absolute,
    )
    return token, expires_at


def _issue_verification(row: Any, enforce_cooldown: bool = False) -> Optional[str]:
    user_id = row["user_id"]
    last = auth_store.last_auth_token_at(user_id, VERIFY_PURPOSE)
    if enforce_cooldown and last and now_ts() - last < RESEND_COOLDOWN_SECONDS:
        raise AuthError(
            429,
            "resend_too_soon",
            "A confirmation email was sent recently. Wait a minute before trying again.",
        )
    token = new_opaque_token(32)
    auth_store.create_auth_token(
        user_id=user_id,
        purpose=VERIFY_PURPOSE,
        token_hash=email_token_hash(token),
        expires_at=now_ts() + VERIFY_TTL_HOURS * 3600,
    )
    url = email_service.verification_link(token)
    delivery = email_service.send_verification(
        row["email"], row["display_name"], token, VERIFY_TTL_HOURS
    )
    auth_store.record_event(
        user_id, "verification_sent", None, None, {"channel": "email", "delivery": delivery}
    )
    return _dev_link(url, delivery)


def get_session_context(token: Optional[str]) -> Optional[SessionContext]:
    if not token:
        return None
    row = auth_store.get_session(hash_token(token))
    if not row:
        return None
    timestamp = now_ts()
    if (
        row["revoked_at"]
        or int(row["expires_at"]) <= timestamp
        or int(row["absolute_expires_at"]) <= timestamp
    ):
        auth_store.revoke_session(row["session_id"], row["user_id"])
        return None
    if timestamp - int(row["last_seen_at"]) >= 300:
        remember = bool(row["remember"])
        expires_at = min(
            timestamp + _session_duration(remember),
            int(row["absolute_expires_at"]),
        )
        auth_store.touch_session(row["session_id"], timestamp, expires_at)
        row = auth_store.get_session(hash_token(token)) or row
    return SessionContext(
        session_id=row["session_id"],
        token=token,
        user=row,
        expires_at=int(row["expires_at"]),
        auth_method=row["auth_method"],
    )


def sign_up(
    *,
    email: str,
    password: str,
    display_name: str,
    accept_terms: bool,
    honeypot: str,
    ip: Optional[str],
    user_agent: Optional[str],
) -> Dict[str, Any]:
    if honeypot.strip():
        logger.warning("Signup honeypot triggered from %s", ip)
        raise AuthError(400, "signup_blocked", "Unable to create an account.")
    if not accept_terms:
        raise AuthError(400, "terms_required", "Accept the terms to continue.")
    address = _normalise_email(email)
    if len(address) > 254:
        raise AuthError(400, "invalid_email", "Enter a valid email address.")
    _assert_password_policy(password, address)
    password_hash = hash_password(password)

    existing = auth_store.get_user_by_email(address)
    if existing:
        dev_link = None
        if not existing["email_verified_at"]:
            dev_link = _issue_verification(existing)
        else:
            email_service.send_security_notice(
                existing["email"],
                existing["display_name"],
                "You already have an account",
                "Someone tried to create a Globe News Atlas account with this email. "
                "If it was you, sign in or reset your password. No new account was created.",
            )
            auth_store.record_event(
                existing["user_id"], "signup_duplicate", ip, user_agent
            )
        return {
            "status": "check_email",
            "message": GENERIC_SIGNUP_MESSAGE,
            "dev_verification_link": dev_link,
        }

    try:
        row = auth_store.create_user(
            email=address,
            display_name=_display_name(display_name, address),
            password_hash=password_hash,
            email_verified=False,
        )
    except (sqlite3.IntegrityError, DatabaseIntegrityError):
        return {
            "status": "check_email",
            "message": GENERIC_SIGNUP_MESSAGE,
            "dev_verification_link": None,
        }

    dev_link = _issue_verification(row)
    auth_store.record_event(
        row["user_id"], "signup", ip, user_agent, {"terms_version": TERMS_VERSION}
    )
    return {
        "status": "check_email",
        "message": GENERIC_SIGNUP_MESSAGE,
        "dev_verification_link": dev_link,
    }


def log_in(
    *,
    email: str,
    password: str,
    remember: bool,
    ip: Optional[str],
    user_agent: Optional[str],
) -> LoginResult:
    address = _normalise_email(email)
    row = auth_store.get_user_by_email(address)
    valid, needs_rehash = verify_password(password, row["password_hash"] if row else None)
    timestamp = now_ts()

    if not valid or row is None:
        if row is not None:
            if not row["locked_until"] or int(row["locked_until"]) <= timestamp:
                # Atomic increment: concurrent failures must all be counted.
                failed, _ = auth_store.increment_login_failure(
                    row["user_id"], settings.auth_lockout_attempts
                )
                auth_store.record_event(
                    row["user_id"],
                    "login_failed",
                    ip,
                    user_agent,
                    {"attempts": failed},
                )
        raise AuthError(401, "invalid_credentials", GENERIC_LOGIN_ERROR)

    if row["locked_until"] and int(row["locked_until"]) > timestamp:
        raise AuthError(
            429,
            "account_locked",
            "Too many attempts. Wait a few minutes before trying again.",
        )

    # Password sign-in is only allowed after the address is confirmed, so an
    # attacker who pre-registers a victim's email cannot hold the account.
    if not row["email_verified_at"]:
        raise AuthError(
            403,
            "email_not_verified",
            "Confirm your email address before signing in. "
            "Check your inbox for the confirmation link.",
        )

    if row["totp_enabled_at"]:
        challenge_token = new_opaque_token(32)
        auth_store.create_login_challenge(
            token_hash=hash_token(challenge_token),
            user_id=row["user_id"],
            remember=remember,
            ip=ip,
            user_agent=user_agent,
            expires_at=timestamp + CHALLENGE_TTL_SECONDS,
        )
        return LoginResult(
            user=None,
            token=None,
            expires_at=None,
            two_factor_required=True,
            challenge_token=challenge_token,
        )

    token, expires_at = _create_session(
        row["user_id"], remember, "password", ip, user_agent
    )
    auth_store.record_login_success(row["user_id"])
    if needs_rehash:
        auth_store.update_password(row["user_id"], hash_password(password))
    auth_store.record_event(
        row["user_id"], "login", ip, user_agent, {"method": "password", "remember": remember}
    )
    return LoginResult(
        user=serialize_user(auth_store.get_user_by_id(row["user_id"]) or row),
        token=token,
        expires_at=expires_at,
    )


def _verify_second_factor(
    row: Any, code: str
) -> Tuple[bool, int, Optional[str]]:
    encrypted = row["totp_secret_enc"]
    secret = decrypt_secret(encrypted) if encrypted else None
    if not secret:
        return False, 0, None
    cleaned = re.sub(r"\s", "", code or "")
    if re.fullmatch(r"\d{6}", cleaned):
        ok, step = verify_totp(secret, cleaned, row["totp_last_step"])
        return ok, step, None
    normalised = normalize_recovery_code(code)
    if len(normalised) < 8:
        return False, 0, None
    candidate = recovery_code_hash(normalised)
    for item in auth_store.list_recovery_codes(row["user_id"]):
        if item["used_at"]:
            continue
        if hmac.compare_digest(candidate, item["code_hash"]):
            return True, 0, item["id"]
    return False, 0, None


def complete_two_factor(
    *,
    challenge_token: str,
    code: str,
    remember: Optional[bool] = None,
    ip: Optional[str],
    user_agent: Optional[str],
) -> LoginResult:
    token_hash = hash_token(challenge_token)
    row = auth_store.get_login_challenge(token_hash)
    timestamp = now_ts()
    if not row or int(row["expires_at"]) <= timestamp:
        raise AuthError(400, "challenge_expired", "This sign-in attempt expired. Start again.")
    if int(row["attempts"]) >= CHALLENGE_MAX_ATTEMPTS:
        auth_store.delete_login_challenge(token_hash)
        raise AuthError(429, "too_many_codes", "Too many attempts. Sign in again.")

    ok, step, recovery_id = _verify_second_factor(row, code)
    if not ok:
        attempts = auth_store.increment_challenge_attempts(token_hash)
        if attempts >= CHALLENGE_MAX_ATTEMPTS:
            auth_store.delete_login_challenge(token_hash)
            raise AuthError(429, "too_many_codes", "Too many attempts. Sign in again.")
        raise AuthError(401, "invalid_code", "That code did not match. Try again.")

    # Each factor is single-use. Claim the TOTP step or recovery code first,
    # then consume the challenge; a concurrent duplicate loses one of these
    # atomic races and never receives a session.
    if recovery_id:
        if not auth_store.mark_recovery_code_used(recovery_id, row["user_id"]):
            raise AuthError(401, "invalid_code", "That code did not match. Try again.")
    elif step:
        if not auth_store.claim_totp_step(row["user_id"], step):
            raise AuthError(401, "invalid_code", "That code did not match. Try again.")
    if not auth_store.consume_login_challenge(token_hash):
        raise AuthError(
            400, "challenge_expired", "This sign-in attempt expired. Start again."
        )

    effective_remember = bool(row["remember"]) if remember is None else remember
    token, expires_at = _create_session(
        row["user_id"], effective_remember, "two_factor", ip, user_agent
    )
    auth_store.record_login_success(row["user_id"])
    auth_store.record_event(
        row["user_id"],
        "login",
        ip,
        user_agent,
        {
            "method": "recovery_code" if recovery_id else "totp",
            "remember": effective_remember,
        },
    )
    return LoginResult(
        user=serialize_user(auth_store.get_user_by_id(row["user_id"]) or row),
        token=token,
        expires_at=expires_at,
    )


def log_out(token: Optional[str], ip: Optional[str], user_agent: Optional[str]) -> None:
    if not token:
        return
    row = auth_store.get_session(hash_token(token))
    if row:
        auth_store.revoke_session(row["session_id"], row["user_id"])
        auth_store.record_event(row["user_id"], "logout", ip, user_agent)


def _deliver_password_reset(
    user_id: str,
    email: str,
    display_name: str,
    token: str,
    ip: Optional[str],
    user_agent: Optional[str],
) -> None:
    delivery = email_service.send_password_reset(
        email, display_name, token, RESET_TTL_MINUTES
    )
    auth_store.record_event(
        user_id,
        "password_reset_requested",
        ip,
        user_agent,
        {"delivery": delivery},
    )


def request_password_reset(email: str, ip: Optional[str], user_agent: Optional[str]) -> Dict[str, Any]:
    address = _normalise_email(email)
    row = auth_store.get_user_by_email(address)
    dev_link: Optional[str] = None
    if row:
        last = auth_store.last_auth_token_at(row["user_id"], RESET_PURPOSE)
        if not last or now_ts() - last >= RESEND_COOLDOWN_SECONDS:
            token = new_opaque_token(32)
            auth_store.create_auth_token(
                user_id=row["user_id"],
                purpose=RESET_PURPOSE,
                token_hash=email_token_hash(token),
                expires_at=now_ts() + RESET_TTL_MINUTES * 60,
            )
            if settings.email_delivery == "dev":
                # Dev logs the message synchronously so tests and local flows
                # can surface the link immediately.
                delivery = email_service.send_password_reset(
                    row["email"], row["display_name"], token, RESET_TTL_MINUTES
                )
                dev_link = _dev_link(email_service.reset_link(token), delivery)
                auth_store.record_event(
                    row["user_id"],
                    "password_reset_requested",
                    ip,
                    user_agent,
                    {"delivery": delivery},
                )
            else:
                # Real SMTP/API delivery is slow and can time out. Send it off
                # the request path so account existence is not timing-visible.
                threading.Thread(
                    target=_deliver_password_reset,
                    args=(
                        row["user_id"],
                        row["email"],
                        row["display_name"],
                        token,
                        ip,
                        user_agent,
                    ),
                    name="password-reset-email",
                    daemon=True,
                ).start()
    return {
        "status": "sent",
        "message": GENERIC_RESET_MESSAGE,
        "dev_reset_link": dev_link,
    }


def check_reset_token(token: str) -> Dict[str, Any]:
    row = auth_store.get_auth_token(email_token_hash(token), RESET_PURPOSE)
    if not row:
        return {"valid": False, "email_masked": None, "expired": False}
    expired = int(row["expires_at"]) <= now_ts()
    valid = bool(not row["used_at"] and not expired)
    return {
        "valid": valid,
        "email_masked": mask_email(row["email"]) if valid else None,
        "expired": expired,
    }


def reset_password(
    token: str, password: str, ip: Optional[str], user_agent: Optional[str]
) -> Dict[str, Any]:
    row = auth_store.get_auth_token(email_token_hash(token), RESET_PURPOSE)
    if not row or row["used_at"] or int(row["expires_at"]) <= now_ts():
        raise AuthError(
            400, "invalid_reset_token", "This reset link is invalid or has expired."
        )
    _assert_password_policy(password, row["email"])
    if not auth_store.consume_auth_token(row["id"], row["user_id"]):
        raise AuthError(400, "invalid_reset_token", "This reset link has already been used.")
    auth_store.update_password(row["user_id"], hash_password(password))
    auth_store.mark_email_verified(row["user_id"])
    auth_store.revoke_all_sessions(row["user_id"])
    auth_store.invalidate_auth_tokens(row["user_id"], [VERIFY_PURPOSE, RESET_PURPOSE])
    auth_store.record_event(row["user_id"], "password_reset", ip, user_agent)
    email_service.send_security_notice(
        row["email"],
        row["display_name"],
        "Your password was reset",
        "Your Globe News Atlas password was reset and all existing sessions were signed out.",
    )
    return {"status": "reset", "message": "Your password has been reset. Sign in to continue."}


def verify_email(
    token: str, ip: Optional[str], user_agent: Optional[str]
) -> Dict[str, Any]:
    row = auth_store.get_auth_token(email_token_hash(token), VERIFY_PURPOSE)
    if not row or int(row["expires_at"]) <= now_ts():
        raise AuthError(
            400, "invalid_verification", "This confirmation link is invalid or has expired."
        )
    if row["used_at"]:
        raise AuthError(400, "invalid_verification", "This confirmation link was already used.")
    if not auth_store.consume_auth_token(row["id"], row["user_id"]):
        raise AuthError(400, "invalid_verification", "This confirmation link was already used.")
    auth_store.mark_email_verified(row["user_id"])
    token_value, expires_at = _create_session(
        row["user_id"], False, "email_verification", ip, user_agent
    )
    auth_store.record_login_success(row["user_id"])
    auth_store.record_event(
        row["user_id"], "email_verified", ip, user_agent, {"method": "email_link"}
    )
    auth_store.record_event(
        row["user_id"], "login", ip, user_agent, {"method": "email_verification"}
    )
    fresh = auth_store.get_user_by_id(row["user_id"]) or row
    return {
        "user": serialize_user(fresh),
        "expires_at": iso_ts(expires_at),
        "expires_ts": expires_at,
        "token": token_value,
    }


def check_verification_token(token: str) -> Dict[str, Any]:
    row = auth_store.get_auth_token(email_token_hash(token), VERIFY_PURPOSE)
    if not row:
        return {"valid": False, "email_masked": None, "expired": False}
    expired = int(row["expires_at"]) <= now_ts()
    valid = bool(not row["used_at"] and not expired)
    return {
        "valid": valid,
        "email_masked": mask_email(row["email"]) if valid else None,
        "expired": expired,
    }


def resend_verification(user_id: str) -> Dict[str, Any]:
    row = auth_store.get_user_by_id(user_id)
    if not row:
        raise AuthError(401, "not_authenticated", "Sign in to continue.")
    if row["email_verified_at"]:
        raise AuthError(400, "already_verified", "This email is already confirmed.")
    dev_link = _issue_verification(row, enforce_cooldown=True)
    return {
        "status": "sent",
        "message": "A new confirmation link is on its way.",
        "dev_verification_link": dev_link,
    }


def change_password(
    *,
    user_id: str,
    session_id: str,
    current_password: str,
    new_password: str,
    code: str = "",
    ip: Optional[str],
    user_agent: Optional[str],
    session_started_at: Optional[int] = None,
) -> Dict[str, Any]:
    row = auth_store.get_user_by_id(user_id)
    if not row:
        raise AuthError(401, "not_authenticated", "Sign in to continue.")
    if row["password_hash"]:
        valid, _ = verify_password(current_password, row["password_hash"])
        if not valid:
            raise AuthError(400, "invalid_password", "Your current password is incorrect.")
        already_used, _ = verify_password(new_password, row["password_hash"])
        if already_used:
            raise AuthError(400, "same_password", "Choose a password you have not used here.")
    elif row["totp_enabled_at"]:
        ok, step, recovery_id = _verify_second_factor(row, code)
        if not ok:
            raise AuthError(
                400,
                "invalid_code",
                "Enter a current authenticator or recovery code to set a password.",
            )
        if recovery_id:
            if not auth_store.mark_recovery_code_used(recovery_id, user_id):
                raise AuthError(400, "invalid_code", "That code has already been used.")
        elif step and not auth_store.claim_totp_step(user_id, step):
            raise AuthError(400, "invalid_code", "That code has already been used.")
    else:
        # Google-only account: a recent sign-in is the only available proof.
        _require_recent_session(session_started_at, "setting a password")
    _assert_password_policy(new_password, row["email"])
    auth_store.update_password(user_id, hash_password(new_password))
    auth_store.revoke_all_sessions(user_id, except_session_id=session_id)
    auth_store.invalidate_auth_tokens(user_id, [VERIFY_PURPOSE, RESET_PURPOSE])
    auth_store.record_event(user_id, "password_changed", ip, user_agent)
    email_service.send_security_notice(
        row["email"],
        row["display_name"],
        "Your password was changed",
        "Your Globe News Atlas password was changed. Other sessions were signed out.",
    )
    fresh = auth_store.get_user_by_id(user_id) or row
    return {"user": serialize_user(fresh), "message": "Password updated."}


def update_profile(user_id: str, display_name: str, ip: Optional[str], user_agent: Optional[str]) -> Dict[str, Any]:
    row = auth_store.get_user_by_id(user_id)
    if not row:
        raise AuthError(401, "not_authenticated", "Sign in to continue.")
    name = _display_name(display_name, row["email"])
    auth_store.update_profile(user_id, name)
    auth_store.record_event(user_id, "profile_updated", ip, user_agent)
    fresh = auth_store.get_user_by_id(user_id) or row
    return {"user": serialize_user(fresh), "message": "Profile updated."}


def list_sessions(user_id: str, current_session_id: str) -> list[Dict[str, Any]]:
    rows = auth_store.list_sessions(user_id)
    timestamp = now_ts()
    sessions = []
    for row in rows:
        if int(row["expires_at"]) <= timestamp or int(row["absolute_expires_at"]) <= timestamp:
            continue
        sessions.append(
            {
                "id": row["id"],
                "current": row["id"] == current_session_id,
                "device": device_label(row["user_agent"]),
                "ip": row["ip"],
                "auth_method": row["auth_method"],
                "remember": bool(row["remember"]),
                "created_at": iso_ts(int(row["created_at"])),
                "last_seen_at": iso_ts(int(row["last_seen_at"])),
                "expires_at": iso_ts(int(row["expires_at"])),
            }
        )
    return sessions


def revoke_session(
    user_id: str, session_id: str, current_session_id: str, ip: str | None, user_agent: str | None
) -> Dict[str, Any]:
    if session_id == current_session_id:
        raise AuthError(
            400, "current_session", "Use sign out to end the session you are using now."
        )
    if not auth_store.revoke_session(session_id, user_id):
        raise AuthError(404, "session_not_found", "That session is no longer active.")
    auth_store.record_event(user_id, "session_revoked", ip, user_agent)
    return {"status": "revoked", "message": "Session signed out."}


def revoke_other_sessions(
    user_id: str, current_session_id: str, ip: Optional[str], user_agent: Optional[str]
) -> Dict[str, Any]:
    count = auth_store.revoke_all_sessions(user_id, except_session_id=current_session_id)
    auth_store.record_event(user_id, "sessions_revoked", ip, user_agent, {"count": count})
    return {
        "status": "revoked",
        "message": f"Signed out {count} other session{'s' if count != 1 else ''}.",
    }


def list_events(user_id: str) -> list[Dict[str, Any]]:
    import json

    events = []
    for row in auth_store.list_events(user_id, limit=20):
        try:
            metadata = json.loads(row["metadata"] or "{}")
        except ValueError:
            metadata = {}
        events.append(
            {
                "event": row["event"],
                "ip": row["ip"],
                "created_at": iso_ts(int(row["created_at"])),
                "metadata": metadata,
            }
        )
    return events


def setup_two_factor(
    *,
    user_id: str,
    password: str,
    ip: Optional[str],
    user_agent: Optional[str],
) -> Dict[str, Any]:
    row = auth_store.get_user_by_id(user_id)
    if not row:
        raise AuthError(401, "not_authenticated", "Sign in to continue.")
    if row["totp_enabled_at"]:
        raise AuthError(400, "totp_enabled", "Two-factor authentication is already on.")
    if row["password_hash"]:
        valid, _ = verify_password(password, row["password_hash"])
        if not valid:
            raise AuthError(400, "invalid_password", "Your password is incorrect.")
    secret = generate_totp_secret()
    auth_store.set_totp_pending(user_id, encrypt_secret(secret))
    uri = otpauth_uri(secret, row["email"])
    auth_store.record_event(user_id, "totp_setup_started", ip, user_agent)
    return {
        "secret": secret,
        "otpauth_uri": uri,
        "qr_data_uri": qr_data_uri(uri),
        "expires_in": TOTP_PENDING_TTL_SECONDS,
    }


def enable_two_factor(
    *,
    user_id: str,
    code: str,
    ip: Optional[str],
    user_agent: Optional[str],
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    row = auth_store.get_user_by_id(user_id)
    if not row:
        raise AuthError(401, "not_authenticated", "Sign in to continue.")
    if row["totp_enabled_at"]:
        raise AuthError(400, "totp_enabled", "Two-factor authentication is already on.")
    pending = auth_store.get_totp_pending(user_id)
    if not pending:
        raise AuthError(400, "totp_not_started", "Start the setup again.")
    encrypted, created_at = pending
    if now_ts() - created_at > TOTP_PENDING_TTL_SECONDS:
        raise AuthError(400, "totp_expired", "The setup expired. Start again.")
    secret = decrypt_secret(encrypted)
    if not secret:
        raise AuthError(400, "totp_failed", "Could not read the setup secret. Start again.")
    ok, step = verify_totp(secret, code, None)
    if not ok:
        raise AuthError(400, "invalid_code", "That code did not match. Check your authenticator.")
    auth_store.enable_totp(user_id)
    auth_store.claim_totp_step(user_id, step)
    codes, hashes = generate_recovery_codes()
    auth_store.replace_recovery_codes(user_id, hashes)
    # Enabling a second factor is a credential change: sign out other devices
    # but keep the session that performed the change.
    auth_store.revoke_all_sessions(user_id, except_session_id=session_id)
    auth_store.record_event(user_id, "totp_enabled", ip, user_agent)
    email_service.send_security_notice(
        row["email"],
        row["display_name"],
        "Two-factor authentication is on",
        "An authenticator app now protects your account. Keep your recovery codes somewhere safe.",
    )
    fresh = auth_store.get_user_by_id(user_id) or row
    return {"user": serialize_user(fresh), "recovery_codes": codes}


def disable_two_factor(
    *,
    user_id: str,
    password: str,
    code: str,
    ip: Optional[str],
    user_agent: Optional[str],
) -> Dict[str, Any]:
    row = auth_store.get_user_by_id(user_id)
    if not row:
        raise AuthError(401, "not_authenticated", "Sign in to continue.")
    if not row["totp_enabled_at"]:
        raise AuthError(400, "totp_disabled", "Two-factor authentication is not on.")
    if row["password_hash"]:
        valid, _ = verify_password(password, row["password_hash"])
        if not valid:
            raise AuthError(400, "invalid_password", "Your password is incorrect.")
    ok, step, recovery_id = _verify_second_factor(row, code)
    if not ok:
        raise AuthError(400, "invalid_code", "Enter a current authenticator or recovery code.")
    if recovery_id and not auth_store.mark_recovery_code_used(recovery_id, user_id):
        raise AuthError(400, "invalid_code", "That code has already been used.")
    if step:
        auth_store.claim_totp_step(user_id, step)
    auth_store.disable_totp(user_id)
    auth_store.record_event(user_id, "totp_disabled", ip, user_agent)
    email_service.send_security_notice(
        row["email"],
        row["display_name"],
        "Two-factor authentication is off",
        "The authenticator app was removed from your account. If this was not you, secure the account now.",
    )
    fresh = auth_store.get_user_by_id(user_id) or row
    return {"user": serialize_user(fresh), "message": "Two-factor authentication turned off."}


def regenerate_recovery_codes(
    *,
    user_id: str,
    password: str,
    code: str,
    ip: Optional[str],
    user_agent: Optional[str],
) -> Dict[str, Any]:
    row = auth_store.get_user_by_id(user_id)
    if not row:
        raise AuthError(401, "not_authenticated", "Sign in to continue.")
    if not row["totp_enabled_at"]:
        raise AuthError(400, "totp_disabled", "Two-factor authentication is not on.")
    if row["password_hash"]:
        valid, _ = verify_password(password, row["password_hash"])
        if not valid:
            raise AuthError(400, "invalid_password", "Your password is incorrect.")
    ok, step, recovery_id = _verify_second_factor(row, code)
    if not ok:
        raise AuthError(400, "invalid_code", "Enter a current authenticator or recovery code.")
    if recovery_id and not auth_store.mark_recovery_code_used(recovery_id, user_id):
        raise AuthError(400, "invalid_code", "That code has already been used.")
    if step:
        auth_store.claim_totp_step(user_id, step)
    codes, hashes = generate_recovery_codes()
    auth_store.replace_recovery_codes(user_id, hashes)
    auth_store.record_event(user_id, "recovery_codes_regenerated", ip, user_agent)
    return {"recovery_codes": codes}


def delete_account(
    *,
    user_id: str,
    password: str,
    confirm_email: str,
    code: str = "",
    ip: Optional[str],
    user_agent: Optional[str],
    session_started_at: Optional[int] = None,
) -> Dict[str, Any]:
    row = auth_store.get_user_by_id(user_id)
    if not row:
        raise AuthError(401, "not_authenticated", "Sign in to continue.")
    if _normalise_email(confirm_email) != row["email"]:
        raise AuthError(400, "email_mismatch", "Type the email address for this account.")
    if row["password_hash"]:
        valid, _ = verify_password(password, row["password_hash"])
        if not valid:
            raise AuthError(400, "invalid_password", "Your password is incorrect.")
    elif row["totp_enabled_at"]:
        ok, step, recovery_id = _verify_second_factor(row, code)
        if not ok:
            raise AuthError(
                400,
                "invalid_code",
                "Enter a current authenticator or recovery code to close the account.",
            )
        if recovery_id and not auth_store.mark_recovery_code_used(recovery_id, user_id):
            raise AuthError(400, "invalid_code", "That code has already been used.")
        if step:
            auth_store.claim_totp_step(user_id, step)
    else:
        # Google-only account: require a sign-in from the last ten minutes.
        _require_recent_session(session_started_at, "closing the account")
    auth_store.record_event(user_id, "account_deleted", ip, user_agent)
    auth_store.delete_user(user_id)
    email_service.send_security_notice(
        row["email"],
        row["display_name"],
        "Your account was deleted",
        "The reader account for this address was closed and its sessions were revoked.",
    )
    return {"status": "deleted", "message": "Your account has been closed."}


# ── Google OIDC ──────────────────────────────────────────────────────

def build_google_start(
    *,
    next_path: Optional[str],
    link_user_id: Optional[str],
    callback_url: str,
) -> Dict[str, Any]:
    if not google_service.configured():
        raise AuthError(503, "google_not_configured", "Google sign-in is not configured.")
    state = google_service.new_state()
    nonce = google_service.new_nonce()
    verifier = google_service.new_code_verifier()
    safe_next = sanitize_next_path(next_path, "/account")
    auth_store.create_oauth_state(
        state_hash=hash_token(state),
        code_verifier=verifier,
        nonce=nonce,
        next_path=safe_next,
        expires_at=now_ts() + 10 * 60,
        link_user_id=link_user_id,
    )
    return {
        "url": google_service.authorization_url(state, nonce, verifier, callback_url),
        "state": state,
        "expires_in": 600,
    }


def complete_google(
    *,
    state: str,
    code: str,
    callback_url: str,
    ip: Optional[str],
    user_agent: Optional[str],
) -> GoogleCallbackResult:
    state_hash = hash_token(state)
    record = auth_store.get_oauth_state(state_hash)
    timestamp = now_ts()
    if (
        not record
        or record["used_at"]
        or int(record["expires_at"]) <= timestamp
    ):
        raise AuthError(400, "google_state", "This Google sign-in link is invalid or expired.")
    if not auth_store.consume_oauth_state(state_hash):
        raise AuthError(400, "google_state", "This Google sign-in link was already used.")

    id_token = google_service.exchange_code(code, record["code_verifier"], callback_url)
    profile = google_service.verify_id_token(id_token, record["nonce"])
    next_path = sanitize_next_path(record["next_path"], "/account")
    link_user_id = record["link_user_id"]

    if link_user_id:
        row = auth_store.get_user_by_id(link_user_id)
        if not row:
            raise AuthError(401, "not_authenticated", "Sign in again before connecting Google.")
        if _normalise_email(row["email"]) != profile.email:
            raise AuthError(
                400,
                "google_email_mismatch",
                "Use the Google account with the same email as this reader account.",
            )
        existing = auth_store.get_identity("google", profile.subject)
        if existing and existing["user_id"] != row["user_id"]:
            raise AuthError(
                400, "google_already_linked", "That Google account is linked to another reader."
            )
        auth_store.link_identity("google", profile.subject, row["user_id"], profile.email)
        auth_store.mark_email_verified(row["user_id"])
        token, expires_at = _create_session(
            row["user_id"], True, "google", ip, user_agent
        )
        auth_store.record_login_success(row["user_id"])
        auth_store.record_event(
            row["user_id"], "google_linked", ip, user_agent, {"method": "google"}
        )
        fresh = auth_store.get_user_by_id(row["user_id"]) or row
        return GoogleCallbackResult(
            user=serialize_user(fresh),
            token=token,
            expires_at=expires_at,
            next_path=next_path,
        )

    identity = auth_store.get_identity("google", profile.subject)
    if identity:
        row = auth_store.get_user_by_id(identity["user_id"])
        if not row:
            raise AuthError(400, "google_account_missing", "That reader account no longer exists.")
    else:
        row = auth_store.get_user_by_email(profile.email)
        if row:
            already = auth_store.get_identity_for_user(row["user_id"], "google")
            if already and already["subject"] != profile.subject:
                raise AuthError(
                    400,
                    "google_already_linked",
                    "This reader account uses a different Google sign-in.",
                )
            if not row["email_verified_at"]:
                # Never auto-link into an unverified password registration:
                # whoever created it may not own the mailbox.
                auth_store.record_event(
                    row["user_id"],
                    "google_link_blocked_unverified",
                    ip,
                    user_agent,
                    {"method": "signin"},
                )
                raise AuthError(
                    403,
                    "google_account_unverified",
                    "This email already has an account that is not verified. "
                    "Verify it or reset the password before using Google sign-in.",
                )
            auth_store.link_identity(
                "google", profile.subject, row["user_id"], profile.email
            )
            auth_store.record_event(
                row["user_id"], "google_linked", ip, user_agent, {"method": "signin"}
            )
        else:
            try:
                row = auth_store.create_user(
                    email=profile.email,
                    display_name=_display_name(profile.name, profile.email),
                    password_hash=None,
                    email_verified=True,
                )
            except (sqlite3.IntegrityError, DatabaseIntegrityError):
                # Lost a race with another signup for this address. Never
                # attach Google to an unverified registration.
                row = auth_store.get_user_by_email(profile.email)
                if not row:
                    raise AuthError(400, "google_signup_failed", "Could not create the account.")
                if not row["email_verified_at"]:
                    auth_store.record_event(
                        row["user_id"],
                        "google_link_blocked_unverified",
                        ip,
                        user_agent,
                        {"method": "signin"},
                    )
                    raise AuthError(
                        403,
                        "google_account_unverified",
                        "This email already has an account that is not verified. "
                        "Verify it or reset the password before using Google sign-in.",
                    )
            auth_store.link_identity(
                "google", profile.subject, row["user_id"], profile.email
            )
            auth_store.record_event(
                row["user_id"],
                "signup_google",
                ip,
                user_agent,
                {"method": "google", "terms_version": TERMS_VERSION},
            )

    if row["totp_enabled_at"]:
        challenge_token = new_opaque_token(32)
        auth_store.create_login_challenge(
            token_hash=hash_token(challenge_token),
            user_id=row["user_id"],
            remember=True,
            ip=ip,
            user_agent=user_agent,
            expires_at=timestamp + CHALLENGE_TTL_SECONDS,
        )
        return GoogleCallbackResult(
            user=serialize_user(row),
            token=None,
            expires_at=None,
            next_path=next_path,
            challenge_token=challenge_token,
        )

    token, expires_at = _create_session(
        row["user_id"], True, "google", ip, user_agent
    )
    auth_store.record_login_success(row["user_id"])
    auth_store.record_event(
        row["user_id"], "login", ip, user_agent, {"method": "google"}
    )
    fresh = auth_store.get_user_by_id(row["user_id"]) or row
    return GoogleCallbackResult(
        user=serialize_user(fresh),
        token=token,
        expires_at=expires_at,
        next_path=next_path,
    )


def unlink_google(
    *,
    user_id: str,
    password: str,
    ip: Optional[str],
    user_agent: Optional[str],
) -> Dict[str, Any]:
    row = auth_store.get_user_by_id(user_id)
    if not row:
        raise AuthError(401, "not_authenticated", "Sign in to continue.")
    if not auth_store.get_identity_for_user(user_id, "google"):
        raise AuthError(400, "google_not_linked", "Google is not connected to this account.")
    if not row["password_hash"]:
        raise AuthError(
            400,
            "password_required",
            "Set a password before disconnecting Google, so you can still sign in.",
        )
    valid, _ = verify_password(password, row["password_hash"])
    if not valid:
        raise AuthError(400, "invalid_password", "Your password is incorrect.")
    auth_store.unlink_identity("google", user_id)
    auth_store.record_event(user_id, "google_unlinked", ip, user_agent)
    email_service.send_security_notice(
        row["email"],
        row["display_name"],
        "Google was disconnected",
        "Google sign-in was removed from your account. Your password still works.",
    )
    fresh = auth_store.get_user_by_id(user_id) or row
    return {"user": serialize_user(fresh), "message": "Google sign-in disconnected."}


def config_dict() -> Dict[str, Any]:
    return {
        "google_enabled": google_service.configured(),
        "email_delivery": settings.email_delivery,
        "environment": settings.environment,
        "password_min_length": max(8, int(settings.auth_min_password_length)),
        "terms_version": TERMS_VERSION,
    }
