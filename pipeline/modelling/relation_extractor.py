"""Builds bilateral relation arcs from real event co-occurrence.

Arcs are evidence-backed: every arc lists the events that mentioned both
countries. No arc is emitted from a single keyword in an unrelated headline.
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

from pipeline.config import settings
from pipeline.ingestion.schema import stable_id
from pipeline.transforms.country_codes import country_iso2
from pipeline.transforms.world_geodata import WORLD_LOCATIONS

logger = logging.getLogger("pipeline.modelling.relation_extractor")

CONFLICT_TERMS = ("strike", "war", "missile", "military", "attack", "drone", "troops", "clashes", "offensive")
SANCTIONS_TERMS = ("sanction", "ban", "expel", "freeze", "embargo")
AID_TERMS = ("aid", "relief", "humanitarian", "rescue", "food", "shelter")
TRADE_TERMS = ("trade", "tariff", "export", "import", "deal", "oil", "gas", "investment", "market")
TALKS_TERMS = ("summit", "meeting", "talk", "diplomat", "accord", "agreement", "ceasefire", "negotiat")


def _centroid(country: str) -> Optional[Tuple[float, float]]:
    return WORLD_LOCATIONS.get(country.lower())


class RelationExtractor:
    def __init__(self, country_centroids: Optional[Dict[str, Tuple[float, float]]] = None):
        self.centroids = country_centroids or WORLD_LOCATIONS

    def _label(self, country: str) -> str:
        return country_iso2(country) or country[:3].upper()

    def _relation_type(self, event: Dict[str, Any]) -> str:
        title = (event.get("title") or "").lower()
        category = event.get("category") or ""
        if any(term in title for term in SANCTIONS_TERMS):
            return "sanctions"
        if any(term in title for term in AID_TERMS):
            return "aid"
        if category == "conflict" or any(term in title for term in CONFLICT_TERMS):
            return "military"
        if category == "economy" or any(term in title for term in TRADE_TERMS):
            return "trade"
        if any(term in title for term in TALKS_TERMS):
            return "talks"
        return "talks"

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
                pair = sorted([self._label(primary), self._label(other)])
                relation_type = self._relation_type(event)
                key = (pair[0], pair[1], relation_type)
                title = (event.get("title") or "").strip()
                impact = float(event.get("importance") or 0.0)
                entry = grouped.get(key)
                if entry is None:
                    grouped[key] = {
                        "id": stable_id("arc", pair[0], pair[1], relation_type)[:20],
                        "a": pair[0],
                        "b": pair[1],
                        "countries": [primary, other],
                        "ty": relation_type,
                        "dir": "a_to_b" if relation_type == "aid" else "bidirectional",
                        "stg": "active",
                        "imp": impact,
                        "t": title[:90],
                        "n": 1,
                        "event_ids": [event.get("id")],
                    }
                else:
                    entry["n"] += 1
                    if event.get("id") and len(entry["event_ids"]) < 25:
                        entry["event_ids"].append(event.get("id"))
                    if impact > entry["imp"]:
                        entry["imp"] = impact
                        entry["t"] = title[:90]

        arcs = []
        for entry in grouped.values():
            a_geo = self.centroids.get(entry["countries"][0].lower())
            b_geo = self.centroids.get(entry["countries"][1].lower())
            if not a_geo or not b_geo:
                continue
            entry["a_lat"], entry["a_lng"] = round(a_geo[0], 4), round(a_geo[1], 4)
            entry["b_lat"], entry["b_lng"] = round(b_geo[0], 4), round(b_geo[1], 4)
            entry["imp"] = round(min(0.25 + entry["n"] * 0.06 + entry["imp"] * 0.35, 1.0), 3)
            arcs.append(entry)

        arcs.sort(key=lambda arc: (arc["n"], arc["imp"]), reverse=True)
        arcs = arcs[: settings.max_arcs]
        logger.info("Extracted %d relation arcs from %d events", len(arcs), len(events))
        return arcs
