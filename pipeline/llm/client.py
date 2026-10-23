import json
import logging
import os
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from pipeline.config import settings

logger = logging.getLogger("pipeline.llm.client")


class LLMProvider(Enum):
    GROQ = "groq"
    OPENROUTER = "openrouter"
    GEMINI = "gemini"
    OLLAMA = "ollama"
    EXTRACTIVE_MOCK = "mock"


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float


class LLMClient:
    """Free-first LLM client with a file-backed daily budget.

    Failover: Groq -> OpenRouter free models -> Gemini -> Ollama -> extractive.
    Every provider is optional and every failure is isolated. The default
    budgets (8 summaries per pipeline run, 80% of provider limits) are
    deliberately below the advertised free tiers so a scheduled run can never
    exhaust an account and crash the application.
    """

    def __init__(self):
        self._daily_counts: Dict[str, int] = {}
        self._minute_timestamps: Dict[str, List[float]] = {}
        self._disabled_providers: Dict[str, float] = {}
        self._disabled_models: Dict[str, float] = {}
        self._current_day = ""
        self._usage_path = Path(settings.data_dir) / "llm_usage.json"
        self._ollama_enabled = os.getenv("ENABLE_OLLAMA", "false").lower() == "true"
        self._timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "45"))
        self.providers = [
            {
                "name": LLMProvider.GROQ,
                "base_url": "https://api.groq.com/openai/v1/chat/completions",
                "model": settings.groq_model or "qwen/qwen3.8-27b",
                "rpm": max(1, settings.groq_rpm),
                "rpd": max(1, settings.groq_rpd),
                "env_key": "GROQ_API_KEY",
            },
            {
                "name": LLMProvider.OPENROUTER,
                "base_url": "https://openrouter.ai/api/v1/chat/completions",
                "models": list(settings.openrouter_models),
                "rpm": max(1, settings.openrouter_rpm),
                "rpd": max(1, settings.openrouter_rpd),
                "env_key": "OPENROUTER_API_KEY",
            },
            {
                "name": LLMProvider.GEMINI,
                "base_url": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
                "rpm": 10,
                "rpd": 200,
                "env_key": "GEMINI_API_KEY",
            },
            {
                "name": LLMProvider.OLLAMA,
                "base_url": "http://localhost:11434/api/chat",
                "model": os.getenv("OLLAMA_MODEL", "llama3.1:8b"),
                "rpm": 999,
                "rpd": 999999,
                "env_key": None,
            },
        ]

    def has_provider(self) -> bool:
        if os.getenv("GROQ_API_KEY") or os.getenv("OPENROUTER_API_KEY") or os.getenv("GEMINI_API_KEY"):
            return True
        return self._ollama_enabled

    # ------------------------------------------------------------- usage budget
    def _today(self) -> str:
        return time.strftime("%Y-%m-%d")

    def _load_usage(self) -> Dict[str, Any]:
        today = self._today()
        try:
            data = json.loads(self._usage_path.read_text(encoding="utf-8"))
            if data.get("date") == today and isinstance(data.get("counts"), dict):
                return data
        except Exception:
            pass
        return {"date": today, "counts": {}}

    def _save_usage(self, data: Dict[str, Any]) -> None:
        try:
            self._usage_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._usage_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data), encoding="utf-8")
            os.replace(temporary, self._usage_path)
        except Exception as exc:
            logger.debug("Could not persist LLM usage: %s", exc)

    def _usage_count(self, name: str) -> int:
        usage = self._load_usage()
        return max(self._daily_counts.get(name, 0), int(usage["counts"].get(name, 0)))

    def _record_request(self, provider: Dict[str, Any]) -> None:
        name = provider["name"].value
        now = time.time()
        usage = self._load_usage()
        usage["counts"][name] = max(int(usage["counts"].get(name, 0)), self._daily_counts.get(name, 0)) + 1
        self._daily_counts[name] = usage["counts"][name]
        self._save_usage(usage)
        self._minute_timestamps.setdefault(name, []).append(now)

    def _check_rate_limit(self, provider: Dict[str, Any]) -> bool:
        name = provider["name"].value
        now = time.time()
        disabled_until = self._disabled_providers.get(name, 0)
        if disabled_until > now:
            return False

        # Keep a safety margin: never spend the last 20% of a free daily tier.
        daily = self._usage_count(name)
        if daily >= max(1, int(provider["rpd"] * 0.8)):
            return False

        timestamps = [t for t in self._minute_timestamps.get(name, []) if now - t < 60]
        self._minute_timestamps[name] = timestamps
        return len(timestamps) < max(1, provider["rpm"])

    # --------------------------------------------------------------- completion
    def complete(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.3,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> LLMResponse:
        errors: List[str] = []

        for provider in self.providers:
            if provider["env_key"] and not os.getenv(provider["env_key"]):
                continue
            if provider["name"] == LLMProvider.OLLAMA and not self._ollama_enabled:
                continue
            if not self._check_rate_limit(provider):
                continue

            try:
                start = time.time()
                if provider["name"] == LLMProvider.OPENROUTER:
                    response = self._call_openrouter(
                        provider, prompt, system_prompt, temperature, max_tokens, json_mode
                    )
                else:
                    self._record_request(provider)
                    if provider["name"] == LLMProvider.GROQ:
                        response = self._call_groq(
                            provider, prompt, system_prompt, temperature, max_tokens, json_mode
                        )
                    elif provider["name"] == LLMProvider.GEMINI:
                        response = self._call_gemini(
                            provider, prompt, system_prompt, temperature, max_tokens, json_mode
                        )
                    else:
                        response = self._call_ollama(
                            provider, prompt, system_prompt, temperature, max_tokens, json_mode
                        )
                response.latency_ms = (time.time() - start) * 1000
                return response
            except Exception as exc:
                logger.warning("LLM provider %s failed: %s", provider["name"].value, exc)
                self._disabled_providers[provider["name"].value] = time.time() + 300
                errors.append(f"{provider['name'].value}: {exc}")
                continue

        logger.info("Falling back to local extractive heuristic processor.")
        return self._extractive_fallback(prompt, json_mode)

    def _messages(self, prompt: str, system_prompt: str) -> List[Dict[str, str]]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _call_groq(
        self,
        provider: Dict[str, Any],
        prompt: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> LLMResponse:
        body = {
            "model": provider["model"],
            "messages": self._messages(prompt, system_prompt),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        response = requests.post(
            provider["base_url"],
            json=body,
            headers={
                "Authorization": f"Bearer {os.getenv(provider['env_key'])}",
                "Content-Type": "application/json",
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        data = response.json()
        return LLMResponse(
            text=data["choices"][0]["message"]["content"],
            provider="groq",
            model=provider["model"],
            input_tokens=data.get("usage", {}).get("prompt_tokens", 0),
            output_tokens=data.get("usage", {}).get("completion_tokens", 0),
            latency_ms=0,
        )

    def _call_openrouter(
        self,
        provider: Dict[str, Any],
        prompt: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> LLMResponse:
        if not provider.get("models"):
            raise RuntimeError("no free OpenRouter model configured")
        errors: List[str] = []
        now = time.time()
        for model in provider["models"]:
            model_key = f"openrouter:{model}"
            if self._disabled_models.get(model_key, 0) > now:
                continue
            if not self._check_rate_limit(provider):
                break
            self._record_request(provider)
            body = {
                "model": model,
                "messages": self._messages(prompt, system_prompt),
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            }
            try:
                response = requests.post(
                    provider["base_url"],
                    json=body,
                    headers={
                        "Authorization": f"Bearer {os.getenv(provider['env_key'])}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "http://localhost:8000"),
                        "X-Title": "Globe News Atlas",
                    },
                    timeout=self._timeout,
                )
                if response.status_code in {402, 404, 429}:
                    self._disabled_models[model_key] = time.time() + 600
                    errors.append(f"{model}: HTTP {response.status_code}")
                    logger.info("OpenRouter free model unavailable (%s): HTTP %s", model, response.status_code)
                    continue
                response.raise_for_status()
                data = response.json()
                choices = data.get("choices") or []
                if not choices:
                    self._disabled_models[model_key] = time.time() + 300
                    errors.append(f"{model}: empty choices")
                    continue
                content = choices[0].get("message", {}).get("content") or ""
                if not content.strip():
                    errors.append(f"{model}: empty content")
                    continue
                usage = data.get("usage") or {}
                return LLMResponse(
                    text=content,
                    provider="openrouter",
                    model=model,
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                    latency_ms=0,
                )
            except Exception as exc:
                self._disabled_models[model_key] = time.time() + 300
                errors.append(f"{model}: {exc}")
                logger.info("OpenRouter free model failed (%s): %s", model, exc)
        raise RuntimeError("all free OpenRouter models failed: " + "; ".join(errors[:4]))

    def _call_gemini(
        self,
        provider: Dict[str, Any],
        prompt: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
        json_mode: bool = False,
    ) -> LLMResponse:
        url = provider["base_url"].format(model=provider["model"])
        text_content = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        generation_config: Dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
        if json_mode:
            generation_config["responseMimeType"] = "application/json"
        response = requests.post(
            url,
            json={
                "contents": [{"parts": [{"text": text_content}]}],
                "generationConfig": generation_config,
            },
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": os.getenv(provider["env_key"], ""),
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        usage = data.get("usageMetadata", {})
        return LLMResponse(
            text=text,
            provider="gemini",
            model=provider["model"],
            input_tokens=usage.get("promptTokenCount", 0),
            output_tokens=usage.get("candidatesTokenCount", 0),
            latency_ms=0,
        )

    def _call_ollama(
        self,
        provider: Dict[str, Any],
        prompt: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> LLMResponse:
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        body = {
            "model": provider["model"],
            "messages": self._messages(prompt, system_prompt),
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if json_mode:
            body["format"] = "json"
        response = requests.post(f"{base_url}/api/chat", json=body, timeout=self._timeout)
        response.raise_for_status()
        data = response.json()
        return LLMResponse(
            text=data["message"]["content"],
            provider="ollama",
            model=provider["model"],
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            latency_ms=0,
        )

    def _extractive_fallback(self, prompt: str, json_mode: bool) -> LLMResponse:
        content = {"summary": "", "cited_source_ids": [], "confidence": 0}
        return LLMResponse(
            text=json.dumps(content) if json_mode else "",
            provider="extractive_mock",
            model="fallback-v1",
            input_tokens=0,
            output_tokens=0,
            latency_ms=0.0,
        )


_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
