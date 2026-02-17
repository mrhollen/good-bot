from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ChatCompletionResult:
    content: str
    tool_calls: list[ToolCall]


def _extract_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        return "".join(parts)
    if content is None:
        return ""
    return str(content)


def _parse_tool_call_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        raw_str = raw.strip()
        if not raw_str:
            return {}
        try:
            parsed = json.loads(raw_str)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Tool call arguments were not valid JSON: {raw_str}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("Tool call arguments JSON must be an object.")
        return parsed
    raise RuntimeError("Tool call arguments must be a JSON object or object-encoded string.")


def _extract_tool_calls(message: dict[str, Any]) -> list[ToolCall]:
    raw_calls = message.get("tool_calls") or []

    # Backward compatibility with older OpenAI-style `function_call` field.
    if not raw_calls and isinstance(message.get("function_call"), dict):
        raw_calls = [
            {
                "id": "legacy_function_call",
                "type": "function",
                "function": message["function_call"],
            }
        ]

    parsed: list[ToolCall] = []
    for item in raw_calls:
        if not isinstance(item, dict):
            continue
        function = item.get("function") or {}
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        arguments = _parse_tool_call_args(function.get("arguments", {}))
        call_id = item.get("id")
        parsed.append(
            ToolCall(
                id=str(call_id) if call_id is not None else "",
                name=name.strip(),
                arguments=arguments,
            )
        )
    return parsed


class OpenRouterClient:
    def __init__(self, *, api_key: str, base_url: str, model: str, timeout_seconds: float = 60.0):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds

    def create_chat_completion(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float = 0.1,
    ) -> ChatCompletionResult:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools is not None:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice

        req = urllib.request.Request(
            url=f"{self._base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout_seconds) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenRouter request failed ({exc.code}): {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"OpenRouter request failed: {exc}") from exc

        data: dict[str, Any] = json.loads(body)
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("OpenRouter returned no choices.")

        message = choices[0].get("message", {})
        if not isinstance(message, dict):
            raise RuntimeError("OpenRouter returned an invalid message payload.")

        content = _extract_text_content(message.get("content", ""))
        tool_calls = _extract_tool_calls(message)
        return ChatCompletionResult(content=content, tool_calls=tool_calls)
