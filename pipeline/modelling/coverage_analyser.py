"""Coverage spectrum from de-duplicated, genuinely independent outlets.

Coded event records (GDELT) and official feeds (USGS, ReliefWeb, ACLED) are
tracked as evidence but never counted as left/centre/right outlets: they have
no editorial alignment and would otherwise distort the spectrum.
"""
import math
from typing import Any, Dict, List


OFFICIAL_SOURCES = {"usgs", "acled", "reliefweb"}
CODED_SOURCES = {"gdelt_events"}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "nat", "<na>"} else text


def outlet_key(article: Dict[str, Any]) -> str:
    return (
        _text(article.get("outlet_id"))
        or _text(article.get("domain"))
        or _text(article.get("outlet"))
        or _text(article.get("source_id"))
        or ""
    ).strip().lower()


def representative_articles(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One article per syndication group, preferring real outlet reports."""
    groups: Dict[str, Dict[str, Any]] = {}
    for index, article in enumerate(articles):
        group = (
            _text(article.get("duplicate_group"))
            or _text(article.get("id"))
            or _text(article.get("canonical_url"))
            or outlet_key(article)
            or f"article_{index}"
        )
        current = groups.get(group)
        if current is None:
            groups[group] = article
            continue
        current_coded = _text(current.get("source")) in CODED_SOURCES
        candidate_coded = _text(article.get("source")) in CODED_SOURCES
        if current_coded and not candidate_coded:
            groups[group] = article
        elif current_coded == candidate_coded and (
            _text(article.get("published_at")) < _text(current.get("published_at"))
        ):
            groups[group] = article
    return list(groups.values())


class CoverageAnalyser:
    CAMP_MAPPING = {
        "left": "left",
        "left_center": "left",
        "centre": "centre",
        "center": "centre",
        "right_center": "right",
        "right": "right",
        "unrated": "unrated",
    }

    def analyse(self, articles: List[Dict[str, Any]]) -> Dict[str, Any]:
        reps = representative_articles(articles)
        spectrum = {"left": 0, "centre": 0, "right": 0, "unrated": 0}
        seen_outlets = set()
        official = False

        for article in reps:
            source = _text(article.get("source"))
            if source in OFFICIAL_SOURCES:
                official = True
            # Event feeds are evidence, not editorial outlets.
            if source in CODED_SOURCES or source in OFFICIAL_SOURCES:
                continue
            key = outlet_key(article)
            if not key or key in seen_outlets:
                continue
            seen_outlets.add(key)
            alignment = self.CAMP_MAPPING.get(
                _text(article.get("alignment")).lower() or "unrated",
                "unrated",
            )
            spectrum[alignment] += 1

        rated = spectrum["left"] + spectrum["centre"] + spectrum["right"]
        has_gap = rated >= 2 and (
            (spectrum["left"] >= 2 and spectrum["right"] == 0)
            or (spectrum["right"] >= 2 and spectrum["left"] == 0)
        )

        return {
            "spectrum": spectrum,
            "distinct_outlets": len(seen_outlets),
            "has_coverage_gap": has_gap,
            "has_official_source": official,
            "source_count": len(reps),
        }

    # Backwards-compatible alias
    def analyze(self, articles: List[Dict[str, Any]]) -> Dict[str, Any]:
        return self.analyse(articles)
