"""Detect worker authentication failures and turn them into a clear diagnostic.

CLI workers (claude/codex/opencode) fail with a generic non-zero exit when their
credentials are missing or invalid. Surfacing that as a specific `blocked` reason
(instead of an opaque "failed") tells the operator exactly what to fix.
"""

from __future__ import annotations

_AUTH_MARKERS = (
    "authentication_error",
    "invalid authentication credentials",
    "failed to authenticate",
    "unauthorized",
    "not logged in",
    "no api key",
    "api key not",
    "invalid api key",
    "401 unauthorized",
)


def detect_auth_failure(*texts: str) -> str | None:
    """Return an actionable diagnostic if any text shows an auth failure, else None."""
    blob = " ".join(t for t in texts if t).lower()
    if any(marker in blob for marker in _AUTH_MARKERS):
        return (
            "Worker authentication failed. Configure the worker's credentials "
            "(e.g. set ANTHROPIC_API_KEY / OPENAI_API_KEY, or run the worker's login "
            "for headless use) and retry."
        )
    return None
