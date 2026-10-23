import logging
import re
from typing import Any, Dict

logger = logging.getLogger("pipeline.modelling.classifier")

CATEGORY_KEYWORDS = {
    "conflict": {
        "war": 3, "airstrike": 3, "missile": 3, "drone": 2, "shelling": 3,
        "offensive": 2, "militants": 2, "insurgent": 2, "troops": 2, "ceasefire": 2,
        "clashes": 3, "battle": 2, "armed": 1, "gunmen": 3, "militia": 2,
        "conflict": 3, "strikes": 3, "strike": 2, "attack": 2, "military": 2,
        "naval": 2, "warship": 2, "jets": 2, "missiles": 3, "paramilitary": 3,
        "hitman": 2, "bombing": 3, "bomb": 2, "houthi": 2,
    },
    "politics": {
        "election": 3, "parliament": 2, "president": 1, "minister": 1, "treaty": 2,
        "diplomat": 2, "summit": 2, "vote": 2, "coalition": 2, "sanctions": 2,
        "government": 1, "policy": 1, "referendum": 3, "campaign": 1,
        "runoff": 3, "diplomacy": 2, "envoy": 2, "court": 1,
        "supreme court": 3, "voter": 2, "voters": 2, "citizenship": 2,
        "disqualify": 1, "aligned": 1,
    },
    "economy": {
        "inflation": 3, "trade": 2, "tariff": 3, "central bank": 3, "deficit": 2,
        "gdp": 3, "market": 1, "currency": 2, "oil price": 2, "investment": 1,
        "exports": 2, "imports": 2, "economy": 3, "economic": 2, "oil": 2,
        "stocks": 2, "shares": 1, "debt": 2, "budget": 1, "inventory": 1,
        "supply": 1, "growth": 1, "jobs": 1, "unemployment": 2, "crypto": 2,
        "bitcoin": 2, "bank": 1, "earnings": 1, "markets": 2, "stock": 2,
        "price": 1, "prices": 1, "gold rate": 3, "gold price": 3,
        "trade deficit": 3, "tariffs": 3, "gasfield": 3, "gas field": 3,
        "costs": 1,
    },
    "disaster": {
        "earthquake": 4, "flood": 3, "hurricane": 3, "wildfire": 3, "cyclone": 3,
        "tsunami": 3, "landslide": 3, "drought": 2, "volcano": 3, "storm": 2,
        "quake": 3, "eruption": 3, "evacuation": 2, "rainfall": 2,
        "heavy rain": 3, "flood watch": 3, "heatwave": 3, "wildfires": 3,
        "landslides": 3,
    },
    "protest": {
        "protest": 4, "rally": 2, "demonstration": 3, "unrest": 3, "strike": 1,
        "march": 1, "riot": 3, "riots": 3, "protester": 4, "protesters": 4,
        "protests": 4,
    },
    "science": {
        "quantum": 3, "satellite": 2, "nasa": 3, "esa": 2, "telescope": 2,
        "research": 1, "study": 1, "spacecraft": 3, "space": 1, "scientist": 2,
        "species": 1, "astronomy": 3,
    },
    "health": {
        "outbreak": 3, "virus": 2, "vaccine": 2, "hospital": 1, "disease": 2,
        "epidemic": 3, "pandemic": 3, "ebola": 4, "measles": 3,
        "cholera": 3, "cancer": 2, "medicine": 1, "patients": 1, "health": 1,
        "outbreaks": 3, "hospitals": 1, "disease": 2,
    },
    "environment": {
        "climate": 2, "emissions": 2, "renewable": 2, "deforestation": 3,
        "biodiversity": 2, "carbon": 2, "pollution": 2, "conservation": 2,
        "wildlife": 2, "warming": 2, "ecosystem": 2,
    },
    "technology": {
        "artificial intelligence": 4, "semiconductor": 3, "chip": 2, "cyber": 3,
        "hacking": 3, "software": 2, "startup": 1, "robot": 2, "smartphone": 2,
        "algorithm": 2, "data center": 3, "cloud": 1, "openai": 3, "google": 1,
        "apple": 1, "microsoft": 1, "meta": 1, "tiktok": 2, "spacex": 2,
        "ai": 2, "tech": 2, "internet": 1, "platform": 1, "starlink": 3,
        "inteligencia artificial": 4, "ia": 2, "social media": 1,
    },
    "sports": {
        "world series": 4, "super bowl": 4, "world cup": 4, "champions league": 4,
        "premier league": 4, "olympic": 3, "playoff": 3, "tournament": 3,
        "championship": 3, "baseball": 3, "cricket": 3, "football": 2,
        "soccer": 2, "basketball": 3, "tennis": 3, "golf": 2, "formula one": 4,
        "alcs": 4, "nlcs": 4, "mlb": 3, "nba": 3, "nfl": 3, "nhl": 3,
        "fifa": 3, "uefa": 3, "ipl": 3, "t20": 4, "odi": 4, "vs": 1,
        "test match": 3, "match": 1, "game": 1, "medal": 2,
        "athlete": 2, "coach": 1, "wicket": 3, "innings": 3, "goal": 1,
    },
    "other": {},
}

