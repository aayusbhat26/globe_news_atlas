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
_NUMBER_RE = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?(?![\w])")
_PROPER_RE = re.compile(r"\b[A-Z][A-Za-z'’-]{2,}(?:\s+[A-Z][A-Za-z'’-]{2,}){0,3}\b")
_COMMON_ENTITIES = {
    "the", "this", "that", "these", "those", "there", "their", "they",
    "a", "an", "in", "on", "at", "by", "for", "from", "with", "without",
    "after", "before", "during", "amid", "and", "but", "or", "as", "of",
    "reports", "report", "according", "officials", "government", "police",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
    "sunday", "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
}
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

        # Numeric grounding: a summary may not introduce counts, dates or
        # casualty figures that are absent from the supplied reporting.
        source_numbers = {
            value.replace(",", "") for value in _NUMBER_RE.findall(source_text)
        }
        summary_numbers = {
            value.replace(",", "") for value in _NUMBER_RE.findall(lowered)
        }
        missing_numbers = sorted(summary_numbers - source_numbers)
        if missing_numbers:
            return {
                "overall_pass": False,
                "reason": f"Unsupported numeric claims: {', '.join(missing_numbers[:4])}",
                "grounding_ratio": 0.0,
                "numbers_ratio": 0.0,
            }

        # Entity grounding: fabricated names/places are rejected even when
        # enough ordinary words overlap.
        source_lower = source_text.lower()
        proper = []
        for match in _PROPER_RE.finditer(summary):
            entity = " ".join(match.group(0).split())
            if entity.lower() in _COMMON_ENTITIES or len(entity) < 3:
                continue
            proper.append(entity)
        if proper:
            found_entities = sum(1 for entity in proper if entity.lower() in source_lower)
            entity_ratio = found_entities / len(proper)
            if entity_ratio < 0.5:
                return {
                    "overall_pass": False,
                    "reason": "Summary names entities not present in the supplied reporting",
                    "grounding_ratio": 0.0,
                    "entity_ratio": round(entity_ratio, 2),
                }
        else:
            entity_ratio = 1.0

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
            "entity_ratio": round(entity_ratio, 2),
            "reason": None if overall else "Summary not sufficiently grounded in sources",
        }
