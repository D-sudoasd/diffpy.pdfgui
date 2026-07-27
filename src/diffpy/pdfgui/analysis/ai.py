"""Optional OpenAI-compatible client for bounded PDF interpretation."""

from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

_MAX_RESPONSE_BYTES = 2 * 1024 * 1024


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

        endpoint = _validated_endpoint(self.settings.endpoint)
        model = self.settings.model.strip()
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
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "diffpy.pdfgui-ai-analysis",
        }
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        try:
            request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
        except (TypeError, ValueError) as error:
            raise AIClientError(f"AI endpoint is invalid: {error}") from error
        timeout = _validated_timeout(self.settings.timeout)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                response_bytes = response.read(_MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            detail = error.read(501).decode("utf-8", errors="replace")
            raise AIClientError(f"AI endpoint returned HTTP {error.code}: {detail}") from error
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            raise AIClientError(f"AI request failed: {error}") from error
        if len(response_bytes) > _MAX_RESPONSE_BYTES:
            raise AIClientError("AI endpoint response exceeded the 2 MiB safety limit")
        response_body = response_bytes.decode("utf-8", errors="replace")

        try:
            parsed = json.loads(response_body)
        except json.JSONDecodeError as error:
            raise AIClientError("AI endpoint returned invalid JSON") from error
        text = _extract_response_text(parsed)
        if not text:
            raise AIClientError("AI endpoint response did not contain assistant text")
        return text.strip()


def _validated_endpoint(value: Any) -> str:
    endpoint = str(value or "").strip()
    if not endpoint:
        raise AIClientError("AI endpoint is not configured")
    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AIClientError("AI endpoint must be an absolute HTTP or HTTPS URL")
    if parsed.username or parsed.password:
        raise AIClientError("AI endpoint credentials must be supplied through the API-key field")
    return endpoint


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
