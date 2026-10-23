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
_WS = re.compile(r"\s+")


def _normalise_title(title: str) -> str:
    text = re.sub(r"[^a-z0-9 ]+", " ", (title or "").lower())
    return _WS.sub(" ", text).strip()


def _shingles(text: str, k: int = 3) -> Set[str]:
    words = re.findall(r"\w+", text.lower())
    if len(words) < k:
        return set(words)
    return {" ".join(words[i:i + k]) for i in range(len(words) - k + 1)}


class Deduplicator:
    def __init__(self, threshold: float = 0.7, num_perm: int = 128, max_minhash_articles: int = 4000):
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
        use_minhash = MinHash is not None and len(articles) <= self.max_minhash_articles
        url_groups: Dict[str, str] = {}
        title_groups: Dict[str, str] = {}
        primary_by_id: Dict[str, str] = {}

        for article in articles:
            article_id = str(article.get("id") or article.get("content_hash") or article.get("canonical_url") or "")
            if not article_id:
                continue
            canonical = (article.get("canonical_url") or article.get("url") or "").strip().lower()
            title_key = _normalise_title(article.get("title", ""))
            source = article.get("source", "")
            outlet = article.get("outlet_id") or article.get("domain") or article.get("outlet") or ""

            duplicate_of: Optional[str] = None
            if canonical and canonical in url_groups:
                duplicate_of = url_groups[canonical]
            elif title_key and (title_key, source, outlet) in title_groups:
                duplicate_of = title_groups[(title_key, source, outlet)]

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

            if canonical:
                url_groups[canonical] = article_id
            if title_key:
                title_groups[(title_key, source, outlet)] = article_id

            if not use_minhash:
                continue
            text = f"{article.get('title', '')} {article.get('snippet', '')}".strip()
            if len(text) < 40:
                continue
            fingerprint = self._minhash(text)
            self._minhashes[article_id] = fingerprint
            matches = self._lsh.query(fingerprint) if self._lsh else []
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
                except ValueError:
                    pass

        duplicates = sum(1 for article in articles if article.get("is_duplicate"))
        logger.info("Deduplication: %d articles, %d duplicates (%s)", len(articles), duplicates, "minhash" if use_minhash else "exact")
        return articles
