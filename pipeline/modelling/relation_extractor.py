"""Builds bilateral relation arcs from real event co-occurrence.

Arcs are evidence-backed: every arc lists the events that mentioned both
countries. No arc is emitted from a single keyword in an unrelated headline.
Endpoint labels, country names and coordinates are derived from one ordered
pair so ``a`` always owns ``a_lat``/``a_lng``.
"""
import logging
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from pipeline.config import settings
from pipeline.ingestion.schema import stable_id
from pipeline.transforms.country_codes import country_iso2
from pipeline.transforms.world_geodata import WORLD_LOCATIONS

logger = logging.getLogger("pipeline.modelling.relation_extractor")

CONFLICT_TERMS = ("strike", "war", "missile", "military", "attack", "drone", "troop", "clash", "offensive")
SANCTIONS_TERMS = ("sanction", "ban", "expel", "freeze", "embargo")
AID_TERMS = ("aid", "relief", "humanitarian", "rescue", "food", "shelter")
TRADE_TERMS = ("trade", "tariff", "export", "import", "deal", "oil", "gas", "investment", "market")
TALKS_TERMS = ("summit", "meeting", "talk", "diplomat", "accord", "agreement", "ceasefire", "negotiat")

# Irregular inflections that a simple suffix check would miss.
_IRREGULAR = {
    "ban": {"banned", "banning"},
    "freeze": {"froze", "frozen"},
    "expel": {"expelled", "expelling"},
    "strike": {"struck", "strikes", "striking"},
    "deal": {"dealt", "deals"},
    "war": {"wars"},
}

_SUPPORTED_CATEGORIES = {
    "sanctions": {"politics", "economy", "conflict"},
    "aid": {"disaster", "humanitarian", "politics", "conflict", "health"},
    "military": {"conflict", "politics"},
    "trade": {"economy", "politics"},
    "talks": {"politics", "economy", "conflict"},
}


def _words(title: str) -> List[str]:
    return re.findall(r"[a-z]+", (title or "").lower())


def _term_present(words: List[str], term: str) -> bool:
    """Morphological word-boundary match: "ban" never matches "Bank"/"said"."""
    base = term.lower()
    variants = {
        base,
        base + "s",
        base + "es",
        base + "ed",
        base + "ing",
        base + "d",
        base + "ment",
        base + "ments",
        base + "ion",
        base + "ions",
        base + "ic",
        base + "ics",
    }
    variants.update(_IRREGULAR.get(base, set()))
    for word in words:
        if word in variants:
            return True
        # "negotiat" is a deliberate stem for negotiate/negotiation.
        if base == "negotiat" and word.startswith(base):
            return True
    return False


def _centroid(country: str) -> Optional[Tuple[float, float]]:
    return WORLD_LOCATIONS.get(country.lower())


class RelationExtractor:
    def __init__(self, country_centroids: Optional[Dict[str, Tuple[float, float]]] = None):
        self.centroids = country_centroids or WORLD_LOCATIONS

    def _label(self, country: str) -> str:
        return country_iso2(country) or country[:3].upper()

    def _relation_type(self, event: Dict[str, Any]) -> str:
        title = (event.get("title") or "").lower()
        words = _words(title)
        category = (event.get("category") or "").strip().lower()

        def supported(kind: str) -> bool:
            return category in _SUPPORTED_CATEGORIES[kind]

        if supported("sanctions") and any(_term_present(words, term) for term in SANCTIONS_TERMS):
            return "sanctions"
        if supported("aid") and any(_term_present(words, term) for term in AID_TERMS):
            return "aid"
        if supported("military") and any(_term_present(words, term) for term in CONFLICT_TERMS):
            return "military"
        if supported("trade") and any(_term_present(words, term) for term in TRADE_TERMS):
            return "trade"
        if supported("talks") and any(_term_present(words, term) for term in TALKS_TERMS):
            return "talks"
        # No supporting category/keyword: stay neutral rather than guessing
        # "talks" from an incidental word.
        return "neutral"

    def _ordered_pair(
        self, primary: str, other: str
    ) -> Tuple[str, str, str, str]:
        """Return (a_label, b_label, a_country, b_country) from one ordering."""
        primary_label, other_label = self._label(primary), self._label(other)
        if (primary_label, primary.lower()) <= (other_label, other.lower()):
            return primary_label, other_label, primary, other
        return other_label, primary_label, other, primary

    def extract_relations(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        grouped: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

        for event in events:
            countries = []
            for country in event.get("countries") or []:
                if country and country not in countries and self.centroids.get(country.lower()):
                    countries.append(country)
            if len(countries) < 2:
                continue

            primary = countries[0]
            for other in countries[1:3]:
                a_label, b_label, a_country, b_country = self._ordered_pair(primary, other)
                relation_type = self._relation_type(event)
                key = (a_label, b_label, relation_type)
                title = (event.get("title") or "").strip()
                impact = float(event.get("importance") or 0.0)
                entry = grouped.get(key)
                aid_direction = ""
                if relation_type == "aid":
                    aid_direction = "a_to_b" if primary == a_country else "b_to_a"
                if entry is None:
                    grouped[key] = {
                        "id": stable_id("arc", a_label, b_label, relation_type)[:20],
                        "a": a_label,
                        "b": b_label,
                        "countries": [a_country, b_country],
                        "ty": relation_type,
                        "dir": aid_direction or "bidirectional",
                        "stg": "active",
                        "imp": impact,
                        "t": title[:90],
                        "n": 1,
                        "event_ids": [event.get("id")],
                        "_aid_directions": Counter({aid_direction: 1}) if aid_direction else Counter(),
                    }
                else:
                    entry["n"] += 1
                    if event.get("id") and len(entry["event_ids"]) < 25:
                        entry["event_ids"].append(event.get("id"))
                    if aid_direction:
                        entry["_aid_directions"][aid_direction] += 1
                    if impact > entry["imp"]:
                        entry["imp"] = impact
                        entry["t"] = title[:90]

        arcs = []
        for entry in grouped.values():
            a_country, b_country = entry["countries"]
            a_geo = self.centroids.get(a_country.lower())
            b_geo = self.centroids.get(b_country.lower())
            if not a_geo or not b_geo:
                continue
            # Endpoint/ISO consistency: never pair an ISO label with another
            # country's centroid.
            if country_iso2(a_country) != entry["a"] or country_iso2(b_country) != entry["b"]:
                logger.warning("Dropping inconsistent relation arc %s", entry.get("id"))
                continue
            entry["a_lat"], entry["a_lng"] = round(a_geo[0], 4), round(a_geo[1], 4)
            entry["b_lat"], entry["b_lng"] = round(b_geo[0], 4), round(b_geo[1], 4)
            if entry["ty"] == "aid" and entry["_aid_directions"]:
                directions = entry["_aid_directions"]
                top = directions.most_common()
                if len(top) == 1 or top[0][1] > top[1][1]:
                    entry["dir"] = top[0][0]
                else:
                    entry["dir"] = "bidirectional"
            entry.pop("_aid_directions", None)
            entry["imp"] = round(min(0.25 + entry["n"] * 0.06 + entry["imp"] * 0.35, 1.0), 3)
            arcs.append(entry)

        arcs.sort(key=lambda arc: (arc["n"], arc["imp"]), reverse=True)
        arcs = arcs[: settings.max_arcs]
        logger.info("Extracted %d relation arcs from %d events", len(arcs), len(events))
        return arcs
