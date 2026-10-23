import re
import unicodedata
from typing import Any, Dict, List, Set

import numpy as np
from sklearn.cluster import AgglomerativeClustering

from pipeline.transforms.country_codes import countries_in_text

# Function words across the languages we ingest. Without these, embeddings
# happily group unrelated articles that merely share a language.
STOPWORDS = {
    "about", "after", "again", "against", "along", "also", "amid", "among",
    "another", "around", "because", "before", "behind", "being", "between",
    "breaking", "brings", "could", "during", "every", "first", "following",
    "from", "have", "having", "into", "latest", "live", "might", "more",
    "most", "much", "must", "news", "other", "over", "report", "reports",
    "said", "says", "should", "since", "some", "still", "such", "than",
    "that", "their", "there", "these", "they", "this", "those", "through",
    "today", "under", "update", "very", "what", "when", "where", "which",
    "while", "will", "with", "world", "would", "years", "yesterday",
    "america", "americas", "latina", "latin", "latino", "global",
    "international", "regional", "national",
    "para", "como", "pero", "esta", "este", "estos", "estas", "sobre",
    "entre", "desde", "hasta", "contra", "segun", "tras", "tambien",
    "porque", "cuando", "donde", "mientras", "durante", "mediante", "mas",
    "menos", "poco", "mucho", "mucha", "muchos", "muchas", "todo", "toda",
    "todos", "todas", "otro", "otra", "otros", "otras", "mismo", "misma",
    "gran", "grande", "nuevo", "nueva", "primer", "primera", "ultimo",
    "ultima", "puede", "pueden", "sera", "seran", "solo", "asi", "hoy",
    "ayer", "manana", "ano", "anos", "dia", "dias", "semana", "mes",
    "veces", "mundo", "noticias",
    "pour", "dans", "avec", "sur", "sous", "vers", "chez", "avant",
    "apres", "depuis", "pendant", "selon", "aussi", "comme", "plus",
    "moins", "tres", "tout", "tous", "toute", "toutes", "autre", "autres",
    "meme", "memes", "nouveau", "nouvelle", "premier", "premiere",
    "dernier", "derniere", "peut", "peuvent", "sera", "seront", "sont",
    "etait", "etaient", "avoir", "etre", "fait", "faire", "dit", "monde",
    "actualites", "aujourd", "hier", "demain", "annee", "annees", "jour",
    "jours", "semaine", "mois", "fois",
    "sem", "sob", "ate", "segundo", "quando", "onde", "enquanto", "muito",
    "muita", "muitos", "muitas", "novo", "nova", "primeiro", "primeira",
    "ultimo", "ultima", "pode", "podem", "foram", "mundo", "noticias",
    "hoje", "ontem", "amanha", "ano", "anos", "dia", "dias", "semana",
    "vez", "vezes",
    "nach", "uber", "unter", "zwischen", "gegen", "wahrend", "wegen",
    "trotz", "auch", "aber", "oder", "sowie", "nicht", "mehr", "weniger",
    "sehr", "alle", "viele", "neue", "neuer", "erste", "letzte", "wird",
    "werden", "wurde", "wurden", "haben", "sagt", "sagte", "welt",
    "nachrichten", "heute", "gestern", "morgen", "jahr", "jahre", "tage",
    "woche", "monat",
    "della", "delle", "dello", "degli", "dalla", "dalle", "dallo", "dagli",
    "nella", "nelle", "nello", "negli", "sulla", "sulle", "sullo", "sugli",
    "senza", "sotto", "sopra", "contro", "secondo", "anche", "perche",
    "piu", "meno", "molto", "molta", "molti", "molte", "tutta", "tutti",
    "tutte", "altra", "altri", "altre", "stesso", "stessa", "nuova",
    "prima", "ultima", "possono", "saranno", "erano", "hanno", "detto",
    "mondo", "notizie", "oggi", "ieri", "domani", "giorno", "giorni",
    "settimana", "mese", "volta",
}

