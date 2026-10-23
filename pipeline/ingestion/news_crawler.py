"""Bounded news crawling and article-text extraction.

This is deliberately not a general web crawler. It only visits article URLs
belonging to outlets in ``seeds/outlets.json``, honours robots.txt and
per-host pacing, skips paywalled publishers, and stops at a configurable URL
and time budget. Extracted text is used for clustering/search; the UI never
renders full article text.
"""
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from pipeline.config import settings
from pipeline.ingestion.schema import canonicalize_url, clean_text, make_raw_article, parse_datetime

try:
    import trafilatura
except ImportError:  # pragma: no cover - dependency is declared in requirements
    trafilatura = None

logger = logging.getLogger("pipeline.ingestion.crawler")

USER_AGENT = (
    "Mozilla/5.0 (compatible; GlobeNewsAtlas/1.0; "
    "+https://github.com/aayusbhat26/project_1) news-crawler"
)
SKIP_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".pdf", ".mp3",
    ".mp4", ".webm", ".zip", ".gz", ".css", ".js", ".ico",
}
SKIP_PATH_PARTS = ("/login", "/signin", "/subscribe", "/account", "/search", "/tag/", "/tags/")
DISALLOW_INDEXING_SIGNALS = ("noindex", "noarchive", "nosnippet", "noai")
META_TAG_RE = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)


@dataclass
class CrawlCandidate:
    url: str
    canonical_url: str
    outlet: Dict[str, Any]
    published_at: Optional[str] = None
    title: str = ""
    from_sitemap: bool = False
    source_row: Optional[Dict[str, Any]] = None


@dataclass
class CrawlResult:
    content_by_url: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    new_articles: List[Dict[str, Any]] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)


