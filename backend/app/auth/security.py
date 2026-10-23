"""Password, session, CSRF, OTP and secret handling for reader accounts."""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import logging
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Iterable, Optional, Tuple
from urllib.parse import quote

import httpx
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger("app.auth.security")

SESSION_COOKIE = "gna_session"
CSRF_COOKIE = "gna_csrf"
OAUTH_STATE_COOKIE = "gna_oauth_state"

TOTP_ISSUER = "Globe News Atlas"
TOTP_DIGITS = 6
TOTP_PERIOD = 30
TOTP_WINDOW = 1
RECOVERY_CODE_COUNT = 10

_MIN_PASSWORD_FALLBACK = 12
_MAX_PASSWORD = 128

_COMMON_PASSWORDS = {
    "123456789012", "password1234", "password12345", "qwertyuiop12", "qwerty123456",
    "letmein12345", "welcome12345", "admin123456", "iloveyou1234", "monkey123456",
    "dragon123456", "sunshine1234", "princess1234", "football1234", "baseball1234",
    "abc123456789", "password123!", "qwerty123456!", "1q2w3e4r5t6y", "1234567890ab",
    "trustno1234", "changeme1234", "secret123456", "starwars1234", "whatever1234",
    "superman1234", "batman123456", "shadow123456", "master123456", "michael123456",
    "jennifer1234", "jordan123456", "harley123456", "ranger123456", "buster123456",
    "soccer123456", "hockey123456", "killer123456", "george123456", "computer1234",
    "internet1234", "service12345", "freedom12345", "passw0rd1234", "p@ssw0rd1234",
    "correcthorsebatterystaple", "thisisapassword", "iloveyou123!", "globenews123",
}

_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)

_dummy_hash: Optional[str] = None
_dummy_lock = threading.Lock()
_secret_lock = threading.Lock()
_secret_cache: dict[str, bytes] = {}


def now_ts() -> int:
    return int(time.time())


def iso_ts(value: Optional[int]) -> Optional[str]:
    if value is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(value))


def new_opaque_token(bytes_length: int = 32) -> str:
    return secrets.token_urlsafe(bytes_length)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


# ── server secret ────────────────────────────────────────────────────

def _secret_path() -> Path:
    return Path(settings.data_dir) / "auth" / "secret.key"


def get_auth_secret() -> bytes:
    configured = (settings.auth_secret or "").strip()
    if configured:
        return configured.encode("utf-8")

    path = _secret_path()
    key = str(path.resolve())
    with _secret_lock:
        if key in _secret_cache:
            return _secret_cache[key]
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            value = path.read_text(encoding="utf-8").strip().encode("utf-8")
        else:
            value = secrets.token_urlsafe(48).encode("utf-8")
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            try:
                fd = os.open(path, flags, 0o600)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(value)
            except FileExistsError:
                value = path.read_text(encoding="utf-8").strip().encode("utf-8")
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            logger.info("Created a local auth secret at %s", path)
        _secret_cache[key] = value
        return value


def _fernet() -> Fernet:
    key = hashlib.sha256(get_auth_secret() + b":totp-v1").digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> Optional[str]:
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError):
        logger.warning("Could not decrypt a stored TOTP secret")
        return None


# ── passwords ────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return _hasher.hash(password)


def _dummy_password_hash() -> str:
    global _dummy_hash
    if _dummy_hash is None:
        with _dummy_lock:
            if _dummy_hash is None:
                _dummy_hash = _hasher.hash(new_opaque_token(24))
    return _dummy_hash


def verify_password(password: str, stored_hash: Optional[str]) -> Tuple[bool, bool]:
    """Return (valid, needs_rehash); always runs a hash for missing accounts."""
    candidate = stored_hash or _dummy_password_hash()
    try:
        _hasher.verify(candidate, password)
        valid = stored_hash is not None
        needs_rehash = bool(valid and _hasher.check_needs_rehash(candidate))
        return valid, needs_rehash
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False, False


def password_errors(password: str, email: str = "") -> list[str]:
    minimum = max(8, int(settings.auth_min_password_length or _MIN_PASSWORD_FALLBACK))
    errors: list[str] = []
    if len(password) < minimum:
        errors.append(f"Use at least {minimum} characters.")
    if len(password) > _MAX_PASSWORD:
        errors.append(f"Use no more than {_MAX_PASSWORD} characters.")
    if not password.strip():
        errors.append("Enter a password.")
        return errors
    lowered = password.lower()
    if lowered in _COMMON_PASSWORDS:
        errors.append("This password is too common. Choose something less predictable.")
    if len(set(password)) <= 2 and len(password) >= 8:
        errors.append("This password repeats too few characters.")
    local_part = (email.split("@", 1)[0] or "").strip().lower()
    if len(local_part) >= 4 and local_part in lowered:
        errors.append("Do not include your email address in the password.")
    if lowered in {"1234567890123", "qwertyuiopasd", "asdfghjkl1234"}:
        errors.append("This password is too easy to guess.")
    return errors


def is_password_breached(password: str) -> bool:
    if not settings.auth_check_breached_passwords:
        return False
    digest = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]
    try:
        response = httpx.get(
            f"https://api.pwnedpasswords.com/range/{prefix}",
            headers={
                "Add-Padding": "true",
                "User-Agent": "GlobeNewsAtlas/1.0 password-safety-check",
            },
            timeout=4.0,
        )
        if response.status_code != 200:
            return False
        for line in response.text.splitlines():
            candidate, _, count = line.partition(":")
            if candidate.strip().upper() == suffix:
                try:
                    return int(count.strip()) > 0
                except ValueError:
                    return True
    except (httpx.HTTPError, OSError):
        logger.info("Breached-password check unavailable; continuing without it")
    return False