# A shared country, region or abstract topic is not evidence that two stories
# cover the same event. These tokens are common enough to link unrelated
# articles, so coherence ignores them.
STOPWORDS.update({
    "united", "states", "america", "american", "americas", "britain",
    "british", "england", "english", "france", "french", "germany",
    "german", "israel", "israeli", "iran", "iranian", "ukraine",
    "ukrainian", "russia", "russian", "china", "chinese", "india",
    "indian", "pakistan", "pakistani", "saudi", "arabia", "emirates",
    "qatar", "egypt", "egyptian", "turkey", "turkish", "syria", "syrian",
    "lebanon", "lebanese", "gaza", "sudan", "sudanese", "south", "north",
    "middle", "east", "west", "africa", "african", "europe", "european",
    "asia", "asian", "latina", "latin", "latino", "latinoamerica",
    "latinoamerican", "latinoamericanos", "korea", "korean", "japan",
    "japanese", "australia", "australian", "canada", "canadian", "mexico",
    "mexican", "brazil", "brazilian", "colombia", "colombian", "argentina",
    "argentinian", "venezuela", "venezuelan", "nigeria", "nigerian",
    "kenya", "kenyan", "ethiopia", "ethiopian", "somalia", "somali",
    "yemen", "yemeni", "iraq", "iraqi", "afghanistan", "afghan",
    "bangladesh", "bangladeshi", "indonesia", "indonesian", "philippines",
    "filipino", "thailand", "thai", "vietnam", "vietnamese", "taiwan",
    "taiwanese", "hong", "kong", "nations", "security", "council",
    "organization", "organisation", "union", "president", "minister",
    "government", "official", "officials", "police", "data", "center",
    "centers", "centre", "centres", "climate", "change",
})


def _ascii(value: str) -> str:
    text = value.replace("’", "'").replace("‘", "'").replace("`", "'")
    return "".join(
        char for char in unicodedata.normalize("NFKD", text) if not unicodedata.combining(char)
    )


def _stem(token: str) -> str:
    if len(token) > 5 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 6 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 5 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 5 and token.endswith("es"):
        return token[:-2]
    if len(token) > 4 and token.endswith("s"):
        return token[:-1]
    return token


def title_tokens(title: str) -> Set[str]:
    cleaned = _ascii(title).lower()
    return {
        _stem(token)
        for token in re.findall(r"[a-z0-9]{4,}", cleaned)
        if token not in STOPWORDS and not token.isdigit()
    }


def _tokens_match(left: str, right: str) -> bool:
    if left == right:
        return True
    shorter, longer = sorted((left, right), key=len)
    return len(shorter) >= 4 and longer.startswith(shorter) and len(longer) - len(shorter) <= 3


# Two shared countries plus one shared event family is strong evidence of the
# same event even when the headlines use different wording. Generic casualty
# words are deliberately excluded: "killed" alone must not merge unrelated
# incidents in the same countries.
STRONG_EVENT_ROOTS = (
    "execut", "behead", "decapitat", "massacr", "assassinat", "airstrik",
    "earthquak", "flood", "cyclon", "hurrican", "wildfir", "erupt", "tsunami",
    "outbreak", "pandem", "epidem", "elect", "referend", "coup", "protest",
    "rall", "ceasefir", "hostag", "kidnap", "explos", "crash", "derail",
    "invas", "offensiv", "sanction", "tariff", "treaty", "summit", "resign",
    "shoot", "stab", "drown", "capsiz", "migrant",
)


def _event_roots(tokens: Set[str]) -> Set[str]:
    return {
        root
        for root in STRONG_EVENT_ROOTS
        if any(token.startswith(root) or root.startswith(token) for token in tokens)
    }


