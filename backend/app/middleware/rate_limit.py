from slowapi import Limiter

from app.client_ip import rate_limit_key

limiter = Limiter(
    # Never key on X-Forwarded-For: it is client-controlled. See client_ip.py.
    key_func=rate_limit_key,
    default_limits=["100/minute"],
    storage_uri="memory://",
)
