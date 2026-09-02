"""Secure, provider-neutral connection error classification and redaction."""

from __future__ import annotations

import re
import socket
import ssl
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError


PROVIDER_CONNECTION_CATEGORIES = frozenset(
    {
        "available",
        "not_configured",
        "authentication_failed",
        "permission_denied",
        "not_found",
        "rate_limited",
        "timeout",
        "network_error",
        "ssl_error",
        "bad_request",
        "response_error",
        "connection_failed",
        "unknown_error",
    }
)

HTTP_STATUS_CATEGORIES = {
    400: "bad_request",
    401: "authentication_failed",
    403: "permission_denied",
    404: "not_found",
    408: "timeout",
    429: "rate_limited",
}

_SECRET_FIELD = re.compile(
    r"(?ix)"
    r"(?:['\"])?"
    r"(?:authorization|proxy-authorization|cookie|set-cookie|"
    r"api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|"
    r"dashscope_api_key|deepseek_api_key)"
    r"(?:['\"])?\s*[:=]\s*"
    r"(?:bearer\s+)?(?:['\"][^'\"]*['\"]|[^\s,;}\]]+)"
)
_BEARER_TOKEN = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")
_HEADERS_BLOCK = re.compile(r"(?is)\bheaders?\s*[:=]\s*\{[^{}]*\}")
_URL_QUERY = re.compile(r"(?i)(https://[^\s?]+)\?[^\s]+")
_CONTROL_WHITESPACE = re.compile(r"[\r\n\t]+")
_SENSITIVE_LABEL = re.compile(
    r"(?i)\b(?:authorization|proxy-authorization|cookie|set-cookie|"
    r"api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|"
    r"dashscope_api_key|deepseek_api_key)\b"
)


@dataclass(frozen=True)
class ProviderErrorDiagnostic:
    category: str
    http_status: int | None
    error_type: str
    safe_summary: str


def sanitize_provider_error(value: Any, *, max_length: int = 240) -> str:
    """Return a bounded single-line error summary with common credentials removed."""

    text = str(value or "provider connection failed")
    text = _HEADERS_BLOCK.sub("[REDACTED]", text)
    text = _SECRET_FIELD.sub("[REDACTED]", text)
    text = _BEARER_TOKEN.sub("[REDACTED]", text)
    text = _URL_QUERY.sub(r"\1?[REDACTED]", text)
    text = _SENSITIVE_LABEL.sub("[REDACTED]", text)
    text = _CONTROL_WHITESPACE.sub(" ", text)
    text = " ".join(text.split())
    if not text:
        text = "provider connection failed"
    if len(text) > max_length:
        text = f"{text[: max_length - 1]}…"
    return text


def classify_provider_error(exc: BaseException) -> ProviderErrorDiagnostic:
    """Classify SDK, urllib and network exceptions without exposing their payloads."""

    http_status = _http_status(exc)
    category_hint = _safe_attribute(exc, "category")
    if category_hint not in PROVIDER_CONNECTION_CATEGORIES:
        category_hint = None

    category = category_hint or HTTP_STATUS_CATEGORIES.get(http_status)
    if category is None and http_status is not None:
        category = "connection_failed"
    elif category is None:
        category = _category_from_exception(exc)

    error_type = _safe_attribute(exc, "error_type") or type(exc).__name__
    summary_source = _safe_attribute(exc, "safe_summary") or str(exc)
    return ProviderErrorDiagnostic(
        category=category,
        http_status=http_status,
        error_type=sanitize_provider_error(error_type, max_length=80),
        safe_summary=sanitize_provider_error(summary_source),
    )


def _category_from_exception(exc: BaseException) -> str:
    if isinstance(exc, ssl.SSLError):
        return "ssl_error"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(exc, HTTPError):
        return HTTP_STATUS_CATEGORIES.get(exc.code, "connection_failed")
    if isinstance(exc, URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, BaseException) and reason is not exc:
            nested = _category_from_exception(reason)
            return "network_error" if nested == "unknown_error" else nested
        return "network_error"
    if isinstance(
        exc,
        (ConnectionError, ConnectionRefusedError, ConnectionResetError, socket.gaierror),
    ):
        return "network_error"

    names = {item.__name__.lower() for item in type(exc).__mro__}
    if names & {"authenticationerror", "unauthorizederror"}:
        return "authentication_failed"
    if names & {"permissiondeniederror", "forbiddenerror"}:
        return "permission_denied"
    if names & {"notfounderror"}:
        return "not_found"
    if names & {"ratelimiterror", "toomanyrequestserror"}:
        return "rate_limited"
    if any("timeout" in name for name in names):
        return "timeout"
    if any("ssl" in name or "certificate" in name for name in names):
        return "ssl_error"
    if any(
        marker in name
        for name in names
        for marker in ("connection", "connecterror", "network", "dns", "proxy")
    ):
        return "network_error"
    if names & {"badrequesterror", "invalidrequesterror"}:
        return "bad_request"

    message = str(exc).lower()
    if "certificate verify failed" in message or "ssl handshake" in message:
        return "ssl_error"
    if "timed out" in message or "timeout" in message:
        return "timeout"
    if any(
        marker in message
        for marker in ("getaddrinfo", "name or service not known", "connection refused")
    ):
        return "network_error"
    return "unknown_error"


def _http_status(exc: BaseException) -> int | None:
    for source in (exc, _safe_attribute(exc, "response")):
        if source is None:
            continue
        for attribute in ("status_code", "status", "code"):
            value = _safe_attribute(source, attribute)
            if isinstance(value, bool):
                continue
            try:
                status = int(value)
            except (TypeError, ValueError):
                continue
            if 100 <= status <= 599:
                return status
    return None


def _safe_attribute(value: Any, name: str) -> Any:
    try:
        return getattr(value, name, None)
    except Exception:
        return None
