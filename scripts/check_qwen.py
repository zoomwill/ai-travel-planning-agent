"""Run one explicit, minimal, structured Qwen connectivity check."""

from __future__ import annotations

import asyncio
import re
import sys

from pydantic import ValidationError

from app.core.config import Settings
from app.llm.errors import LLMError
from app.llm.runtime import create_llm_runtime, require_qwen_provider


async def check_qwen() -> int:
    """Validate configuration, make one paid request, and hide all private details."""

    try:
        loaded = Settings()
    except ValidationError:
        print("FAIL Qwen: invalid local configuration")
        return 1
    settings = loaded.model_copy(update={"agent_reasoning_mode": "qwen"})
    if not settings.qwen_is_configured:
        print("FAIL Qwen: llm_not_configured (set QWEN_API_KEY or DASHSCOPE_API_KEY)")
        return 1

    runtime = create_llm_runtime(settings)
    try:
        provider = require_qwen_provider(runtime)
        result = await provider.smoke_test()
        if result.value.status != "ok":
            print("FAIL Qwen: llm_schema_validation_failed")
            return 1
        safe_model = re.sub(r"[^A-Za-z0-9._-]", "_", result.model)[:128]
        usage = "token usage unavailable"
        if result.input_tokens is not None and result.output_tokens is not None:
            usage = f"input_tokens={result.input_tokens}; output_tokens={result.output_tokens}"
        print(f"PASS Qwen: model={safe_model}; {usage}")
        return 0
    except LLMError as exc:
        print(f"FAIL Qwen: {exc.code}")
        return 1
    except Exception:
        print("FAIL Qwen: llm_provider_error")
        return 1
    finally:
        await runtime.aclose()


def main() -> int:
    """Provide a synchronous command-line entry point."""

    return asyncio.run(check_qwen())


if __name__ == "__main__":
    sys.exit(main())
