import asyncio
import logging
import mimetypes
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.router import api_router
from app.auth.errors import AuthError
from app.auth.store import auth_store
from app.config import settings
from app.middleware.rate_limit import limiter
from app.services.event_service import event_service
from app.services.snapshot_service import snapshot_service

mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("application/geo+json", ".geojson")
mimetypes.add_type("font/woff2", ".woff2")

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("app.main")


def hf_refresh_enabled() -> bool:
    """Public HF buckets need no token; only repo + pull flag are required."""
    return bool(settings.hf_repo and settings.hf_pull_serving)


async def _refresh_serving_loop() -> None:
    interval = max(30, int(settings.hf_pull_interval_seconds or 120))
    while True:
        await asyncio.sleep(interval)
        try:
            count = await asyncio.to_thread(snapshot_service.refresh_from_hf)
            if count:
                logger.info("Picked up %d updated serving files from Hugging Face.", count)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Periodic HF serving refresh failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Cold deployments pull the gold serving files from the HF bucket or dataset.
    available = await asyncio.to_thread(snapshot_service.ensure_local)
    if available:
        manifest = snapshot_service.get_manifest()
        logger.info(
            "Serving pipeline data (run %s, generated %s)",
            manifest.get("run_id"),
            manifest.get("generated_at"),
        )
    else:
        logger.warning(
            "No serving artifacts in %s. Run the pipeline or configure HF_TOKEN/HF_DATASET_REPO.",
            snapshot_service.root,
        )

    try:
        await asyncio.to_thread(auth_store.ensure_ready)
        logger.info(
            "Reader accounts ready (Google sign-in %s, email delivery %s)",
            "on" if settings.google_login_enabled else "off",
            settings.email_delivery,
        )
    except Exception as exc:
        logger.error("Could not initialise the account database: %s", exc)

    refresh_task = None
    if hf_refresh_enabled():
        refresh_task = asyncio.create_task(_refresh_serving_loop())

    try:
        yield
    finally:
        if refresh_task:
            refresh_task.cancel()
            await asyncio.gather(refresh_task, return_exceptions=True)


DOCS_ENABLED = not settings.is_production

app = FastAPI(
    title="Globe News Atlas API",
    description="Live globe of world events with political spectrum coverage and cited sources",
    version="2.0.0",
    docs_url="/docs" if DOCS_ENABLED else None,
    redoc_url="/redoc" if DOCS_ENABLED else None,
    openapi_url="/openapi.json" if DOCS_ENABLED else None,
    lifespan=lifespan,
)

app.add_middleware(GZipMiddleware, minimum_size=500)
# No implicit localhost/Vercel origins: cross-origin browser clients must be
# listed explicitly in ALLOWED_ORIGINS. The SPA is served same-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins or []),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count"],
)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.resolved_allowed_hosts,
    www_redirect=False,
)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(AuthError)
async def auth_error_handler(request: Request, exc: AuthError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": {"code": exc.code, "message": exc.message}},
        headers={"Cache-Control": "no-store"},
    )


SPA_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'sha256-fAdI4fwecFT5mhxHsTVu7fm1q1zvs+indMMKVmA5gN0='; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self'; "
    "img-src 'self' data: https:; "
    "connect-src 'self'; "
    "frame-ancestors 'self'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "object-src 'none'"
)


@app.middleware("http")
async def cache_and_security_headers(request, call_next):
    path = request.url.path
    # Defence in depth for deployments that flip ENVIRONMENT to production.
    if settings.is_production and (
        path in {"/docs", "/redoc", "/openapi.json"} or path.startswith("/docs/")
    ):
        return JSONResponse(
            {"detail": "Not Found"}, status_code=404, headers={"Cache-Control": "no-store"}
        )
    response = await call_next(request)
    if response.status_code == 200 and path.startswith(("/assets/", "/data/", "/fonts/")):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif path.startswith("/v1/") and path not in {"/v1/snapshot", "/v1/stream"}:
        response.headers["Cache-Control"] = "no-store"
    elif path in {"/health", "/ready"}:
        response.headers["Cache-Control"] = "no-store"
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    content_type = response.headers.get("content-type", "")
    if path.startswith("/embed/"):
        # Public event cards are meant to be framed; nothing else is.
        response.headers["Content-Security-Policy"] = "frame-ancestors *"
    elif content_type.startswith("text/html"):
        # SPA pages: scripts/fonts from self, inline styles (React style props),
        # images from self/data/https, fetch + SSE to self only.
        response.headers["Content-Security-Policy"] = SPA_CSP
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    else:
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
    )
    if settings.is_production and settings.secure_cookies:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response

app.include_router(api_router, prefix="/v1")


def _readiness() -> dict:
    age = snapshot_service.data_age_seconds()
    max_age = max(0, int(settings.snapshot_max_age_seconds))
    snapshot_ready = snapshot_service.is_fresh(max_age)
    auth_ready = auth_store.ping()
    return {
        "ready": bool(snapshot_ready and auth_ready),
        "snapshot_ready": snapshot_ready,
        "auth_db_ready": auth_ready,
        "data_age_seconds": age,
        "snapshot_max_age_seconds": max_age,
    }


@app.get("/health")
async def health():
    """Liveness probe; always 200 while the process can answer."""
    status = snapshot_service.status()
    status.pop("storage", None)
    readiness = _readiness()
    return {
        "status": "ok" if readiness["ready"] else "degraded",
        "ready": readiness["ready"],
        "data_age_seconds": readiness["data_age_seconds"],
        "version": "2.0.0",
        "environment": settings.environment,
        "data": status,
    }


@app.head("/health", include_in_schema=False)
async def health_head() -> Response:
    return Response(status_code=200)


