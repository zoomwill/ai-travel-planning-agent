"""Validate Qwen endpoints before an API key can be sent anywhere."""

import re
from typing import TypeAlias
from urllib.parse import urlsplit

from app.llm.errors import LLMError

QwenHostClass: TypeAlias = str

_DASHSCOPE_HOST_CLASSES = {
    "dashscope.aliyuncs.com": "china-beijing",
    "dashscope-intl.aliyuncs.com": "singapore",
    "dashscope-us.aliyuncs.com": "united-states",
    "cn-hongkong.dashscope.aliyuncs.com": "china-hong-kong",
}
_MAAS_REGIONS = {
    "cn-beijing",
    "ap-southeast-1",
    "ap-northeast-1",
    "eu-central-1",
    "cn-hongkong",
}
_WORKSPACE_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def validate_qwen_base_url(base_url: str) -> QwenHostClass:
    """Allow only current official HTTPS Model Studio compatibility endpoints."""

    parsed = urlsplit(base_url)
    try:
        port = parsed.port
    except ValueError:
        raise LLMError("llm_invalid_base_url") from None
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/compatible-mode/v1"
    ):
        raise LLMError("llm_invalid_base_url")

    hostname = parsed.hostname
    if hostname is None:
        raise LLMError("llm_invalid_base_url")
    exact_class = _DASHSCOPE_HOST_CLASSES.get(hostname)
    if exact_class is not None:
        return exact_class

    labels = hostname.split(".")
    if (
        len(labels) == 5
        and labels[2:] == ["maas", "aliyuncs", "com"]
        and labels[1] in _MAAS_REGIONS
        and _WORKSPACE_LABEL.fullmatch(labels[0]) is not None
    ):
        return f"workspace-{labels[1]}"
    raise LLMError("llm_invalid_base_url")