def shares_story(
    left: Set[str],
    right: Set[str],
    left_countries: Set[str] | None = None,
    right_countries: Set[str] | None = None,
    left_events: Set[str] | None = None,
    right_events: Set[str] | None = None,
) -> bool:
    shared = {
        a for a in left for b in right
        if _tokens_match(a, b)
    }
    if len(shared) >= 2:
        return True
    if (
        left_countries
        and right_countries
        and left_events
        and right_events
        and len(left_countries & right_countries) >= 2
        and bool(left_events & right_events)
    ):
        return True
    return False


class StoryClusterer:
    """Clusters articles into story groups based on embeddings.

    Agglomerative clustering on short, multilingual headlines can merge stories
    that merely share a language or a broad subject. Every embedding cluster is
    therefore split into connected components that also share at least two
    distinctive title tokens. This keeps paraphrase-level coverage groups while
    preventing unrelated same-language stories from becoming one event.
    """

    def __init__(self, distance_threshold: float = 0.45):
        self.distance_threshold = distance_threshold

    def cluster(self, articles: List[Dict[str, Any]], embeddings: np.ndarray) -> List[List[Dict[str, Any]]]:
        if not articles:
            return []

        if len(articles) == 1:
            return [articles]

        clustering = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=self.distance_threshold,
            metric="cosine",
            linkage="average",
        )
        labels = clustering.fit_predict(embeddings)

        clusters: Dict[int, List[Dict[str, Any]]] = {}
        for art, label in zip(articles, labels):
            clusters.setdefault(label, []).append(art)

        refined: List[List[Dict[str, Any]]] = []
        for group in clusters.values():
            refined.extend(self._coherent_groups(group))
        return self._merge_by_signature(refined)

    def _merge_by_signature(self, groups: List[List[Dict[str, Any]]]) -> List[List[Dict[str, Any]]]:
        """Join tightly matching stories that landed in different embedding clusters.

        Embeddings can separate paraphrases of one event. A shared pair of
        countries plus a shared event family is strong enough to reunite them.
        """
        if len(groups) < 2:
            return groups

        signatures = []
        for group in groups:
            countries: Set[str] = set()
            events: Set[str] = set()
            for article in group:
                title = str(article.get("title") or "")
                countries.update(countries_in_text(title, limit=6))
                events.update(_event_roots(title_tokens(title)))
            signatures.append((countries, events))

        parent = list(range(len(groups)))

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        for left in range(len(groups)):
            for right in range(left + 1, len(groups)):
                left_countries, left_events = signatures[left]
                right_countries, right_events = signatures[right]
                if (
                    left_events
                    and right_events
                    and len(left_countries & right_countries) >= 2
                    and bool(left_events & right_events)
                ):
                    parent[find(right)] = find(left)

        merged: Dict[int, List[Dict[str, Any]]] = {}
        for index, group in enumerate(groups):
            merged.setdefault(find(index), []).extend(group)
        return list(merged.values())

    def _coherent_groups(self, group: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        if len(group) <= 1:
            return [group] if group else []

        tokens = [title_tokens(str(article.get("title") or "")) for article in group]
        country_sets = [
            set(countries_in_text(str(article.get("title") or ""), limit=6))
            for article in group
        ]
        event_sets = [_event_roots(token_set) for token_set in tokens]
        adjacency: Dict[int, Set[int]] = {index: set() for index in range(len(group))}
        for left in range(len(group)):
            for right in range(left + 1, len(group)):
                if shares_story(
                    tokens[left],
                    tokens[right],
                    country_sets[left],
                    country_sets[right],
                    event_sets[left],
                    event_sets[right],
                ):
                    adjacency[left].add(right)
                    adjacency[right].add(left)

        seen: Set[int] = set()
        parts: List[List[Dict[str, Any]]] = []
        for start in range(len(group)):
            if start in seen:
                continue
            stack = [start]
            seen.add(start)
            component: List[int] = []
            while stack:
                index = stack.pop()
                component.append(index)
                for neighbour in adjacency[index]:
                    if neighbour not in seen:
                        seen.add(neighbour)
                        stack.append(neighbour)
            parts.append([group[index] for index in sorted(component)])
        return parts
