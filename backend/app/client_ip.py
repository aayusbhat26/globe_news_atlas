"""Resolve the client address used for rate limiting and audit records.

The app must never trust ``X-Forwarded-For``: any client can set it. Behind a
proxy that overwrites ``CF-Connecting-IP`` (Cloudflare in front of Render) the
header is only honoured when ``TRUST_PROXY_HEADERS`` is enabled or when the
process runs on Render (``RENDER=true``). Otherwise the ASGI server's socket
peer address is used. Values are validated/truncated so they always fit the
database columns.
"""

from __future__ import annotations

import ipaddress
import os
from typing import Optional

from fastapi import Request

from app.config import settings

MAX_IP_LENGTH = 45


def proxy_headers_trusted() -> bool:
    if settings.trust_proxy_headers:
        return True
    return (os.getenv("RENDER") or "").strip().lower() in {"1", "true", "yes", "on"}


def clean_client_ip(value: object, *, validate: bool = False) -> Optional[str]:
    """Return a storage-safe address, optionally requiring a real IP literal."""
    text = str(value or "").strip()
    if not text:
        return None
    if validate:
        try:
            text = str(ipaddress.ip_address(text))
        except ValueError:
            return None
    return text[:MAX_IP_LENGTH] or None


def get_client_ip(request: Optional[Request]) -> Optional[str]:
    """Client IP for limiting and auditing; never reads X-Forwarded-For."""
    if request is None:
        return None
    if proxy_headers_trusted():
        trusted = clean_client_ip(
            request.headers.get("cf-connecting-ip"), validate=True
        )
        if trusted:
            return trusted
    client = getattr(request, "client", None)
    return clean_client_ip(getattr(client, "host", None))


def rate_limit_key(request: Request) -> str:
    """SlowAPI key function: one bucket per socket peer (or trusted proxy)."""
    return get_client_ip(request) or "unknown"
