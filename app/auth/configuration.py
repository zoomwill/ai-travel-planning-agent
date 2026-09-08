"""Pure validation for trusted deployment origins, not request-supplied URLs."""

import ipaddress
import re
from urllib.parse import urlsplit


def https_origin(value: str) -> str:
    """Require an exact HTTPS DNS origin, with no credentials, path or wildcard."""

    parsed = urlsplit(value)
    try:
        ipaddress.ip_address(parsed.hostname or "")
    except ValueError:
        pass
    else:
        raise ValueError("expected a trusted DNS origin, not an IP address")
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?", parsed.hostname)
        or "." not in parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or any(char.isspace() for char in value)
    ):
        raise ValueError("expected an exact HTTPS origin without credentials or path")
    return f"https://{parsed.hostname}"


def normalize_issuer(value: str) -> str:
    """Normalize a configured Auth0 tenant/custom-domain issuer with a trailing slash."""

    return https_origin(value) + "/"
