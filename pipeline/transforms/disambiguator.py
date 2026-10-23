from typing import Dict, Any, List


class Disambiguator:
    """Resolves ambiguous place names to a location the offline gazetteer knows.

    The returned strings must match a real gazetteer entry; inventing labels
    such as "Georgia (US State)" would make geocoding fail.
    """
    RULES = [
        {
            "term": "georgia",
            "context_cues": {"tbilisi", "caucasus", "russia", "black sea", "abkhazia", "ossetia"},
            "resolved": "georgia",
            "fallback": "atlanta",
        },
        {
            "term": "washington",
            "context_cues": {"white house", "congress", "capitol", "senate", "federal", "pentagon"},
            "resolved": "washington",
            "fallback": "seattle",
        },
    ]

    def disambiguate(self, entity_name: str, surrounding_text: str) -> str:
        name_lower = (entity_name or "").lower().strip()
        text_lower = (surrounding_text or "").lower()

        for rule in self.RULES:
            if name_lower == rule["term"]:
                if any(cue in text_lower for cue in rule["context_cues"]):
                    return rule["resolved"]
                return rule["fallback"]

        return entity_name
