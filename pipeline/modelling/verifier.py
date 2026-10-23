import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pipeline.modelling.verifier")

BOILERPLATE = (
    "international reports indicate",
    "cross-border verification confirmed",
    "verified reporting confirms",
    "multi-perspective analysis",
)
STOPWORDS = {
    "about", "after", "again", "against", "also", "amid", "among", "another",
    "because", "before", "being", "between", "could", "during", "every", "first",
    "from", "have", "reports", "reported", "says", "said", "that", "their", "there",
    "these", "they", "this", "those", "through", "under", "until", "which", "while",
    "with", "would", "according",
}


class Verifier:
    """Checks that a summary is grounded in the supplied reporting."""

    def verify(
        self,
        summary: str,
        articles: List[Dict[str, Any]],
        cited_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if not summary or not articles:
            return {"overall_pass": False, "reason": "Empty inputs", "grounding_ratio": 0.0}

        lowered = summary.lower()
        if len(summary.strip()) < 35:
            return {"overall_pass": False, "reason": "Summary too short", "grounding_ratio": 0.0}
        if any(phrase in lowered for phrase in BOILERPLATE):
            return {"overall_pass": False, "reason": "Boilerplate summary", "grounding_ratio": 0.0}

        valid_ids = {str(article.get("id")) for article in articles if article.get("id")}
        if cited_ids and not set(cited_ids).issubset(valid_ids):
            return {"overall_pass": False, "reason": "Invalid citation ids", "grounding_ratio": 0.0}
        if re.search(r"\[src_\d+\]", summary):
            return {"overall_pass": False, "reason": "Unexpected citation markers", "grounding_ratio": 0.0}

        source_text = " ".join(
            f"{article.get('title', '')} {article.get('snippet', '')}" for article in articles
        ).lower()
        words = []
        for word in lowered.split():
            cleaned = word.strip(".,;:\"'()[]!?—–")
            if len(cleaned) > 4 and cleaned not in STOPWORDS:
                words.append(cleaned)
        if not words:
            return {"overall_pass": False, "reason": "No checkable words", "grounding_ratio": 0.0}
        found = sum(1 for word in words if word in source_text)
        ratio = found / len(words)
        overall = ratio >= 0.3
        return {
            "overall_pass": overall,
            "grounding_ratio": round(ratio, 2),
            "reason": None if overall else "Summary not sufficiently grounded in sources",
        }
