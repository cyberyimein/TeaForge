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


def parse_documents_for_framework(
    test_path: Path,
    framework: str,
    *,
    evidence_mode: str = "static",
    runtime_timeout: int = 120,
) -> list[PCLDocument]:
    """Route one test path through the selected framework parser."""
    normalized = normalize_pcl_framework(framework)
    if evidence_mode != "static" and normalized != "jest":
        raise ValueError("Runtime assertion evidence is currently supported only for Jest.")
    if normalized == "pytest":
        return parse_pytest_documents(test_path)

    if normalized == "angular":
        from teaforge.angular.parser import parse_angular_documents

        return parse_angular_documents(test_path)

    if normalized == "playwright":
        from teaforge.playwright.parser import parse_playwright_documents

        return parse_playwright_documents(test_path)

    from teaforge.jest.parser import parse_jest_documents
    from teaforge.jest.runtime import (
        JestRuntimeEvidenceUnavailableError,
        capture_jest_run,
        enrich_documents_with_runtime_evidence,
        normalize_evidence_mode,
    )

    mode = normalize_evidence_mode(evidence_mode)
    documents = parse_jest_documents(test_path)
    if mode == "static":
        return documents

    try:
        run = capture_jest_run(test_path, timeout_seconds=runtime_timeout)
        matched_count = enrich_documents_with_runtime_evidence(
            documents, run.evidence
        )
        if matched_count == 0:
            raise JestRuntimeEvidenceUnavailableError(
                "Jest produced assertion evidence, but it could not be matched to parsed testcases."
            )
    except JestRuntimeEvidenceUnavailableError as exc:
        if mode == "runtime":
            raise
        for document in documents:
            document.evidence_mode = "static-fallback"
            document.evidence_warnings.append(str(exc))
        return documents

    for document in documents:
        document.evidence_mode = "runtime"
        document.runtime_exit_code = run.exit_code
        document.runtime_tests_passed = run.tests_passed
        document.evidence_warnings.extend(run.warnings)
        if not run.tests_passed:
            document.evidence_warnings.append(
                f"Jest completed with failing tests (exit code {run.exit_code}); "
                "the report was generated from the captured failure evidence."
            )
    return documents