@app.get("/ready")
async def ready() -> JSONResponse:
    """Readiness probe: fresh serving data and a reachable account database."""
    readiness = _readiness()
    payload = {
        "status": "ready" if readiness["ready"] else "not_ready",
        **readiness,
        "version": "2.0.0",
    }
    return JSONResponse(
        payload,
        status_code=200 if readiness["ready"] else 503,
        headers={"Cache-Control": "no-store"},
    )


@app.api_route(
    "/v1",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    include_in_schema=False,
)
@app.api_route(
    "/v1/{full_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    include_in_schema=False,
)
async def api_not_found(full_path: str = "") -> JSONResponse:
    """Unknown API paths stay JSON instead of falling through to the SPA."""
    return JSONResponse({"detail": "Not Found"}, status_code=404)


frontend_dist = Path(
    os.getenv("FRONTEND_DIST", str(Path(__file__).resolve().parents[2] / "frontend" / "dist"))
)
if (frontend_dist / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")

    @app.get("/")
    async def serve_index():
        return FileResponse(frontend_dist / "index.html")

    frontend_root = frontend_dist.resolve()

    @app.get("/sitemap.xml", include_in_schema=False)
    async def sitemap(request: Request):
        base = (settings.public_base_url or str(request.base_url)).rstrip("/")
        snapshot = snapshot_service.get_snapshot("30d") or {}
        fallback_lastmod = datetime.now(timezone.utc).isoformat()
        page_lastmod = snapshot.get("ts") or fallback_lastmod
        entries = [
            (f"{base}/", page_lastmod, "hourly", "1.0"),
            (f"{base}/storylines", page_lastmod, "hourly", "0.7"),
            (f"{base}/thin-file", page_lastmod, "hourly", "0.7"),
            (f"{base}/rewind", page_lastmod, "daily", "0.6"),
            (f"{base}/privacy", page_lastmod, "yearly", "0.2"),
            (f"{base}/terms", page_lastmod, "yearly", "0.2"),
        ]
        seen = {url for url, _, _, _ in entries}
        for event in snapshot.get("events", []):
            event_id = event.get("id")
            if not event_id:
                continue
            url = f"{base}/event/{event_id}"
            if url in seen:
                continue
            seen.add(url)
            entries.append((url, event.get("at") or page_lastmod, "daily", "0.5"))
        body = "".join(
            f"<url><loc>{escape(url)}</loc><lastmod>{escape(str(ts))}</lastmod>"
            f"<changefreq>{freq}</changefreq><priority>{priority}</priority></url>"
            for url, ts, freq, priority in entries
        )
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"{body}</urlset>"
        )
        return Response(
            content=xml,
            media_type="application/xml",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    def _event_share_shell(event_id: str, base_url: str) -> str | None:
        """Inject per-event OG metadata into the SPA shell for public shares."""
        detail = event_service.get_event_detail(event_id)
        if not detail:
            return None
        try:
            shell = (frontend_root / "index.html").read_text(encoding="utf-8")
        except OSError:
            return None
        title = escape(f"{detail.title} — Globe News Atlas")
        description_text = (
            detail.summary or detail.excerpt or "A world event from the Globe News Atlas."
        ).strip()
        if len(description_text) > 220:
            description_text = description_text[:217].rstrip() + "…"
        description = escape(description_text)
        canonical = escape(f"{base_url.rstrip('/')}/event/{detail.id}")
        image = escape(f"{base_url.rstrip('/')}/og-image.png")
        tags = "\n".join(
            [
                f'<meta property="og:type" content="article">',
                f'<meta property="og:site_name" content="Globe News Atlas">',
                f'<meta property="og:title" content="{escape(detail.title)}">',
                f'<meta property="og:description" content="{description}">',
                f'<meta property="og:url" content="{canonical}">',
                f'<meta property="og:image" content="{image}">',
                f'<meta property="og:image:width" content="1200">',
                f'<meta property="og:image:height" content="630">',
                f'<meta property="og:image:alt" content="Globe News Atlas — world events, coverage and provenance">',
                f'<meta name="twitter:card" content="summary_large_image">',
                f'<meta name="twitter:title" content="{escape(detail.title)}">',
                f'<meta name="twitter:description" content="{description}">',
                f'<meta name="twitter:image" content="{image}">',
                f'<link rel="canonical" href="{canonical}">',
            ]
        )
        shell = re.sub(
            r'<(?:meta|link)\b[^>]*(?:property="og:[^"]*"|name="twitter:[^"]*"|rel="canonical")[^>]*>\s*',
            "",
            shell,
            flags=re.I,
        )
        shell = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", shell, count=1, flags=re.S)
        shell = re.sub(
            r'<meta name="description"[^>]*>',
            f'<meta name="description" content="{description}">',
            shell,
            count=1,
        )
        return shell.replace("</head>", f"{tags}\n</head>", 1)

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str, request: Request):
        candidate = (frontend_dist / full_path).resolve()
        if candidate.is_file() and frontend_root in candidate.parents:
            return FileResponse(candidate)
        share = re.match(r"^(?:embed/)?event/([^/]+)/?$", full_path)
        if share:
            base = settings.public_base_url or settings.app_base_url or str(request.base_url)
            shell = await asyncio.to_thread(
                _event_share_shell, unquote(share.group(1)), base
            )
            if shell:
                return HTMLResponse(shell, headers={"Cache-Control": "public, max-age=60"})
        return FileResponse(frontend_root / "index.html")
else:
    @app.get("/")
    async def root():
        return {
            "service": "Globe News Atlas API",
            "docs": "/docs",
            "snapshot": "/v1/snapshot?window=24h",
            "health": "/health",
        }
