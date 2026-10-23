"""Neutral, source-grounded event summaries with an extractive fallback."""
import json
import logging
import re
from typing import Any, Dict, List, Optional

from pipeline.llm.client import get_llm_client
from pipeline.modelling.verifier import Verifier

logger = logging.getLogger("pipeline.modelling.summariser")

SYSTEM_PROMPT = (
    "You are a neutral wire-service editor. Write a 2-3 sentence summary of the event\n"
    "using only the supplied headlines and snippets. Never add facts that are not in\n"
    "the supplied text. If sources disagree, say so and name the outlets. Do not use\n"
    "bracketed citation markers. Return strict JSON with fields: summary (string) and\n"
    "cited_source_ids (array of the src_N ids you used)."
)


def _strip_citations(text: str) -> str:
    return re.sub(r"\s*\[src_\d+\]", "", text or "").strip()


def _parse_json(text: str) -> Dict[str, Any]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def _first_sentence(text: str, limit: int = 220) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return ""
    match = re.match(r"(.+?[.!?])(?:\s|$)", cleaned)
    sentence = match.group(1) if match else cleaned
    return sentence[:limit].rstrip()


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _informative_snippet(snippet: str, title: str, outlet: str) -> str:
    """Return publisher-supplied detail that adds information beyond the headline."""
    cleaned = re.sub(r"\s+", " ", (snippet or "").strip())
    if not cleaned:
        return ""
    cleaned = re.sub(r"^\[headline only\]\s*", "", cleaned, flags=re.IGNORECASE).strip()
    lowered = cleaned.lower()
    for prefix in (f"{outlet} - ", f"{outlet}: ", f"{outlet} — "):
        if outlet and lowered.startswith(prefix.lower()):
            cleaned = cleaned[len(prefix):].strip()
            break
    cleaned = re.sub(
        r"\s*(read more|continue reading|full story|subscribe to .*?)\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    snippet_key = _normalise(cleaned)
    title_key = _normalise(title)
    if not snippet_key or len(snippet_key) < 30:
        return ""
    if snippet_key == title_key:
        return ""
    if (snippet_key in title_key or title_key in snippet_key) and abs(len(snippet_key) - len(title_key)) < 40:
        return ""
    return cleaned


def _detail_sentences(text: str) -> List[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [
        sentence.strip()
        for sentence in sentences
        if len(sentence.strip()) >= 40
    ]


class Summariser:
    def __init__(self):
        self.llm = get_llm_client()
        self.verifier = Verifier()

    def summarise_hover(
        self,
        articles: List[Dict[str, Any]],
        title: Optional[str] = None,
        allow_llm: bool = True,
    ) -> Dict[str, Any]:
        if not articles:
            return {"summary": "", "cited_ids": [], "confidence": 0.0, "method": "extractive"}

        payload = []
        seen_outlets = set()
        for article in articles:
            if len(payload) >= 5:
                break
            if article.get("source") == "gdelt_events":
                continue
            outlet = article.get("outlet") or article.get("domain") or "Unknown outlet"
            key = outlet.lower()
            if key in seen_outlets:
                continue
            seen_outlets.add(key)
            payload.append(
                {
                    "id": f"src_{len(payload) + 1}",
                    "outlet": outlet,
                    "title": (article.get("title") or "").strip(),
                    "snippet": (article.get("snippet") or "")[:350],
                }
            )
        if not payload:
            first = articles[0]
            payload = [{
                "id": "src_1",
                "outlet": first.get("outlet") or "Source",
                "title": first.get("title", ""),
                "snippet": (first.get("snippet") or "")[:350],
            }]

        if allow_llm and self.llm.has_provider():
            prompt = (
                (f"Event headline: {title}\n\n" if title else "")
                + "Articles:\n"
                + json.dumps(payload, ensure_ascii=False, indent=2)
            )
            try:
                response = self.llm.complete(
                    prompt=prompt,
                    system_prompt=SYSTEM_PROMPT,
                    temperature=0.2,
                    max_tokens=350,
                    json_mode=True,
                )
                if response.provider != "extractive_mock":
                    data = _parse_json(response.text)
                    summary = _strip_citations(str(data.get("summary", "")))
                    cited = [str(item) for item in data.get("cited_source_ids", [])]
                    if summary and self.verifier.verify(summary, payload, cited)["overall_pass"]:
                        return {
                            "summary": summary,
                            "cited_ids": cited or [payload[0]["id"]],
                            "confidence": round(min(0.75 + 0.03 * len(payload), 0.94), 2),
                            "method": f"llm:{response.provider}",
                        }
                    logger.info("LLM summary rejected by verifier; using extractive fallback.")
            except Exception as exc:
                logger.info("LLM summarisation unavailable: %s", exc)

        summary = self._extractive(payload, title=title)
        return {
            "summary": summary,
            "cited_ids": [item["id"] for item in payload[:3]],
            "confidence": round(min(0.55 + 0.06 * len(payload), 0.85), 2),
            "method": "extractive",
        }

    def _extractive(self, payload: List[Dict[str, Any]], title: Optional[str] = None) -> str:
        if not payload:
            return ""

        event_title = _first_sentence(title or payload[0].get("title", ""), 180)
        if not event_title:
            return ""

        if title:
            target = set(_normalise(title).split())
            payload = sorted(
                payload,
                key=lambda item: len(target & set(_normalise(item.get("title", "")).split())),
                reverse=True,
            )

        parts: List[str] = []
        seen: set = set()
        lead = f"{payload[0].get('outlet') or 'The source'} reports: {event_title.rstrip('.')}."
        seen.add(_normalise(lead))
        parts.append(lead)

        detail_budget = 2
        for position, item in enumerate(payload[:3]):
            snippet = _informative_snippet(
                item.get("snippet", ""),
                item.get("title", ""),
                item.get("outlet", ""),
            )
            item_title = _first_sentence(item.get("title", ""), 180)
            item_key = _normalise(item_title)
            event_key = _normalise(event_title)
            added = ""
            if snippet:
                for sentence in _detail_sentences(snippet):
                    key = _normalise(sentence)
                    if not key or key in seen or key == item_key:
                        continue
                    seen.add(key)
                    added = sentence if sentence.endswith((".", "!", "?")) else sentence + "."
                    break
            elif position > 0 and item_key and item_key not in seen:
                # Several wire and local feeds publish only a headline. Use the
                # next distinct headline rather than pretending the story is a
                # single sentence.
                if item_key == event_key or item_key in event_key or event_key in item_key:
                    continue
                seen.add(item_key)
                added = item_title

            if not added:
                continue
            if position == 0:
                attributed = added
            else:
                attributed = f"{item.get('outlet')} adds: {added.rstrip('.')}."
            parts.append(attributed)
            detail_budget -= 1
            if detail_budget <= 0:
                break

        return " ".join(parts)[:600].strip()
