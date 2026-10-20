"""OpenAI-compatible DeepSeek chat client.

The client deliberately uses the Python standard library, so no SDK is needed.
It supports both an environment variable and a local secret file; the secret
itself is never written to configuration.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from llm.errors import LLMError


class DeepSeekError(LLMError):
    """Raised when the DeepSeek API cannot produce a completion."""


class DeepSeekClient:
    def __init__(self, config: dict[str, Any]) -> None:
        self.base_url = str(config.get("base_url", "https://api.deepseek.com")).rstrip("/")
        self.model = str(config.get("model", "deepseek-flash")).strip() or "deepseek-flash"
        self.timeout = float(config.get("timeout_seconds", 45))
        self.temperature = float(config.get("temperature", 0.7))
        self.max_tokens = int(config.get("max_tokens", 600))
        self.thinking = str(config.get("thinking", "disabled")).strip().lower()
        reasoning = config.get("reasoning", {})
        if not isinstance(reasoning, dict):
            reasoning = {}
        self.reasoning_model = str(reasoning.get("model", self.model)).strip() or self.model
        self.reasoning_thinking = str(reasoning.get("thinking", "enabled")).strip().lower()
        self.reasoning_effort = str(reasoning.get("reasoning_effort", "high")).strip().lower()
        self.reasoning_max_tokens = int(reasoning.get("max_tokens", 1200))
        self.api_key_env = str(config.get("api_key_env", "DEEPSEEK_API_KEY")).strip()
        self.api_key_file = str(config.get("api_key_file", "")).strip()

    def _api_key(self) -> str:
        key = os.environ.get(self.api_key_env, "").strip() if self.api_key_env else ""
        if key:
            return key
        if self.api_key_file:
            try:
                key = Path(self.api_key_file).read_text(encoding="utf-8").splitlines()[0].strip()
            except (OSError, UnicodeError, IndexError):
                key = ""
        if not key:
            source_name = self.api_key_env if self.api_key_env and not self.api_key_env.startswith("sk-") else "DEEPSEEK_API_KEY"
            raise DeepSeekError(
                f"DeepSeek API key is missing; set environment variable {source_name} or fill {self.api_key_file}"
            )
        return key

    def _endpoint(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return self.base_url + "/chat/completions"

    async def chat(self, messages: list[dict[str, str]]) -> str:
        return await self.chat_with_mode(messages, mode="fast")

    async def chat_with_mode(self, messages: list[dict[str, str]], mode: str = "fast") -> str:
        """Run a completion using the fast or reasoning parameter profile."""
        return await asyncio.to_thread(self._chat_sync, messages, mode)

    def _chat_sync(self, messages: list[dict[str, str]], mode: str = "fast") -> str:
        reasoning_mode = str(mode).strip().lower() == "reasoning"
        model = self.reasoning_model if reasoning_mode else self.model
        thinking = self.reasoning_thinking if reasoning_mode else self.thinking
        max_tokens = self.reasoning_max_tokens if reasoning_mode else self.max_tokens
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "max_tokens": max_tokens,
        }
        if reasoning_mode:
            if thinking in {"enabled", "disabled"}:
                payload["thinking"] = {"type": thinking}
            if thinking == "enabled" and self.reasoning_effort in {"low", "high", "max"}:
                payload["reasoning_effort"] = self.reasoning_effort
        else:
            payload["temperature"] = self.temperature
            if thinking in {"enabled", "disabled"}:
                payload["thinking"] = {"type": thinking}
        request = urllib.request.Request(
            self._endpoint(),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key()}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                result = json.loads(raw)
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:800]
            except OSError:
                detail = str(exc)
            raise DeepSeekError(f"DeepSeek HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise DeepSeekError(f"DeepSeek request failed: {exc}") from exc
        try:
            content = result["choices"][0]["message"].get("content", "")
        except (KeyError, IndexError, TypeError) as exc:
            raise DeepSeekError("DeepSeek response did not contain choices[0].message.content") from exc
        if not isinstance(content, str):
            raise DeepSeekError("DeepSeek response content was not text")
        return content.strip()
