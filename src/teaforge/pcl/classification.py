"""Classify testcase intent from naming hints when pytest metadata is limited."""

from __future__ import annotations


NORMAL_HINTS = ("normal", "success", "valid", "ok", "happy")
BOUNDARY_HINTS = ("boundary", "edge", "limit", "min", "max")
EXCEPTION_HINTS = (
    "exception",
    "error",
    "invalid",
    "not_found",
    "missing",
    "duplicate",
    "empty",
    "none",
    "fail",
)


def classify_type(*tokens: str) -> str:
    """Map free-form testcase hints to the Japanese PCL type codes."""
    normalized = " ".join(tokens).lower()
    if any(keyword in normalized for keyword in EXCEPTION_HINTS):
        return "E"
    if any(keyword in normalized for keyword in BOUNDARY_HINTS):
        return "I"
    if any(keyword in normalized for keyword in NORMAL_HINTS):
        return "N"
    return "N"

