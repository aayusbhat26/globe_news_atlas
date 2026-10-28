"""Lightweight entity extraction for headlines and snippets.

spaCy is optional; the default lexicons are fast, deterministic and sufficient
for country/city grounding.
"""
import logging
import os
import re
import unicodedata
from typing import Any, Dict, List

from pipeline.transforms.country_codes import (
    AMBIGUOUS_COUNTRY_NAMES,
    canonical_country,
    countries_in_text,
    country_mention_supported,
)
from pipeline.transforms.world_geodata import DEMONYM_MAP, WORLD_LOCATIONS

logger = logging.getLogger("pipeline.transforms.entity_extractor")

ORGANISATION_TERMS = {
    "united nations": "United Nations",
    "un": "UN",
    "nato": "NATO",
    "european union": "European Union",
    "eu": "EU",
    "world health organization": "WHO",
    "who": "WHO",
    "international monetary fund": "IMF",
    "world bank": "World Bank",
    "red cross": "Red Cross",
    "red crescent": "Red Crescent",
    "african union": "African Union",
    "asean": "ASEAN",
    "opec": "OPEC",
    "interpol": "Interpol",
    "unicef": "UNICEF",
    "unhcr": "UNHCR",
    "world food programme": "World Food Programme",
}

_LOCATION_KEYS = sorted(
    {key for key in set(WORLD_LOCATIONS) | set(DEMONYM_MAP) if len(key) >= 4},
    key=len,
    reverse=True,
)
_LOCATION_PATTERN = re.compile(
    r"(?<![a-z])(" + "|".join(re.escape(key) for key in _LOCATION_KEYS) + r")(?![a-z])",
    re.IGNORECASE,
)
_PREPOSITION_PATTERN = re.compile(r"\b(?:in|at|near|across|from|around|outside|inside)\s+$", re.IGNORECASE)
_CAPITALISED = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}\b")
_SHORT_COUNTRY_CODES = {"US": "United States", "UK": "United Kingdom", "UAE": "United Arab Emirates", "DRC": "Democratic Republic of the Congo"}


def _ascii(value: str) -> str:
    text = value.replace("’", "'").replace("‘", "'").replace("`", "'")
    return "".join(
        char for char in unicodedata.normalize("NFKD", text) if not unicodedata.combining(char)
    )


def short_code_is_country(text: str, code: str) -> bool:
    """Return True only when a short code is used as a country, not a currency.

    The live regression was "US$100 million views": a word-boundary match on
    ``US`` read the currency prefix as the United States. Currency notations
    (``US$``, ``$US``, ``US $``) and ISO currency codes are never countries.
    """
    pattern = re.compile(rf"(?<![A-Za-z]){re.escape(code)}(?![A-Za-z])")
    for match in pattern.finditer(text or ""):
        before = (text or "")[max(0, match.start() - 3): match.start()]
        after = (text or "")[match.end(): match.end() + 3]
        if before.rstrip().endswith("$"):
            continue
        if after.lstrip().startswith("$"):
            continue
        return True
    return False


def _ambiguous_mention_allowed(key: str, text: str, headline: bool) -> bool:
    """Ambiguous country/state names need explicit place evidence in body text."""
    canonical = canonical_country(key)
    if not canonical or canonical.lower() not in AMBIGUOUS_COUNTRY_NAMES:
        return True
    if headline:
        return True
    return country_mention_supported(canonical, text)


