"""Resolve ambiguous place names without guessing.

The offline gazetteer cannot tell Georgia the country from Georgia the US
state, Washington the capital from Washington the state, or Jordan the country
from Jordan a person's surname. Returning a wrong place is worse than
returning nothing, so unresolved names yield an empty string and callers are
expected to leave the article unlocated.
"""
from typing import Dict, Optional


class Disambiguator:
    """Resolves ambiguous place names to a gazetteer entry when evidence exists."""

    RULES = [
        {
            "term": "georgia",
            "country_cues": {
                "tbilisi", "caucasus", "abkhazia", "ossetia", "south ossetia",
                "georgian government", "georgian parliament", "georgian army",
                "black sea",
            },
            "country_value": "georgia",
            "us_cues": {
                "atlanta", "savannah", "state of georgia", "georgia state",
                "u.s.", "united states", "gop", "governor brian kemp",
            },
            "us_value": "atlanta",
        },
        {
            "term": "washington",
            "country_cues": {"white house", "congress", "capitol", "senate", "federal", "pentagon", "d.c.", "washington, dc"},
            "country_value": "washington",
            "us_cues": {"washington state", "seattle", "olympia", "spokane", "tacoma"},
            "us_value": "seattle",
            # "Washington" on its own in a headline almost always means the
            # US capital, never a random city; keep that default explicit.
            "default_value": "washington",
        },
        {
            "term": "jordan",
            "country_cues": {
                "amman", "kingdom of jordan", "jordanian", "jordanians",
                "king abdullah", "jordan border", "jordanian army",
            },
            "country_value": "jordan",
            "person_cues": {
                "michael b jordan", "michael jordan", "jordan peterson",
                "jordan belfort", "jordan peele", "jordan spieth",
            },
        },
    ]

    def _rule_for(self, name: str) -> Optional[Dict[str, object]]:
        cleaned = (name or "").strip().lower()
        for rule in self.RULES:
            if cleaned == rule["term"]:
                return rule
        return None

    def is_ambiguous(self, entity_name: str) -> bool:
        return self._rule_for(entity_name) is not None

    def disambiguate(self, entity_name: str, surrounding_text: str) -> str:
        """Return a gazetteer key, or "" when the evidence is insufficient."""
        rule = self._rule_for(entity_name)
        if rule is None:
            return entity_name

        text_lower = (surrounding_text or "").lower()
        if any(cue in text_lower for cue in rule.get("person_cues", set())):
            return ""
        if any(cue in text_lower for cue in rule.get("country_cues", set())):
            return str(rule["country_value"])
        if any(cue in text_lower for cue in rule.get("us_cues", set())):
            return str(rule["us_value"])
        return str(rule.get("default_value") or "")
