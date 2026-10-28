"""Deterministic near-duplicate detection.

Exact URL and title duplicates are always caught. MinHash LSH is used when
available to collapse syndicated wire copies without hiding distinct coverage.
"""
import hashlib
import logging
import re
from typing import Any, Dict, List, Optional, Set

try:
    from datasketch import MinHash, MinHashLSH
except ImportError:  # pragma: no cover
    MinHash = None
    MinHashLSH = None

logger = logging.getLogger("pipeline.transforms.deduplicator")

WIRE_DOMAINS = {"reuters.com", "apnews.com", "afp.com"}
OFFICIAL_EVENT_SOURCES = {"usgs", "acled", "reliefweb", "gdelt_events"}
_WS = re.compile(r"\s+")


def _official_event_key(article: Dict[str, Any]) -> str:
    source = str(article.get("source") or "").strip().lower()
    if source not in OFFICIAL_EVENT_SOURCES:
        return ""
    source_id = str(article.get("source_id") or article.get("id") or "").strip()
    return f"{source}:{source_id}" if source_id else ""


def _is_google_news(article: Dict[str, Any]) -> bool:
    metadata = article.get("source_metadata") if isinstance(article.get("source_metadata"), dict) else {}
    return bool(
        article.get("via_google_news")
        or article.get("source") == "google_news"
        or metadata.get("via_google_news")
    )


def _normalise_title(title: str) -> str:
    text = re.sub(r"[^a-z0-9 ]+", " ", (title or "").lower())
    return _WS.sub(" ", text).strip()


def _shingles(text: str, k: int = 3) -> Set[str]:
    words = re.findall(r"\w+", text.lower())
    if len(words) < k:
        return set(words)
    return {" ".join(words[i:i + k]) for i in range(len(words) - k + 1)}


class Deduplicator:
    def __init__(self, threshold: float = 0.7, num_perm: int = 128, max_minhash_articles: int = 20000):
        self.threshold = threshold
        self.num_perm = num_perm
        self.max_minhash_articles = max_minhash_articles
        self._lsh = None
        self._minhashes: Dict[str, Any] = {}

    def _reset(self) -> None:
        if MinHashLSH is not None:
            self._lsh = MinHashLSH(threshold=self.threshold, num_perm=self.num_perm)
        self._minhashes = {}

    def _minhash(self, text: str):
        if MinHash is None:
            return None
        m = MinHash(num_perm=self.num_perm, seed=1)
        for shingle in _shingles(text):
            m.update(shingle.encode("utf-8"))
        return m

    def process_articles(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        self._reset()
        # Process direct publisher links before Google News redirects so the
        # direct SCMP/Prothom Alo URL is the retained primary source.
        ordered = sorted(articles, key=_is_google_news)
        limit = max(1, int(self.max_minhash_articles))
        use_minhash = MinHash is not None
        sharded = use_minhash and len(ordered) > limit
        if sharded:
            logger.info(
                "Deduplication: %d articles exceed MinHash limit %d; sharding near-duplicate checks.",
                len(ordered),
                limit,
            )
        url_groups: Dict[str, str] = {}
        title_groups: Dict[tuple, str] = {}
        primary_by_id: Dict[str, str] = {}
        primary_official: Dict[str, str] = {}
        minhash_processed = 0

        for article in ordered:
            article_id = str(article.get("id") or article.get("content_hash") or article.get("canonical_url") or "")
            if not article_id:
                continue
            canonical = (article.get("canonical_url") or article.get("url") or "").strip().lower()
            title_key = _normalise_title(article.get("title", ""))
            outlet = str(
                article.get("outlet_id") or article.get("domain") or article.get("outlet") or ""
            ).strip().lower()
            official = _official_event_key(article)

            def conflicts_with_primary(primary_id: str) -> bool:
                primary_key = primary_official.get(primary_id, "")
                return bool(official and primary_key and official != primary_key)

            duplicate_of: Optional[str] = None
            if canonical and canonical in url_groups:
                candidate = url_groups[canonical]
                if not conflicts_with_primary(candidate):
                    duplicate_of = candidate
            if duplicate_of is None and title_key and (title_key, outlet) in title_groups:
                candidate = title_groups[(title_key, outlet)]
                if not conflicts_with_primary(candidate):
                    duplicate_of = candidate

            if duplicate_of:
                article["is_duplicate"] = True
                article["duplicate_of"] = duplicate_of
                article["duplicate_group"] = primary_by_id.get(duplicate_of, duplicate_of)
                article["is_syndicated"] = article.get("domain", "") not in WIRE_DOMAINS and article.get("domain", "") != ""
                continue

            article["is_duplicate"] = False
            article["duplicate_of"] = None
            article["is_syndicated"] = False
            primary_by_id[article_id] = article_id
            primary_official[article_id] = official

            if canonical:
                url_groups[canonical] = article_id
            if title_key:
                title_groups[(title_key, outlet)] = article_id

            if not use_minhash:
                continue
            if minhash_processed >= limit:
                # A new shard bounds memory. Exact URL/title checks still run
                # across the whole batch; only cross-shard near-duplicates are
                # sacrificed, and that is logged rather than silently disabled.
                self._reset()
                minhash_processed = 0
            text = f"{article.get('title', '')} {article.get('snippet', '')}".strip()
            if len(text) < 40:
                continue
            fingerprint = self._minhash(text)
            self._minhashes[article_id] = fingerprint
            matches = self._lsh.query(fingerprint) if self._lsh else []
            matches = [primary for primary in matches if not conflicts_with_primary(primary)]
            if matches:
                primary = matches[0]
                article["is_duplicate"] = True
                article["duplicate_of"] = primary
                article["duplicate_group"] = primary_by_id.get(primary, primary)
                article["is_syndicated"] = article.get("domain", "") not in WIRE_DOMAINS
            else:
                try:
                    self._lsh.insert(article_id, fingerprint)
                    primary_by_id[article_id] = article_id
                    primary_official[article_id] = official
                except ValueError:
                    pass
            minhash_processed += 1

        duplicates = sum(1 for article in articles if article.get("is_duplicate"))
        mode = "minhash-sharded" if sharded else ("minhash" if use_minhash else "exact")
        logger.info("Deduplication: %d articles, %d duplicates (%s)", len(articles), duplicates, mode)
        return articles
