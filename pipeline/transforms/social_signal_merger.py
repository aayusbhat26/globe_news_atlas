"""Matches Reddit/Bluesky discussion volume to clustered stories."""
import math
import re
from typing import Any, Dict, List

STOPWORDS = {
    "about", "after", "again", "against", "amid", "among", "another", "around",
    "because", "before", "being", "between", "could", "during", "every", "first",
    "from", "have", "heads", "their", "there", "these", "they", "this", "those",
    "through", "under", "until", "update", "what", "when", "where", "which",
    "while", "with", "would", "world", "news", "latest", "breaking", "report",
    "reports", "reported", "says", "said", "video", "live", "just", "more",
}


def _tokens(text: str) -> set:
    return {
        word for word in re.findall(r"[a-z]{4,}", (text or "").lower())
        if word not in STOPWORDS
    }


class SocialSignalMerger:
    def score_cluster(self, articles: List[Dict[str, Any]], social_items: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not social_items:
            return {"social_buzz_score": 0.0, "social_thread_count": 0, "reddit_threads": 0, "bluesky_posts": 0}

        event_tokens = set()
        for article in articles[:10]:
            event_tokens |= _tokens(article.get("title", ""))
        if not event_tokens:
            return {"social_buzz_score": 0.0, "social_thread_count": 0, "reddit_threads": 0, "bluesky_posts": 0}

        buzz = 0.0
        threads = 0
        reddit_threads = 0
        bluesky_posts = 0
        seen_posts: set = set()

        for post in social_items:
            post_id = post.get("id") or post.get("source_id")
            if post_id in seen_posts:
                continue
            tokens = _tokens(post.get("text") or post.get("title") or post.get("matched_title") or "")
            overlap = event_tokens & tokens
            if len(overlap) < 2:
                continue
            if len(overlap) == 2 and sum(1 for token in overlap if len(token) >= 5) < 2:
                continue
            if len(overlap) / max(len(event_tokens), 1) < 0.08:
                continue
            seen_posts.add(post_id)
            threads += 1
            source = post.get("source")
            score = float(post.get("score") or post.get("upvotes") or 0)
            if source == "reddit":
                reddit_threads += 1
                buzz += min(math.log1p(score) / 10.0, 0.18)
            elif source == "bluesky":
                bluesky_posts += 1
                buzz += min(math.log1p(score) / 10.0, 0.12)
            else:
                buzz += min(math.log1p(score) / 12.0, 0.1)

        return {
            "social_buzz_score": round(min(buzz, 1.0), 3),
            "social_thread_count": threads,
            "reddit_threads": reddit_threads,
            "bluesky_posts": bluesky_posts,
        }

    def merge(self, articles: List[Dict[str, Any]], social_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        for article in articles:
            metrics = self.score_cluster([article], social_items)
            article.update(metrics)
        return articles
