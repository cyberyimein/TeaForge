"""Dispatch PCL parsing to a framework-specific backend."""

from __future__ import annotations

from pathlib import Path

from .models import PCLDocument
from .parser import parse_pytest_documents

SUPPORTED_PCL_FRAMEWORKS = ("pytest", "jest", "angular", "playwright")


def normalize_pcl_framework(framework: str) -> str:
    """Normalize and validate the requested PCL parsing backend."""
    normalized = framework.strip().lower()
    if normalized not in SUPPORTED_PCL_FRAMEWORKS:
        supported = ", ".join(SUPPORTED_PCL_FRAMEWORKS)
        raise ValueError(f"Unsupported framework: {framework}. Supported values: {supported}")
    return normalized


def parse_documents_for_framework(test_path: Path, framework: str) -> list[PCLDocument]:
    """Route one test path through the selected framework parser."""
    normalized = normalize_pcl_framework(framework)
    if normalized == "pytest":
        return parse_pytest_documents(test_path)

    if normalized == "angular":
        from teaforge.angular.parser import parse_angular_documents

        return parse_angular_documents(test_path)

    if normalized == "playwright":
        from teaforge.playwright.parser import parse_playwright_documents

        return parse_playwright_documents(test_path)

    from teaforge.jest.parser import parse_jest_documents

    return parse_jest_documents(test_path)