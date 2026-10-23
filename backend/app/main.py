import asyncio
import logging
import mimetypes
import os
import re
from contextlib import asynccontextmanager
from html import escape
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from slowapi.middleware import SlowAPIMiddleware

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
    if settings.hf_token and settings.hf_repo and settings.hf_pull_serving:
        refresh_task = asyncio.create_task(_refresh_serving_loop())

    try:
        yield
    finally:
        if refresh_task:
            refresh_task.cancel()
            await asyncio.gather(refresh_task, return_exceptions=True)


app = FastAPI(
    title="Globe News Atlas API",
    description="Live globe of world events with political spectrum coverage and cited sources",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_origin_regex=(
        None
        if settings.environment == "production"
        else r"https?://(localhost|127\.0\.0\.1)(:\d+)?"
    ),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
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


@app.middleware("http")
async def cache_and_security_headers(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if response.status_code == 200 and path.startswith(("/assets/", "/data/", "/fonts/")):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif path.startswith("/v1/") and path not in {"/v1/snapshot", "/v1/stream"}:
        response.headers["Cache-Control"] = "no-store"
    elif path == "/health":
        response.headers["Cache-Control"] = "no-store"
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if path.startswith("/embed/"):
        # Public event cards are meant to be framed; nothing else is.
        response.headers["Content-Security-Policy"] = "frame-ancestors *"
    else:
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
    )
    if settings.environment == "production" and settings.secure_cookies:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response

app.include_router(api_router, prefix="/v1")


@app.get("/health")
async def health():
    """Health check with pipeline data status."""
    status = snapshot_service.status()
    status.pop("storage", None)
    return {
        "status": "ok",
        "version": "2.0.0",
        "environment": settings.environment,
        "data": status,
    }


@app.head("/health", include_in_schema=False)
async def health_head() -> Response:
    return Response(status_code=200)


frontend_dist = Path(
    os.getenv("FRONTEND_DIST", str(Path(__file__).resolve().parents[2] / "frontend" / "dist"))
)
if (frontend_dist / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")

    @app.get("/")
    async def serve_index():
        return FileResponse(frontend_dist / "index.html")

    frontend_root = frontend_dist.resolve()

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
        tags = "\n".join(
            [
                f'<meta property="og:type" content="article">',
                f'<meta property="og:site_name" content="Globe News Atlas">',
                f'<meta property="og:title" content="{escape(detail.title)}">',
                f'<meta property="og:description" content="{description}">',
                f'<meta property="og:url" content="{canonical}">',
                f'<meta name="twitter:card" content="summary">',
                f'<link rel="canonical" href="{canonical}">',
            ]
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
