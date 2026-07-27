"""Optional OpenAI-compatible client for bounded PDF interpretation."""

from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class AIClientError(RuntimeError):
    """Raised when the configured AI endpoint cannot return usable text."""


@dataclass(slots=True)
class AISettings:
    """Connection settings for an OpenAI-compatible chat endpoint."""

    endpoint: str = ""
    model: str = ""
    api_key: str = ""
    timeout: float = 60.0

    @classmethod
    def from_environment(cls) -> "AISettings":
        """Load settings from PDFGUI_AI_* environment variables."""

        timeout_text = os.environ.get("PDFGUI_AI_TIMEOUT", "60")
        try:
            timeout = float(timeout_text)
        except ValueError:
            timeout = 60.0
        if not math.isfinite(timeout):
            timeout = 60.0
        return cls(
            endpoint=os.environ.get("PDFGUI_AI_ENDPOINT", "").strip(),
            model=os.environ.get("PDFGUI_AI_MODEL", "").strip(),
            api_key=os.environ.get("PDFGUI_AI_API_KEY", "").strip(),
            timeout=min(600.0, max(1.0, timeout)),
        )


class OpenAICompatibleClient:
    """Send a report prompt to an OpenAI-compatible chat-completions API."""

    def __init__(self, settings: AISettings):
        self.settings = settings

    def ask(self, prompt: str) -> str:
        """Return the endpoint's text response."""

        endpoint = self.settings.endpoint.strip()
        model = self.settings.model.strip()
        if not endpoint:
            raise AIClientError("AI endpoint is not configured")
        if not model:
            raise AIClientError("AI model is not configured")
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a careful scientific assistant for atomic pair distribution function analysis. "
                        "Respect the evidence boundaries in the user's prompt."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        try:
            request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
        except (TypeError, ValueError) as error:
            raise AIClientError(f"AI endpoint is invalid: {error}") from error
        timeout = _validated_timeout(self.settings.timeout)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                response_body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            raise AIClientError(f"AI endpoint returned HTTP {error.code}: {detail}") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise AIClientError(f"AI request failed: {error}") from error

        try:
            parsed = json.loads(response_body)
        except json.JSONDecodeError as error:
            raise AIClientError("AI endpoint returned invalid JSON") from error
        text = _extract_response_text(parsed)
        if not text:
            raise AIClientError("AI endpoint response did not contain assistant text")
        return text.strip()


def _extract_response_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                return _content_to_text(message.get("content"))
            return _content_to_text(first.get("text"))
    return _content_to_text(payload.get("output_text"))


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                elif isinstance(text, dict) and isinstance(text.get("value"), str):
                    parts.append(text["value"])
        return "\n".join(parts)
    return ""


def _validated_timeout(value: Any) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        return 60.0
    if not math.isfinite(timeout):
        return 60.0
    return min(600.0, max(1.0, timeout))