# ── CSRF ─────────────────────────────────────────────────────────────

def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def issue_csrf_token(ttl_seconds: int = 60 * 60 * 24 * 30) -> str:
    payload = json.dumps(
        {"exp": now_ts() + ttl_seconds, "nonce": new_opaque_token(16)},
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = _b64encode(payload)
    signature = hmac.new(
        get_auth_secret(), encoded.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{encoded}.{_b64encode(signature)}"


def csrf_token_valid(token: Optional[str]) -> bool:
    if not token or "." not in token:
        return False
    encoded, signature = token.rsplit(".", 1)
    expected = hmac.new(
        get_auth_secret(), encoded.encode("ascii"), hashlib.sha256
    ).digest()
    try:
        if not hmac.compare_digest(_b64decode(signature), expected):
            return False
        payload = json.loads(_b64decode(encoded))
    except (ValueError, TypeError, json.JSONDecodeError):
        return False
    return int(payload.get("exp") or 0) > now_ts()


# ── one-time links ───────────────────────────────────────────────────

def email_token_hash(token: str) -> str:
    return hashlib.sha256(("email:" + token).encode("utf-8")).hexdigest()


def recovery_code_hash(code: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]", "", code.upper())
    return hmac.new(
        get_auth_secret(), ("recovery:" + normalized).encode("utf-8"), hashlib.sha256
    ).hexdigest()


def normalize_recovery_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", code.upper())


# ── TOTP ─────────────────────────────────────────────────────────────

def generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _totp_at(secret: str, step: int) -> str:
    padded = secret + "=" * (-len(secret) % 8)
    key = base64.b32decode(padded.upper(), casefold=True)
    counter = step.to_bytes(8, "big")
    digest = hmac.new(key, counter, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = (
        (digest[offset] & 0x7F) << 24
        | (digest[offset + 1] & 0xFF) << 16
        | (digest[offset + 2] & 0xFF) << 8
        | (digest[offset + 3] & 0xFF)
    )
    return str(binary % (10 ** TOTP_DIGITS)).zfill(TOTP_DIGITS)


def verify_totp(
    secret: str,
    code: str,
    last_used_step: Optional[int] = None,
    at_time: Optional[int] = None,
) -> Tuple[bool, int]:
    cleaned = re.sub(r"\s", "", code or "")
    if not re.fullmatch(r"\d{6}", cleaned):
        return False, 0
    current = int((at_time if at_time is not None else now_ts()) // TOTP_PERIOD)
    for offset in range(-TOTP_WINDOW, TOTP_WINDOW + 1):
        step = current + offset
        if last_used_step is not None and step <= last_used_step:
            continue
        if hmac.compare_digest(_totp_at(secret, step), cleaned):
            return True, step
    return False, 0


def otpauth_uri(secret: str, email: str) -> str:
    label = quote(f"{TOTP_ISSUER}:{email}", safe="")
    issuer = quote(TOTP_ISSUER, safe="")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={issuer}"
        f"&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_PERIOD}"
    )


def qr_data_uri(uri: str) -> Optional[str]:
    try:
        import qrcode
        import qrcode.image.svg

        image = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=8)
        buffer = io.BytesIO()
        image.save(buffer)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/svg+xml;base64,{encoded}"
    except Exception as exc:  # pragma: no cover - optional rendering path
        logger.warning("Could not render a TOTP QR code: %s", exc)
        return None


def generate_recovery_codes() -> Tuple[list[str], list[str]]:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    plain: list[str] = []
    hashed: list[str] = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(alphabet) for _ in range(10))
        code = f"{raw[:5]}-{raw[5:]}"
        plain.append(code)
        hashed.append(recovery_code_hash(code))
    return plain, hashed


# ── misc ─────────────────────────────────────────────────────────────

def sanitize_next_path(value: Optional[str], fallback: str = "/") -> str:
    if not value:
        return fallback
    candidate = value.strip()
    if (
        not candidate.startswith("/")
        or candidate.startswith("//")
        or "\\" in candidate
        or any(ord(char) < 32 for char in candidate)
        or "://" in candidate
    ):
        return fallback
    return candidate[:500]


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    if not domain:
        return "***"
    visible = local[:1] if local else ""
    return f"{visible}***@{domain}"


def device_label(user_agent: Optional[str]) -> str:
    ua = (user_agent or "").lower()
    if "iphone" in ua:
        device = "iPhone"
    elif "ipad" in ua:
        device = "iPad"
    elif "android" in ua:
        device = "Android device"
    elif "windows" in ua:
        device = "Windows PC"
    elif "macintosh" in ua or "mac os" in ua:
        device = "Mac"
    elif "linux" in ua:
        device = "Linux device"
    else:
        device = "Unknown device"

    if "edg/" in ua:
        browser = "Edge"
    elif "firefox/" in ua:
        browser = "Firefox"
    elif "chrome/" in ua or "crios/" in ua:
        browser = "Chrome"
    elif "safari/" in ua:
        browser = "Safari"
    else:
        browser = "Browser"
    return f"{browser} on {device}"


def joined_errors(errors: Iterable[str]) -> str:
    return " ".join(errors)
