"""Reddit discussion ingestion with a PullPush archive fallback.

The public JSON endpoints are frequently rate-limited or blocked from cloud
runners; PullPush exposes the same public post metadata without credentials.
"""
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from pipeline.config import settings
from pipeline.ingestion.base_fetcher import BaseFetcher
from pipeline.ingestion.schema import clean_text, make_raw_social

try:
    import feedparser
except ImportError:  # pragma: no cover - dependency is declared in requirements
    feedparser = None

logger = logging.getLogger("pipeline.ingestion.reddit")

USER_AGENT = settings.reddit_user_agent or "GlobeNewsAtlas/1.0"


class RedditFetcher(BaseFetcher):
    PUBLIC_URL = "https://www.reddit.com/r/{sub}/hot.json?limit=25&raw_json=1"
    OAUTH_URL = "https://oauth.reddit.com/r/{sub}/hot?limit=25&raw_json=1"
    TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
    RSS_URL = "https://www.reddit.com/r/{sub}/hot.rss"
    PULLPUSH_URL = "https://api.pullpush.io/reddit/search/submission/"

    def __init__(self, subreddits_file: Optional[Path] = None):
        super().__init__(name="reddit", max_retries=2, circuit_break_seconds=1800)
        self.subreddits_file = (
            subreddits_file
            or Path(__file__).resolve().parent.parent.parent / "seeds" / "subreddits.json"
        )
        self.client_id = os.getenv("REDDIT_CLIENT_ID", "").strip()
        self.client_secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
        self._token: Optional[str] = None
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def _load_subreddits(self) -> List[Dict[str, Any]]:
        if not self.subreddits_file.exists():
            logger.warning("Subreddit seeds missing: %s", self.subreddits_file)
            return []
        with open(self.subreddits_file, "r", encoding="utf-8") as handle:
            return [item for item in json.load(handle) if item.get("name")]

    def _oauth_token(self) -> Optional[str]:
        if self._token:
            return self._token
        if not (self.client_id and self.client_secret):
            return None
        try:
            response = requests.post(
                self.TOKEN_URL,
                auth=(self.client_id, self.client_secret),
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": USER_AGENT},
                timeout=settings.request_timeout,
            )
            response.raise_for_status()
            self._token = response.json().get("access_token")
            return self._token
        except Exception as exc:
            logger.warning("Reddit OAuth token request failed: %s", exc)
            return None

    def _from_oauth(self, subreddit: str) -> List[Dict[str, Any]]:
        token = self._oauth_token()
        if not token:
            raise PermissionError("Reddit OAuth credentials unavailable")
        response = self.session.get(
            self.OAUTH_URL.format(sub=subreddit),
            headers={"Authorization": f"bearer {token}"},
            timeout=settings.request_timeout,
        )
        if response.status_code == 401:
            self._token = None
            token = self._oauth_token()
            if token:
                response = self.session.get(
                    self.OAUTH_URL.format(sub=subreddit),
                    headers={"Authorization": f"bearer {token}"},
                    timeout=settings.request_timeout,
                )
        response.raise_for_status()
        return self._parse_children(response.json(), subreddit)

    def _parse_children(self, payload: Dict[str, Any], subreddit: str) -> List[Dict[str, Any]]:
        children = payload.get("data", {}).get("children", [])
        posts = []
        for child in children:
            data = child.get("data", {})
            permalink = data.get("permalink", "")
            posts.append(
                {
                    "id": data.get("id"),
                    "title": data.get("title", ""),
                    "selftext": data.get("selftext", ""),
                    "url": f"https://www.reddit.com{permalink}" if permalink else data.get("url", ""),
                    "link_url": data.get("url", ""),
                    "score": data.get("score", 0),
                    "num_comments": data.get("num_comments", 0),
                    "created_utc": data.get("created_utc"),
                    "author": data.get("author", ""),
                    "subreddit": data.get("subreddit", subreddit),
                    "flair": data.get("link_flair_text", ""),
                    "is_self": data.get("is_self", False),
                }
            )
        return posts

    def _from_public(self, subreddit: str) -> List[Dict[str, Any]]:
        url = self.PUBLIC_URL.format(sub=subreddit)
        response = self.session.get(url, timeout=settings.request_timeout, params={"raw_json": 1})
        if response.status_code in (403, 429):
            raise PermissionError(f"Reddit returned {response.status_code}")
        response.raise_for_status()
        return self._parse_children(response.json(), subreddit)

    def _from_rss(self, subreddit: str) -> List[Dict[str, Any]]:
        """Credential-free fallback for environments where Reddit blocks JSON."""
        if not feedparser:
            raise RuntimeError("feedparser unavailable")
        response = self.session.get(
            self.RSS_URL.format(sub=subreddit),
            headers={"Accept": "application/atom+xml,application/xml,text/xml,*/*"},
            timeout=settings.request_timeout * 2,
        )
        if response.status_code in (403, 429):
            raise PermissionError(f"Reddit RSS returned {response.status_code}")
        response.raise_for_status()
        feed = feedparser.parse(response.content)
        posts: List[Dict[str, Any]] = []
        for entry in feed.entries[:25]:
            title = clean_text(entry.get("title", ""), 400)
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue
            summary = entry.get("summary") or ""
            if not summary and entry.get("content"):
                summary = entry["content"][0].get("value", "")
            posts.append(
                {
                    "id": entry.get("id") or link,
                    "title": title,
                    "selftext": clean_text(summary, 600),
                    "url": link,
                    "link_url": link,
                    "score": 0,
                    "num_comments": 0,
                    "created_utc": entry.get("published") or entry.get("updated"),
                    "author": entry.get("author", ""),
                    "subreddit": subreddit,
                    "flair": "",
                    "is_self": False,
                    "_backend": "rss",
                }
            )
        return posts

    def _from_pullpush(self, subreddit: str) -> List[Dict[str, Any]]:
        cutoff = int((datetime.now(timezone.utc) - timedelta(hours=48)).timestamp())
        last_error: Optional[Exception] = None
        for sort_type in ("score", "created_utc"):
            for attempt in range(2):
                try:
                    response = self.session.get(
                        self.PULLPUSH_URL,
                        params={
                            "subreddit": subreddit,
                            "size": 25,
                            "sort": "desc",
                            "sort_type": sort_type,
                            "after": cutoff,
                        },
                        timeout=settings.request_timeout * 2,
                    )
                    if response.status_code == 429:
                        time.sleep(4 * (attempt + 1))
                        last_error = PermissionError("PullPush returned 429")
                        continue
                    response.raise_for_status()
                    payload = response.json()
                    posts = []
                    for data in payload.get("data", []):
                        permalink = data.get("permalink") or ""
                        if isinstance(permalink, dict):
                            permalink = permalink.get("url", "")
                        if permalink and not permalink.startswith("http"):
                            permalink = f"https://www.reddit.com{permalink}"
                        posts.append(
                            {
                                "id": data.get("id"),
                                "title": data.get("title", ""),
                                "selftext": data.get("selftext", ""),
                                "url": permalink or data.get("url", ""),
                                "link_url": data.get("url", ""),
                                "score": data.get("score", 0),
                                "num_comments": data.get("num_comments", 0),
                                "created_utc": data.get("created_utc"),
                                "author": data.get("author", ""),
                                "subreddit": data.get("subreddit", subreddit),
                                "flair": data.get("link_flair_text", ""),
                                "is_self": data.get("is_self", False),
                            }
                        )
                    if posts:
                        return posts
                except Exception as exc:
                    last_error = exc
                    break
        if last_error:
            logger.warning("PullPush fallback failed for r/%s: %s", subreddit, last_error)
        return []

    def fetch(self) -> List[Dict[str, Any]]:
        if self.is_circuit_open():
            logger.info("Reddit fetch skipped: circuit breaker open.")
            return []

        records: List[Dict[str, Any]] = []
        seen: set = set()
        public_blocked = False
        rss_blocked = False
        oauth_enabled = bool(self.client_id and self.client_secret)
        pullpush_blocked = False
        for sub in self._load_subreddits():
            name = sub["name"]
            min_score = int(sub.get("min_score", settings.reddit_min_score))
            posts: List[Dict[str, Any]] = []
            if oauth_enabled:
                try:
                    posts = self._from_oauth(name)
                except Exception as exc:
                    logger.warning("Reddit OAuth fetch failed for r/%s: %s", name, exc)
                    oauth_enabled = False
            if not posts and not oauth_enabled and not public_blocked:
                try:
                    posts = self._from_public(name)
                except PermissionError as exc:
                    logger.warning("Reddit public endpoint unavailable (%s); switching to PullPush.", exc)
                    public_blocked = True
                except Exception as exc:
                    logger.warning("Reddit public fetch failed for r/%s: %s", name, exc)
            if not posts and not oauth_enabled and not rss_blocked:
                try:
                    posts = self._from_rss(name)
                except PermissionError as exc:
                    rss_blocked = True
                    logger.warning("Reddit RSS unavailable (%s); trying PullPush.", exc)
                except Exception as exc:
                    logger.warning("Reddit RSS failed for r/%s: %s", name, exc)
            if not posts and not oauth_enabled and not rss_blocked and not pullpush_blocked:
                posts = self._from_pullpush(name)
                if not posts:
                    pullpush_blocked = True
                    logger.info("PullPush appears rate-limited; skipping remaining subreddits this run.")

            for post in posts:
                if not post.get("id") or not post.get("title"):
                    continue
                if int(post.get("score") or 0) < min_score and post.get("_backend") != "rss":
                    continue
                if post["id"] in seen:
                    continue
                seen.add(post["id"])
                text = post["title"]
                if post.get("selftext"):
                    text = f"{text} — {post['selftext'][:400]}"
                records.append(
                    make_raw_social(
                        source="reddit",
                        source_id=str(post["id"]),
                        text=text,
                        url=post.get("url", ""),
                        author=post.get("author", ""),
                        community=post.get("subreddit", name),
                        score=post.get("score", 0),
                        comments=post.get("num_comments", 0),
                        created_at=post.get("created_utc"),
                        matched_title=post.get("title", ""),
                        metadata={
                            "link_url": post.get("link_url", ""),
                            "flair": post.get("flair", ""),
                            "is_self": post.get("is_self", False),
                            "weight": sub.get("weight", 1.0),
                            "category": sub.get("category", "general"),
                        },
                    )
                )
            time.sleep(min(settings.host_delay_seconds, 1.0))

        if records:
            self.record_success()
        else:
            self.record_failure()
        logger.info("Reddit gathered %d posts", len(records))
        return records
