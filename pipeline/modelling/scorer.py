from typing import Dict, Any


class Scorer:
    """Importance and confidence from observed coverage, not synthetic priors."""

    def score_event(
        self,
        outlet_count: int,
        social_buzz: float,
        severity: str,
        source_count: int = 1,
        has_official_source: bool = False,
        hours_since_update: float = 0.0,
    ) -> Dict[str, Any]:
        outlet_factor = min(outlet_count / 12.0, 0.5)
        social_factor = min(max(social_buzz, 0.0) * 0.2, 0.2)
        severity_factor = {"high": 0.2, "medium": 0.1, "low": 0.03}.get(severity, 0.05)
        source_factor = min(source_count / 40.0, 0.05)
        recency_factor = 0.05 if hours_since_update <= 1 else (0.03 if hours_since_update <= 24 else 0.0)
        importance = round(min(outlet_factor + social_factor + severity_factor + source_factor + recency_factor, 1.0), 3)

        is_single_source = outlet_count <= 1
        confidence = 0.42 + min(outlet_count, 10) * 0.04
        if has_official_source:
            confidence += 0.08
        if is_single_source:
            confidence = min(confidence, 0.55)
        confidence = round(min(confidence, 0.95), 2)

        return {
            "importance": importance,
            "confidence": confidence,
            "is_single_source": is_single_source,
        }
