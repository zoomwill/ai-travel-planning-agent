"""SDK-shaped test doubles that never open a network connection."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from openai.types.chat import ChatCompletion


class FakeCompletions:
    """Return or raise scripted values while recording sanitized request arguments."""

    def __init__(self, responses: Sequence[ChatCompletion | BaseException]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> ChatCompletion:
        """Return the next script entry without interpreting request content."""

        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class FakeChat:
    """Expose the nested SDK attribute used by the provider."""

    def __init__(self, completions: FakeCompletions) -> None:
        self.completions = completions


class FakeAsyncOpenAI:
    """Minimal reusable client double with observable cleanup."""

    def __init__(self, responses: Sequence[ChatCompletion | BaseException]) -> None:
        self.completions = FakeCompletions(responses)
        self.chat = FakeChat(self.completions)
        self.close_calls = 0

    async def close(self) -> None:
        """Record one application-lifespan cleanup."""

        self.close_calls += 1


def completion(
    payload: dict[str, object] | str,
    *,
    prompt_tokens: int | None = 7,
    completion_tokens: int | None = 3,
) -> ChatCompletion:
    """Create a real SDK response model around controlled JSON content."""

    content = payload if isinstance(payload, str) else json.dumps(payload)
    usage = None
    if prompt_tokens is not None and completion_tokens is not None:
        usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
    return ChatCompletion.model_validate(
        {
            "id": "offline-completion",
            "choices": [
                {
                    "finish_reason": "stop",
                    "index": 0,
                    "message": {"content": content, "role": "assistant"},
                }
            ],
            "created": 0,
            "model": "qwen-plus-test",
            "object": "chat.completion",
            "usage": usage,
        }
    )