BREAKING_TERMS = ("breaking", "live", "unfolding", "developing", "just in")
VALID_CATEGORIES = set(CATEGORY_KEYWORDS)

# Word boundaries matter here: "skilled" is not "killed", "deadline" is not
# "dead", and "executive" is not an execution.
CASUALTY_PATTERN = re.compile(
    r"(?<![a-z])(?:kill(?:s|ed|ing)?|dead|deaths?|fatalit(?:y|ies)|casualt(?:y|ies)|"
    r"wounded|massacre[ds]?|execut(?:e|ed|es|ion|ions)|behead(?:ed|ing|s)?|"
    r"decapitat(?:e|ed|es|ion|ions)?|injur(?:ed|ies|y)|bodies|"
    r"death\s+sentence|death\s+row|capital\s+punishment)(?![a-z])",
    re.IGNORECASE,
)
DISTRESS_PATTERN = re.compile(
    r"(?<![a-z])(?:graphic|disturbing|gruesome)(?![a-z])",
    re.IGNORECASE,
)
SEVERITY_PATTERN = re.compile(
    r"(?<![a-z])(?:emergency|evacuat\w*|catastroph\w*|devastat\w*|widespread|"
    r"outbreak\w*|invasion|massacre\w*|explosion\w*|collapse[ds]?|meltdown|fatal\w*)(?![a-z])",
    re.IGNORECASE,
)
# "Kill the bill" and "execute a plan" are political/planning language, not
# evidence of casualties.
_NON_CASUALTY_PHRASES = re.compile(
    r"(?<![a-z])(?:kill(?:ed|s|ing)?|execut(?:e|ed|es|ing))\s+"
    r"(?:the\s+)?(?:bill|plan|deal|proposal|measure|amendment|legislation|project|strategy|contract|order)(?![a-z])",
    re.IGNORECASE,
)


class Classifier:
    def classify(
        self,
        title: str,
        snippet: str = "",
        pre_assigned_cat: str = None,
        source_count: int = 1,
    ) -> Dict[str, Any]:
        title_text = title.lower()
        body_text = snippet.lower()

        if pre_assigned_cat in VALID_CATEGORIES:
            category = pre_assigned_cat
        else:
            def keyword_score(text: str) -> Dict[str, int]:
                result: Dict[str, int] = {}
                for category_name, keywords in CATEGORY_KEYWORDS.items():
                    score = sum(
                        weight
                        for keyword, weight in keywords.items()
                        if re.search(rf"(?<![a-z]){re.escape(keyword)}(?![a-z])", text)
                    )
                    if score:
                        result[category_name] = score
                return result

            title_scores = keyword_score(title_text)
            body_scores = keyword_score(body_text)
            scores: Dict[str, int] = {
                category_name: title_scores.get(category_name, 0) * 2
                + body_scores.get(category_name, 0)
                for category_name in CATEGORY_KEYWORDS
            }
            scores = {name: score for name, score in scores.items() if score}
            category = max(scores, key=scores.get) if scores else "other"

        combined = f"{title_text} {body_text}"
        casualty_text = _NON_CASUALTY_PHRASES.sub(" ", combined)
        casualty = bool(CASUALTY_PATTERN.search(casualty_text))
        content_warning = (
            "Distressing content: reports mention casualties or graphic details."
            if casualty or DISTRESS_PATTERN.search(combined)
            else None
        )

        severe = casualty or bool(SEVERITY_PATTERN.search(combined))
        if casualty and category != "sports":
            severity = "high"
        elif category in {"conflict", "disaster"} and (severe or (source_count >= 8 and category == "conflict")):
            severity = "high"
        elif category in {"conflict", "disaster", "protest", "health"} or severe:
            severity = "medium"
        else:
            severity = "low"

        status = "developing" if any(term in combined for term in BREAKING_TERMS) else "ongoing"

        return {
            "category": category,
            "severity": severity,
            "status": status,
            "content_warning": content_warning,
        }
