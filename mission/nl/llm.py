"""OpenAI-compatible LLM backend for NL -> Mission IR.

Works with any OpenAI-compatible /chat/completions endpoint: OpenAI, Azure
OpenAI, or a local server (Ollama `ollama serve`, llama.cpp `--api`, LM Studio).
Configure via env:

    NIMBUS_LLM_BASE_URL   default https://api.openai.com/v1
    NIMBUS_LLM_API_KEY    API key (use any non-empty value for local servers)
    NIMBUS_LLM_MODEL      default gpt-4o-mini
    NIMBUS_LLM_TIMEOUT_S  default 30

Uses only the stdlib (urllib) so it adds no dependency.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from mission.nl.base import NLCompileError
from mission.nl.prompt import build_system_prompt


class LLMCompiler:
    """NL->IR via an OpenAI-compatible chat endpoint. Implements NLCompiler."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get(
            "NIMBUS_LLM_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.api_key = api_key or os.environ.get("NIMBUS_LLM_API_KEY", "")
        self.model = model or os.environ.get("NIMBUS_LLM_MODEL", "gpt-4o-mini")
        self.timeout_s = timeout_s or float(os.environ.get("NIMBUS_LLM_TIMEOUT_S", "30"))

    def compile(self, text: str) -> dict[str, Any]:
        if not (text or "").strip():
            raise NLCompileError("empty mission text")
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": build_system_prompt()},
                {"role": "user", "content": text.strip()},
            ],
            "response_format": {"type": "json_object"},
        }
        content = self._post(payload)
        return self._extract_json(content)

    def _post(self, payload: dict[str, Any]) -> str:
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as exc:  # pragma: no cover - network
            body = exc.read().decode(errors="replace")[:500]
            raise NLCompileError(f"LLM HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:  # pragma: no cover
            raise NLCompileError(f"LLM unreachable at {self.base_url}: {exc}") from exc
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:  # pragma: no cover
            raise NLCompileError(f"unexpected LLM response shape: {data}") from exc

    @staticmethod
    def _extract_json(content: str) -> dict[str, Any]:
        content = content.strip()
        # tolerate ```json fences some models still emit
        fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", content, re.S)
        if fence:
            content = fence.group(1)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            brace = re.search(r"\{.*\}", content, re.S)
            if brace:
                return json.loads(brace.group(0))
            raise NLCompileError(f"LLM did not return JSON: {content[:200]!r}")
