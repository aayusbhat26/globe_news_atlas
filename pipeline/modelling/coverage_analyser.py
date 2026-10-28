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


def is_google_news(article: Dict[str, Any]) -> bool:
    metadata = article.get("source_metadata") if isinstance(article.get("source_metadata"), dict) else {}
    return bool(
        article.get("via_google_news")
        or article.get("source") == "google_news"
        or metadata.get("via_google_news")
    )


def representative_articles(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One article per syndication group, preferring direct publisher links."""
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
        elif (
            current_coded == candidate_coded
            and is_google_news(current)
            and not is_google_news(article)
        ):
            # A direct SCMP/Prothom Alo link is preferable to its Google News
            # redirect for the same story.
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
        distinct = len(seen_outlets)
        rated_share = (rated / distinct) if distinct else 0.0
        dominant = max(spectrum["left"], spectrum["right"])
        dominant_share = (dominant / rated) if rated else 0.0
        one_sided = (
            rated >= 3
            and rated_share >= 0.5
            and dominant >= 2
            and min(spectrum["left"], spectrum["right"]) == 0
            and dominant_share >= 0.6
        )
        # Keep the backend's boolean meaning coherent: a gap exists only when
        # enough rated outlets exist to judge it and one wing dominates the
        # rated coverage. 21 unrated outlets must not turn 2 left/1 centre into
        # a "one-sided" story.
        has_gap = one_sided

        if has_gap:
            gap_side = "left" if spectrum["left"] > spectrum["right"] else "right"
            gap_reason = (
                f"{gap_side}-rated outlets only ({spectrum[gap_side]} of "
                f"{rated} rated outlets); no opposite-side coverage."
            )
        elif distinct and rated_share < 0.5:
            gap_reason = (
                f"Insufficient rated coverage to judge a gap "
                f"({rated}/{distinct} distinct outlets rated)."
            )
        elif rated < 3:
            gap_reason = f"Not enough rated outlets to judge a gap ({rated} rated)."
        elif dominant_share < 0.6:
            gap_reason = "Rated coverage includes substantial centre reporting; no one-sided gap."
        else:
            gap_reason = "Coverage includes both left- and right-rated outlets."

        return {
            "spectrum": spectrum,
            "distinct_outlets": distinct,
            "rated_outlets": rated,
            "rated_share": round(rated_share, 2),
            "has_coverage_gap": has_gap,
            "coverage_gap_reason": gap_reason,
            "has_official_source": official,
            "source_count": len(reps),
        }

    # Backwards-compatible alias
    def analyze(self, articles: List[Dict[str, Any]]) -> Dict[str, Any]:
        return self.analyse(articles)
