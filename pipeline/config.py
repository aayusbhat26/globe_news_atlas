"""Central pipeline configuration loaded from .env / environment."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # dotenv is optional at runtime
    pass

ROOT_DIR = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


WINDOWS: Dict[str, int] = {"1h": 60, "24h": 24 * 60, "7d": 7 * 24 * 60, "30d": 30 * 24 * 60}

DEFAULT_GDELT_DOC_QUERIES: List[str] = [
    "geopolitics",
    "conflict OR ceasefire",
    "election OR parliament",
    "economy OR markets",
    "climate OR disaster",
    "protest OR unrest",
    "India",
    "China",
    "Ukraine",
    "Middle East",
    "Africa",
    "Latin America",
    "Europe",
    "Southeast Asia",
]


@dataclass(frozen=True)
class PipelineConfig:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", str(ROOT_DIR / "data"))))

    # Hugging Face dataset storage
    hf_token: str = field(default_factory=lambda: os.getenv("HF_TOKEN", "").strip())
    hf_repo: str = field(default_factory=lambda: os.getenv("HF_DATASET_REPO", "").strip())
    hf_storage_type: str = field(default_factory=lambda: os.getenv("HF_STORAGE_TYPE", "dataset").strip().lower())
    hf_private: bool = field(default_factory=lambda: _bool("HF_DATASET_PRIVATE", True))
    hf_pull_before_run: bool = field(default_factory=lambda: _bool("HF_PULL_BEFORE_RUN", True))
    hf_push_after_run: bool = field(default_factory=lambda: _bool("HF_PUSH_AFTER_RUN", True))
    hf_pull_days: int = field(default_factory=lambda: _int("HF_PULL_DAYS", 30))
    hf_bronze_checkpoint: bool = field(default_factory=lambda: _bool("HF_BRONZE_CHECKPOINT", True))
    hf_push_crawl_text: bool = field(default_factory=lambda: _bool("HF_PUSH_CRAWL_TEXT", False))
    bronze_retention_days: int = field(default_factory=lambda: _int("BRONZE_RETENTION_DAYS", 14))
    silver_retention_days: int = field(default_factory=lambda: _int("SILVER_RETENTION_DAYS", 45))

    # Source toggles / limits
    enable_gdelt_events: bool = field(default_factory=lambda: _bool("ENABLE_GDELT_EVENTS", True))
    enable_gdelt_doc: bool = field(default_factory=lambda: _bool("ENABLE_GDELT_DOC", True))
    enable_rss: bool = field(default_factory=lambda: _bool("ENABLE_RSS", True))
    enable_google_news: bool = field(default_factory=lambda: _bool("ENABLE_GOOGLE_NEWS", True))
    enable_reddit: bool = field(default_factory=lambda: _bool("ENABLE_REDDIT", True))
    enable_bluesky: bool = field(default_factory=lambda: _bool("ENABLE_BLUESKY", True))
    enable_usgs: bool = field(default_factory=lambda: _bool("ENABLE_USGS", True))
    enable_reliefweb: bool = field(default_factory=lambda: _bool("ENABLE_RELIEFWEB", True))
    enable_newsapi: bool = field(default_factory=lambda: _bool("ENABLE_NEWSAPI", True))
    enable_acled: bool = field(default_factory=lambda: _bool("ENABLE_ACLED", True))

    gdelt_doc_queries: List[str] = field(
        default_factory=lambda: [
            q.strip()
            for q in os.getenv("GDELT_DOC_QUERIES", "|".join(DEFAULT_GDELT_DOC_QUERIES)).split("|")
            if q.strip()
        ]
    )
    gdelt_doc_timespan: str = field(default_factory=lambda: os.getenv("GDELT_DOC_TIMESPAN", "24h"))
    gdelt_max_rows: int = field(default_factory=lambda: _int("GDELT_MAX_ROWS", 2500))
    gdelt_top_events: int = field(default_factory=lambda: _int("GDELT_TOP_EVENTS", 250))
    gdelt_doc_max_records: int = field(default_factory=lambda: _int("GDELT_DOC_MAX_RECORDS", 75))
    gdelt_doc_max_articles: int = field(default_factory=lambda: _int("GDELT_DOC_MAX_ARTICLES", 600))

    rss_max_items: int = field(default_factory=lambda: _int("RSS_MAX_ITEMS", 8))
    rss_max_outlets: int = field(default_factory=lambda: _int("RSS_MAX_OUTLETS", 0))
    google_news_max_items: int = field(default_factory=lambda: _int("GOOGLE_NEWS_MAX_ITEMS", 15))
    reddit_min_score: int = field(default_factory=lambda: _int("REDDIT_MIN_SCORE", 25))
    request_timeout: float = field(default_factory=lambda: _float("REQUEST_TIMEOUT_SECONDS", 8.0))
    host_delay_seconds: float = field(default_factory=lambda: _float("HOST_DELAY_SECONDS", 1.0))

    # Bounded article crawler. It follows the outlet allowlist, robots.txt and
    # per-host pacing, and never bypasses paywalls or bot protection.
    enable_crawler: bool = field(default_factory=lambda: _bool("ENABLE_CRAWLER", True))
    crawler_max_urls: int = field(default_factory=lambda: _int("CRAWLER_MAX_URLS", 120))
    crawler_per_outlet: int = field(default_factory=lambda: _int("CRAWLER_PER_OUTLET", 8))
    crawler_sitemap_days: int = field(default_factory=lambda: _int("CRAWLER_SITEMAP_DAYS", 3))
    crawler_time_budget_seconds: int = field(default_factory=lambda: _int("CRAWLER_TIME_BUDGET_SECONDS", 180))
    crawler_host_delay: float = field(default_factory=lambda: _float("CRAWLER_HOST_DELAY_SECONDS", 1.0))
    crawler_max_bytes: int = field(default_factory=lambda: _int("CRAWLER_MAX_BYTES", 2_000_000))
    crawler_retention_days: int = field(default_factory=lambda: _int("CRAWLER_RETENTION_DAYS", 14))
    crawler_max_content_chars: int = field(default_factory=lambda: _int("CRAWLER_MAX_CONTENT_CHARS", 6000))

    # Silver / gold
    # Safe upper bound for embedding/clustering. It is deliberately well above
    # the 30-day editorial volume so the candidate pool is not truncated before
    # window assignment; MinHash sharding is configured to match.
    cluster_max_articles: int = field(default_factory=lambda: _int("CLUSTER_MAX_ARTICLES", 12000))
    dedupe_minhash_max_articles: int = field(default_factory=lambda: _int("DEDUPE_MINHASH_MAX_ARTICLES", 20000))
    cluster_distance_threshold: float = field(default_factory=lambda: _float("CLUSTER_DISTANCE_THRESHOLD", 0.45))
    enable_llm_summaries: bool = field(default_factory=lambda: _bool("ENABLE_LLM_SUMMARIES", True))
    max_llm_summaries: int = field(default_factory=lambda: _int("MAX_LLM_SUMMARIES_PER_RUN", 25))
    max_snapshot_events: int = field(default_factory=lambda: _int("MAX_SNAPSHOT_EVENTS", 400))
    max_snapshot_events_7d: int = field(default_factory=lambda: _int("MAX_SNAPSHOT_EVENTS_7D", 600))
    max_snapshot_events_30d: int = field(default_factory=lambda: _int("MAX_SNAPSHOT_EVENTS_30D", 800))
    max_arcs: int = field(default_factory=lambda: _int("MAX_VISIBLE_ARCS", 200))

    # API keys (all optional except HF)
    groq_api_key: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", "").strip())
    groq_model: str = field(default_factory=lambda: os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b").strip())
    groq_rpm: int = field(default_factory=lambda: _int("GROQ_RPM", 20))
    groq_rpd: int = field(default_factory=lambda: _int("GROQ_RPD", 1000))
    openrouter_api_key: str = field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY", "").strip())
    openrouter_models: List[str] = field(
        default_factory=lambda: [
            model.strip()
            for model in os.getenv(
                "OPENROUTER_FREE_MODELS",
                "minimax/minimax-m3.1-flash:free,nvidia/nemotron-3.5-lightning:free,google/gemma-4-31b-it:free",
            ).replace("|", ",").split(",")
            if model.strip()
        ]
    )
    openrouter_rpm: int = field(default_factory=lambda: _int("OPENROUTER_RPM", 6))
    openrouter_rpd: int = field(default_factory=lambda: _int("OPENROUTER_RPD", 25))
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", "").strip())
    geonames_username: str = field(default_factory=lambda: os.getenv("GEONAMES_USERNAME", "").strip())
    newsapi_key: str = field(default_factory=lambda: os.getenv("NEWSAPI_KEY", "").strip())
    newsapi_daily_limit: int = field(default_factory=lambda: _int("NEWSAPI_DAILY_LIMIT", 10))
    acled_key: str = field(default_factory=lambda: os.getenv("ACLED_ACCESS_KEY", "").strip())
    acled_email: str = field(default_factory=lambda: os.getenv("ACLED_EMAIL", "").strip())
    acled_password: str = field(default_factory=lambda: os.getenv("ACLED_PASSWORD", "").strip())
    reddit_user_agent: str = field(
        default_factory=lambda: os.getenv("REDDIT_USER_AGENT", "GlobeNewsAtlas/1.0 (+https://github.com/aayusbhat26/project_1)")
    )

    @property
    def hf_enabled(self) -> bool:
        return bool(self.hf_token and self.hf_repo)


settings = PipelineConfig()