class NewsCrawler:
    def __init__(self, seeds_file: Optional[Path] = None):
        self.seeds_file = seeds_file or Path(__file__).resolve().parents[2] / "seeds" / "outlets.json"
        self.outlets = self._load_outlets()
        self.by_domain: Dict[str, Dict[str, Any]] = {}
        for outlet in self.outlets:
            domain = self._clean_domain(outlet.get("domain"))
            if domain:
                self.by_domain[domain] = outlet
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en;q=0.9,*;q=0.5",
            }
        )
        self._robots: Dict[str, Dict[str, Any]] = {}
        self._last_fetch: Dict[str, float] = {}
        self._failures: Dict[str, int] = {}
        self._blocked: Set[str] = set()
        self._deadline = 0.0

    # ------------------------------------------------------------------ setup
    def _load_outlets(self) -> List[Dict[str, Any]]:
        if not self.seeds_file.exists():
            return []
        try:
            payload = json.loads(self.seeds_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("Could not read outlet seeds: %s", exc)
            return []
        if not isinstance(payload, list):
            return []
        return [
            outlet
            for outlet in payload
            if isinstance(outlet, dict)
            and not outlet.get("paywall")
            and outlet.get("domain")
        ]

    @staticmethod
    def _clean_domain(domain: Any) -> str:
        text = str(domain or "").strip().lower().removeprefix("www.")
        return text.split("/")[0]

    def _domain(self, url: str) -> str:
        return self._clean_domain(urlparse(url).netloc)

    def _outlet_for(self, url: str) -> Optional[Dict[str, Any]]:
        domain = self._domain(url)
        if not domain:
            return None
        return self.by_domain.get(domain)

    def _deadline_left(self) -> float:
        return self._deadline - time.monotonic()

    # --------------------------------------------------------------- robots
    def _robots_for(self, domain: str) -> Dict[str, Any]:
        if domain in self._robots:
            return self._robots[domain]
        info: Dict[str, Any] = {"allow": True, "delay": max(0.5, settings.crawler_host_delay)}
        robots_url = f"https://{domain}/robots.txt"
        try:
            response = self.session.get(robots_url, timeout=min(settings.request_timeout, 6), allow_redirects=True)
            if response.status_code == 404:
                self._robots[domain] = info
                return info
            if response.status_code in {401, 403, 429}:
                info["allow"] = False
            elif response.ok:
                parser = RobotFileParser()
                parser.set_url(robots_url)
                parser.parse(response.text.splitlines())
                info["parser"] = parser
                delay = parser.crawl_delay(USER_AGENT) or parser.crawl_delay("*") or 0
                if delay:
                    info["delay"] = max(float(delay), 0.5)
        except requests.RequestException as exc:
            logger.info("robots.txt unavailable for %s (%s); skipping host", domain, exc)
            info["allow"] = False
        self._robots[domain] = info
        return info

    def _can_fetch(self, url: str) -> bool:
        domain = self._domain(url)
        if not domain or domain in self._blocked:
            return False
        info = self._robots_for(domain)
        if not info.get("allow", True):
            return False
        parser = info.get("parser")
        if parser is not None and not parser.can_fetch(USER_AGENT, url):
            return False
        return True

    def _pace(self, domain: str) -> None:
        info = self._robots_for(domain)
        delay = max(0.5, float(info.get("delay", settings.crawler_host_delay)))
        previous = self._last_fetch.get(domain)
        if previous is not None:
            remaining = delay - (time.monotonic() - previous)
            if remaining > 0:
                time.sleep(min(remaining, max(0.0, self._deadline_left())))
        self._last_fetch[domain] = time.monotonic()

    # ----------------------------------------------------------------- fetch
    def _request(self, url: str) -> Optional[requests.Response]:
        domain = self._domain(url)
        if not self._can_fetch(url) or self._deadline_left() <= 0:
            return None
        self._pace(domain)
        try:
            response = self.session.get(
                url,
                timeout=min(settings.request_timeout, 10),
                allow_redirects=True,
                stream=True,
            )
            if response.status_code in {401, 402, 403, 429}:
                self._blocked.add(domain)
                logger.info("Crawler blocked at %s (%s); skipping remaining URLs for this host", domain, response.status_code)
                response.close()
                return None
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            self._failures[domain] = self._failures.get(domain, 0) + 1
            if self._failures[domain] >= 2:
                self._blocked.add(domain)
            logger.info("Crawler request failed for %s: %s", url, exc)
            return None

    def _read_response(self, response: requests.Response, limit: int) -> Optional[bytes]:
        chunks: List[bytes] = []
        total = 0
        try:
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                total += len(chunk)
                if total > limit:
                    logger.info("Crawler skipped oversized response (%s bytes limit)", limit)
                    return None
                chunks.append(chunk)
        finally:
            response.close()
        return b"".join(chunks)

    # --------------------------------------------------------------- parsing
    @staticmethod
    def _local_tag(element: ET.Element) -> str:
        return element.tag.rsplit("}", 1)[-1].lower()

    def _xml_entries(self, content: bytes) -> Tuple[str, List[Dict[str, Any]]]:
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            return "", []
        kind = self._local_tag(root)
        entries: List[Dict[str, Any]] = []
        for child in list(root):
            if self._local_tag(child) not in {"url", "sitemap"}:
                continue
            entry: Dict[str, Any] = {}
            for field in list(child):
                name = self._local_tag(field)
                if name == "loc":
                    entry["loc"] = (field.text or "").strip()
                elif name in {"lastmod", "publication_date", "date"}:
                    entry["lastmod"] = (field.text or "").strip()
                elif name == "title":
                    entry["title"] = clean_text(field.text, 400)
            if entry.get("loc"):
                entries.append(entry)
        return kind, entries

    @staticmethod
    def _recent_enough(value: Any, days: int) -> bool:
        parsed = parse_datetime(value)
        if not parsed:
            return True
        try:
            moment = datetime.fromisoformat(parsed)
        except ValueError:
            return True
        return moment >= datetime.now(timezone.utc) - timedelta(days=max(days, 1))

    def _sitemap_candidates(self, outlet: Dict[str, Any]) -> List[Dict[str, Any]]:
        sitemap_url = str(outlet.get("sitemap_url") or "").strip()
        if not sitemap_url:
            return []
        response = self._request(sitemap_url)
        if response is None:
            return []
        body = self._read_response(response, min(settings.crawler_max_bytes, 5_000_000))
        if not body:
            return []
        kind, entries = self._xml_entries(body)
        if kind == "sitemapindex":
            sub_filter = str(outlet.get("sitemap_filter") or "").lower()
            children = [
                entry
                for entry in entries
                if entry.get("loc") and (not sub_filter or sub_filter in entry["loc"].lower())
            ]
            children.sort(key=lambda entry: entry.get("lastmod") or "", reverse=True)
            found: List[Dict[str, Any]] = []
            for child in children[:3]:
                if self._deadline_left() <= 0:
                    break
                child_response = self._request(child["loc"])
                if child_response is None:
                    continue
                child_body = self._read_response(child_response, min(settings.crawler_max_bytes, 8_000_000))
                if not child_body:
                    continue
                child_kind, child_entries = self._xml_entries(child_body)
                if child_kind == "urlset":
                    found.extend(child_entries)
                if len(found) >= settings.crawler_per_outlet * 4:
                    break
            entries = found
        include_filter = str(outlet.get("sitemap_include") or "").lower()
        candidates = []
        for entry in entries:
            url = canonicalize_url(entry.get("loc") or "")
            if not url or (include_filter and include_filter not in url.lower()):
                continue
            if not self._is_article_url(url):
                continue
            if not self._recent_enough(entry.get("lastmod"), settings.crawler_sitemap_days):
                continue
            candidates.append(
                {
                    "url": url,
                    "published_at": entry.get("lastmod"),
                    "title": entry.get("title") or "",
                }
            )
        candidates.sort(key=lambda entry: entry.get("published_at") or "", reverse=True)
        return candidates[: settings.crawler_per_outlet]

    @staticmethod
    def _header_disallows_indexing(headers: Any) -> bool:
        value = ""
        if headers is not None:
            try:
                value = str(headers.get("X-Robots-Tag") or "").lower()
            except AttributeError:
                value = ""
        return any(signal in value for signal in DISALLOW_INDEXING_SIGNALS)

    @staticmethod
    def _html_disallows_indexing(html: bytes) -> bool:
        head = html[:200_000].decode("utf-8", "ignore")
        for tag in META_TAG_RE.findall(head):
            if not re.search(r'name=["\'](?:robots|googlebot)["\']', tag, re.IGNORECASE):
                continue
            content = re.search(r'content=["\']([^"\']*)', tag, re.IGNORECASE)
            if content and any(
                signal in content.group(1).lower() for signal in DISALLOW_INDEXING_SIGNALS
            ):
                return True
        return False

    @staticmethod
    def _is_article_url(url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        path = (parsed.path or "/").lower()
        if any(path.endswith(extension) for extension in SKIP_EXTENSIONS):
            return False
        if any(part in path for part in SKIP_PATH_PARTS):
            return False
        if path in {"", "/"}:
            return False
        return True

    # ------------------------------------------------------------- extraction
    def _extract_article(self, html: bytes, url: str, fallback_title: str = "") -> Optional[Dict[str, Any]]:
        if not trafilatura:
            return None
        try:
            payload = trafilatura.extract(
                html,
                output_format="json",
                with_metadata=True,
                include_comments=False,
                include_tables=False,
            )
            if not payload:
                return None
            data = json.loads(payload)
        except (ValueError, TypeError) as exc:
            logger.info("Crawler extraction failed for %s: %s", url, exc)
            return None
        text = clean_text(data.get("text") or data.get("raw_text") or "", settings.crawler_max_content_chars)
        if len(text) < 200:
            return None
        title = clean_text(data.get("title") or fallback_title, 400)
        if not title:
            return None
        excerpt = clean_text(data.get("excerpt") or text[:320], 400)
        published = parse_datetime(data.get("date"))
        return {
            "title": title,
            "text": text,
            "excerpt": excerpt,
            "published_at": published,
            "author": clean_text(data.get("author"), 160),
            "language": str(data.get("language") or "").strip().lower(),
            "word_count": len(text.split()),
            "url": canonicalize_url(data.get("source") or url),
        }

    # -------------------------------------------------------------- discovery
    def _feed_candidates(
        self,
        raw_articles: Iterable[Dict[str, Any]],
        recent_urls: Set[str],
    ) -> List[CrawlCandidate]:
        candidates: List[CrawlCandidate] = []
        seen: Set[str] = set()
        for article in raw_articles:
            source = str(article.get("source") or "")
            if source in {"gdelt_events"}:
                continue
            url = canonicalize_url(str(article.get("url") or article.get("canonical_url") or ""))
            if not url or url in seen or url in recent_urls:
                continue
            outlet = self._outlet_for(url)
            if not outlet or outlet.get("crawl_allowed") is False or not self._is_article_url(url):
                continue
            seen.add(url)
            candidates.append(
                CrawlCandidate(
                    url=url,
                    canonical_url=url,
                    outlet=outlet,
                    published_at=article.get("published_at"),
                    title=str(article.get("title") or ""),
                    source_row=article,
                )
            )
        candidates.sort(key=lambda candidate: candidate.published_at or "", reverse=True)
        return candidates

    def _sitemap_discovery(self, recent_urls: Set[str]) -> List[CrawlCandidate]:
        candidates: List[CrawlCandidate] = []
        seen: Set[str] = set()
        for outlet in self.outlets:
            if (
                not outlet.get("sitemap_url")
                or outlet.get("crawl_allowed") is False
                or self._deadline_left() <= 0
            ):
                continue
            for entry in self._sitemap_candidates(outlet):
                url = entry["url"]
                if url in seen or url in recent_urls:
                    continue
                seen.add(url)
                candidates.append(
                    CrawlCandidate(
                        url=url,
                        canonical_url=url,
                        outlet=outlet,
                        published_at=entry.get("published_at"),
                        title=entry.get("title") or "",
                        from_sitemap=True,
                    )
                )
        return candidates

    def _select_candidates(
        self,
        feed_candidates: List[CrawlCandidate],
        sitemap_candidates: List[CrawlCandidate],
    ) -> List[CrawlCandidate]:
        feed_urls = {candidate.canonical_url for candidate in feed_candidates}
        sitemap_only = [candidate for candidate in sitemap_candidates if candidate.canonical_url not in feed_urls]

        selected: List[CrawlCandidate] = []
        seen: Set[str] = set()
        per_outlet: Dict[str, int] = {}

        def add(candidate: CrawlCandidate) -> bool:
            outlet_id = str(candidate.outlet.get("id") or candidate.outlet.get("domain") or "")
            if candidate.canonical_url in seen:
                return False
            if per_outlet.get(outlet_id, 0) >= settings.crawler_per_outlet:
                return False
            if len(selected) >= settings.crawler_max_urls:
                return False
            selected.append(candidate)
            seen.add(candidate.canonical_url)
            per_outlet[outlet_id] = per_outlet.get(outlet_id, 0) + 1
            return True

        # Half the budget goes to sitemap-only stories, which feeds can miss.
        sitemap_quota = max(1, settings.crawler_max_urls // 2)
        for candidate in sitemap_only:
            if len(selected) >= sitemap_quota:
                break
            add(candidate)
        for candidate in feed_candidates:
            if len(selected) >= settings.crawler_max_urls:
                break
            add(candidate)
        for candidate in sitemap_only:
            if len(selected) >= settings.crawler_max_urls:
                break
            add(candidate)
        return selected

    # ------------------------------------------------------------------- run
    def run(
        self,
        raw_articles: List[Dict[str, Any]],
        recent_urls: Optional[Set[str]] = None,
    ) -> CrawlResult:
        result = CrawlResult()
        if not settings.enable_crawler or not trafilatura:
            result.stats = {"enabled": 0, "attempted": 0, "fetched": 0, "extracted": 0}
            return result

        self._deadline = time.monotonic() + max(settings.crawler_time_budget_seconds, 30)
        recent = {canonicalize_url(url) for url in (recent_urls or set()) if url}
        feed = self._feed_candidates(raw_articles, recent)
        sitemap = self._sitemap_discovery(recent)
        selected = self._select_candidates(feed, sitemap)
        result.stats = {
            "enabled": 1,
            "feed_candidates": len(feed),
            "sitemap_candidates": len(sitemap),
            "selected": len(selected),
            "attempted": 0,
            "fetched": 0,
            "extracted": 0,
            "skipped_directive": 0,
            "failed": 0,
        }

        for candidate in selected:
            if self._deadline_left() <= 0:
                break
            result.stats["attempted"] += 1
            response = self._request(candidate.url)
            if response is None:
                result.stats["failed"] += 1
                continue
            if self._header_disallows_indexing(response.headers):
                result.stats["skipped_directive"] += 1
                response.close()
                continue
            body = self._read_response(response, settings.crawler_max_bytes)
            if not body:
                result.stats["failed"] += 1
                continue
            result.stats["fetched"] += 1
            if self._html_disallows_indexing(body):
                result.stats["skipped_directive"] += 1
                continue
            article = self._extract_article(body, candidate.url, candidate.title)
            if not article:
                result.stats["failed"] += 1
                continue
            result.stats["extracted"] += 1
            extracted_url = canonicalize_url(article.get("url") or candidate.url)
            content_record = {
                "title": article["title"],
                "text": article["text"],
                "excerpt": article["excerpt"],
                "published_at": article.get("published_at") or candidate.published_at,
                "author": article.get("author") or "",
                "language": article.get("language") or candidate.outlet.get("language") or "en",
                "word_count": article["word_count"],
                "url": extracted_url,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "outlet": candidate.outlet.get("name") or "",
                "outlet_id": candidate.outlet.get("id") or "",
                "domain": candidate.outlet.get("domain") or self._domain(extracted_url),
            }
            result.content_by_url[candidate.canonical_url] = content_record
            result.content_by_url[extracted_url] = content_record
            if candidate.from_sitemap and candidate.source_row is None:
                result.new_articles.append(
                    make_raw_article(
                        source="sitemap_crawler",
                        source_id=candidate.canonical_url,
                        title=article["title"],
                        url=candidate.canonical_url,
                        outlet=candidate.outlet.get("name") or "",
                        outlet_id=candidate.outlet.get("id") or "",
                        domain=candidate.outlet.get("domain") or "",
                        alignment=candidate.outlet.get("alignment") or "unrated",
                        country=candidate.outlet.get("country"),
                        language=article.get("language") or candidate.outlet.get("language") or "en",
                        author=article.get("author") or "",
                        published_at=content_record["published_at"],
                        snippet=content_record["excerpt"],
                        category=None,
                        source_metadata={
                            "crawler": "sitemap",
                            "sitemap_url": candidate.outlet.get("sitemap_url"),
                        },
                        raw_payload={"crawler": "sitemap", "word_count": article["word_count"]},
                    )
                )
        logger.info("Crawler: %s", result.stats)
        return result

    # --------------------------------------------------------------- attach
    def attach_raw_content(
        self,
        raw_articles: List[Dict[str, Any]],
        result: CrawlResult,
    ) -> int:
        attached = 0
        for article in raw_articles:
            source_url = canonicalize_url(str(article.get("canonical_url") or article.get("url") or ""))
            content = result.content_by_url.get(source_url)
            if not content:
                continue
            article["content"] = content["text"]
            if len(str(article.get("snippet") or "")) < 180:
                article["snippet"] = content["excerpt"] or content["text"][:400]
            attached += 1
        return attached

    def attach_content(
        self,
        normalised: List[Dict[str, Any]],
        result: CrawlResult,
    ) -> List[Dict[str, Any]]:
        content_rows: List[Dict[str, Any]] = []
        seen_articles: Set[str] = set()
        for article in normalised:
            source_url = canonicalize_url(str(article.get("canonical_url") or article.get("url") or ""))
            content = result.content_by_url.get(source_url)
            if not content:
                continue
            article["content"] = content["text"]
            article["content_excerpt"] = content["excerpt"]
            article["word_count"] = content["word_count"]
            article["crawled_at"] = content["fetched_at"]
            if len(str(article.get("snippet") or "")) < 180:
                article["snippet"] = content["excerpt"] or content["text"][:400]
            article_id = str(article.get("id") or "")
            if not article_id or article_id in seen_articles:
                continue
            seen_articles.add(article_id)
            content_rows.append(
                {
                    "article_id": article_id,
                    "url": content.get("url") or source_url,
                    "canonical_url": source_url,
                    "title": article.get("title") or content.get("title") or "",
                    "outlet": article.get("outlet") or content.get("outlet") or "",
                    "outlet_id": article.get("outlet_id") or content.get("outlet_id") or "",
                    "domain": article.get("domain") or content.get("domain") or "",
                    "published_at": article.get("published_at") or content.get("published_at"),
                    "fetched_at": content.get("fetched_at"),
                    "word_count": int(content.get("word_count") or 0),
                    "language": content.get("language") or "en",
                    "text": content["text"],
                    "excerpt": content["excerpt"],
                }
            )
        return content_rows
