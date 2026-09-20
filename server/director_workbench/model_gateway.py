from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import httpx


@dataclass(frozen=True, slots=True)
class ChatCompletion:
    text: str
    input_tokens: int
    output_tokens: int
    model: str


class CompletionGateway(Protocol):
    def complete(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        json_mode: bool = False,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ChatCompletion: ...


class OpenAICompatibleAdapter:
    """Small adapter for providers implementing /chat/completions."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = client

    def complete(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        json_mode: bool = False,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ChatCompletion:
        body: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.4 if temperature is None else temperature,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if urlsplit(self._base_url).hostname == "api.deepseek.com":
            body["thinking"] = {"type": "disabled"}
        context = nullcontext(self._client) if self._client is not None else httpx.Client(timeout=90)
        with context as client:
            last_finish_reason = "unknown"
            for _attempt in range(3):
                response = client.post(
                    f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=body,
                )
                response.raise_for_status()
                payload = response.json()
                choice = payload["choices"][0]
                last_finish_reason = str(choice.get("finish_reason", "unknown"))
                content = choice["message"].get("content")
                if isinstance(content, str) and content.strip():
                    usage = payload.get("usage", {})
                    return ChatCompletion(
                        text=content,
                        input_tokens=int(usage.get("prompt_tokens", 0)),
                        output_tokens=int(usage.get("completion_tokens", 0)),
                        model=payload.get("model", model),
                    )
                if last_finish_reason == "length" and isinstance(body.get("max_tokens"), int):
                    body["max_tokens"] = max(body["max_tokens"] * 2, 1024)
        raise RuntimeError(
            "模型连续 3 次返回空内容，请稍后重试或更换模型"
            f"（finish_reason={last_finish_reason}）"
        )