class EntityExtractor:
    def __init__(self):
        self.nlp = None
        if os.getenv("ENABLE_SPACY", "false").lower() == "true":
            try:
                import spacy

                self.nlp = spacy.load("en_core_web_sm")
                logger.info("spaCy NER enabled")
            except Exception as exc:
                logger.info("spaCy unavailable, using lexicon extractor: %s", exc)

    def extract(self, text: str, headline: bool = False) -> Dict[str, List[str]]:
        """Extract entities from article text.

        ``headline=True`` marks the trusted headline/dateline context. Body
        text uses conservative matching so a bare surname ("Jordan") or a
        company/place homonym is not promoted to a country.
        """
        if not text:
            return {"people": [], "organizations": [], "locations": [], "countries": []}

        text = text[:5000]
        if self.nlp:
            try:
                return self._spacy_extract(text, headline)
            except Exception as exc:
                logger.debug("spaCy extraction failed, falling back: %s", exc)
        return self._lexicon_extract(text, headline)

    def _spacy_extract(self, text: str, headline: bool = False) -> Dict[str, List[str]]:
        doc = self.nlp(text)
        people = [ent.text for ent in doc.ents if ent.label_ == "PERSON"]
        orgs = [ent.text for ent in doc.ents if ent.label_ == "ORG"]
        locs = [
            ent.text for ent in doc.ents
            if ent.label_ in ("GPE", "LOC")
            and _ambiguous_mention_allowed(ent.text, text, headline)
        ]
        countries = countries_in_text(text, allow_ambiguous=headline)
        return self._dedupe(people, orgs, locs, countries)

    def _lexicon_extract(self, text: str, headline: bool = False) -> Dict[str, List[str]]:
        locations: List[str] = []
        countries: List[str] = []
        search_text = _ascii(text)

        for match in _LOCATION_PATTERN.finditer(search_text):
            key = match.group(1).lower()
            if not _ambiguous_mention_allowed(key, search_text, headline):
                continue
            if key in DEMONYM_MAP:
                target = DEMONYM_MAP[key]
                canonical = canonical_country(target) or target
                if canonical and canonical not in countries:
                    countries.append(canonical)
                continue
            canonical = canonical_country(key)
            if canonical:
                if canonical not in countries:
                    countries.append(canonical)
                location_name = canonical
            else:
                location_name = match.group(1)
            if location_name.lower() not in {loc.lower() for loc in locations}:
                locations.append(location_name)

        for code, name in _SHORT_COUNTRY_CODES.items():
            if short_code_is_country(search_text, code):
                if name not in countries:
                    countries.append(name)

        # Drop country names from the city list so geocoding prefers specific
        # places when both appear.
        specific = [loc for loc in locations if loc.lower() not in {c.lower() for c in countries}]
        ordered = self._order_by_preposition(search_text, specific) + [c for c in countries if c.lower() not in {loc.lower() for loc in specific}]

        people = [
            name for name in _CAPITALISED.findall(text)
            if not any(name.lower() == loc.lower() or name.lower() in loc.lower() for loc in ordered)
        ][:5]
        organisations = [
            name for name in _CAPITALISED.findall(text)
            if any(term in name.lower() for term in ("corp", "inc", "university", "ministry", "agency", "party", "bank", "council", "committee"))
        ][:5]
        for term, label in ORGANISATION_TERMS.items():
            if re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE) and label not in organisations:
                organisations.append(label)

        return self._dedupe(
            people,
            organisations,
            ordered,
            countries_in_text(text, allow_ambiguous=headline) or countries,
        )

    def _order_by_preposition(self, text: str, locations: List[str]) -> List[str]:
        prepared, other = [], []
        for location in locations:
            pattern = re.compile(r"(?<![a-z])" + re.escape(location.lower()) + r"(?![a-z])")
            position = None
            match = pattern.search(text.lower())
            if match:
                position = match.start()
            before = text.lower()[max(0, (position or 0) - 14): position] if position is not None else ""
            if _PREPOSITION_PATTERN.search(before):
                prepared.append(location)
            else:
                other.append(location)
        return prepared + other

    @staticmethod
    def _dedupe(people: List[str], orgs: List[str], locations: List[str], countries: List[str]) -> Dict[str, List[str]]:
        def unique(values: List[str], limit: int = 8) -> List[str]:
            seen = set()
            result = []
            for value in values:
                cleaned = (value or "").strip()
                key = cleaned.lower()
                if not cleaned or key in seen:
                    continue
                seen.add(key)
                result.append(cleaned)
                if len(result) >= limit:
                    break
            return result

        return {
            "people": unique(people, 5),
            "organizations": unique(orgs, 5),
            "locations": unique(locations, 8),
            "countries": unique(countries, 6),
        }
