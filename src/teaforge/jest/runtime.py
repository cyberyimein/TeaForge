"""Capture observed Jest assertion evidence without modifying the target project."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from teaforge.jest.project import JestProject
from teaforge.pcl.assembly import build_output_rows
from teaforge.pcl.models import PCLAssertionEvidence, PCLDocument, PCLTestCase
from teaforge.process import WorkflowDeadline, bounded_process_detail

EVIDENCE_MODES = ("static", "runtime", "auto")
EVIDENCE_SCHEMA_VERSION = 1
MAX_EVIDENCE_FILE_BYTES = 6 * 1024 * 1024
MAX_EVIDENCE_RECORDS = 6000


@dataclass(slots=True, frozen=True)
class JestAssertionEvidence:
    test_name: str
    test_path: str
    matcher: str
    expected: list[str]
    actual: str
    passed: bool
    negated: bool = False
    promise_mode: str = ""
    error: str = ""


@dataclass(slots=True, frozen=True)
class JestEvidenceRun:
    evidence: list[JestAssertionEvidence]
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    warnings: tuple[str, ...] = ()

    @property
    def tests_passed(self) -> bool:
        return self.exit_code == 0


class JestRuntimeEvidenceUnavailableError(RuntimeError):
    """Runtime evidence cannot start or the target uses unsupported assertion hooks."""

    code = "jest-runtime-evidence-unavailable"


def normalize_evidence_mode(mode: str) -> str:
    normalized = mode.strip().lower()
    if normalized not in EVIDENCE_MODES:
        supported = ", ".join(EVIDENCE_MODES)
        raise ValueError(f"Unsupported evidence mode: {mode}. Supported values: {supported}")
    return normalized


def capture_jest_assertions(
    test_path: Path,
    *,
    timeout_seconds: int = 120,
) -> list[JestAssertionEvidence]:
    """Compatibility wrapper returning only assertions from one Jest evidence run."""
    return capture_jest_run(
        test_path,
        timeout_seconds=timeout_seconds,
    ).evidence


def capture_jest_run(
    test_path: Path,
    *,
    timeout_seconds: int = 120,
) -> JestEvidenceRun:
    """Execute project-local Jest and preserve both evidence and process status."""
    try:
        project = JestProject.discover(test_path)
    except RuntimeError as exc:
        raise JestRuntimeEvidenceUnavailableError(str(exc)) from exc
    deadline = WorkflowDeadline.start(
        "Jest runtime evidence workflow",
        timeout_seconds,
    )
    setup_files = project.setup_files_after_env(
        timeout_seconds=deadline.remaining_seconds()
    )

    import tempfile

    with tempfile.TemporaryDirectory(prefix="teaforge-jest-evidence-") as temp_dir:
        evidence_path = Path(temp_dir) / "assertions.jsonl"
        listener_resource = resources.files("teaforge.jest.assets").joinpath(
            "runtime-listener.cjs"
        )
        with resources.as_file(listener_resource) as listener_path:
            command = [
                "--runInBand",
                "--runTestsByPath",
                *[str(path) for path in project.test_files],
            ]
            for setup_file in [*setup_files, str(listener_path)]:
                command.extend(["--setupFilesAfterEnv", setup_file])
            environment = os.environ.copy()
            environment["TEAFORGE_JEST_EVIDENCE_PATH"] = str(evidence_path)
            result = project.run(
                command,
                timeout_seconds=deadline.remaining_seconds(),
                operation="Jest runtime evidence",
                environment=environment,
            )

        evidence, warnings = load_jest_evidence(evidence_path)
        if evidence:
            return JestEvidenceRun(
                evidence=evidence,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                warnings=tuple(warnings),
            )

        detail = bounded_process_detail(result.stderr, result.stdout)
        if result.returncode != 0:
            raise RuntimeError(
                "Jest failed before TeaForge captured assertion evidence. "
                f"Exit code: {result.returncode}. {detail}"
            )
        raise JestRuntimeEvidenceUnavailableError(
            "Jest completed but no supported expect() assertions were observed. "
            "Use --evidence-mode static for tests that import a separate expect implementation."
        )


def enrich_documents_with_runtime_evidence(
    documents: list[PCLDocument],
    evidence: list[JestAssertionEvidence],
) -> int:
    """Attach observed assertions to statically parsed testcases without replacing design intent."""
    matched_count = 0
    for document in documents:
        document_changed = False
        for case in document.testcases:
            matches = [
                item
                for item in evidence
                if _evidence_matches_case(item, case, document.test_file)
            ]
            if not matches:
                continue
            case.assertion_evidence = [
                PCLAssertionEvidence(
                    matcher=item.matcher,
                    expected=item.expected,
                    actual=item.actual,
                    passed=item.passed,
                    negated=item.negated,
                    promise_mode=item.promise_mode,
                    error=item.error,
                )
                for item in matches
            ]
            case.execution_status = (
                "passed" if all(item.passed for item in matches) else "failed"
            )
            case.runtime_test_name = matches[0].test_name
            case.runtime_test_path = matches[0].test_path
            document_changed = True
            matched_count += 1
        if document_changed:
            document.output_rows = build_output_rows(document.testcases)
    return matched_count


def load_jest_assertions(path: Path) -> list[JestAssertionEvidence]:
    """Load assertion records while preserving the historical list-only API."""
    evidence, _warnings = load_jest_evidence(path)
    return evidence


def load_jest_evidence(
    path: Path,
) -> tuple[list[JestAssertionEvidence], list[str]]:
    """Load bounded, versioned assertion evidence and producer warnings."""
    if not path.exists():
        return [], []
    file_size = path.stat().st_size
    if file_size > MAX_EVIDENCE_FILE_BYTES:
        raise RuntimeError(
            "Jest evidence file is too large to load safely: "
            f"{file_size} bytes (limit: {MAX_EVIDENCE_FILE_BYTES})."
        )
    evidence: list[JestAssertionEvidence] = []
    warnings: list[str] = []
    with path.open(encoding="utf-8") as evidence_file:
        for line_number, raw_line in enumerate(evidence_file, start=1):
            if line_number > MAX_EVIDENCE_RECORDS:
                raise RuntimeError(
                    "Jest evidence contains too many records to load safely "
                    f"(limit: {MAX_EVIDENCE_RECORDS})."
                )
            if not raw_line.strip():
                continue
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Invalid Jest evidence JSON on line {line_number}: {exc.msg}"
                ) from exc
            if payload.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
                raise RuntimeError(
                    "Unsupported Jest evidence schema on line "
                    f"{line_number}: {payload.get('schema_version')!r}."
                )
            kind = payload.get("kind")
            if kind == "warning":
                message = str(payload.get("message", "Jest evidence was truncated."))
                warnings.append(message)
                continue
            if kind != "assertion":
                raise RuntimeError(
                    f"Unsupported Jest evidence record kind on line {line_number}: {kind!r}."
                )
            expected = payload.get("expected", [])
            if not isinstance(expected, list):
                raise RuntimeError(
                    f"Invalid Jest evidence expected values on line {line_number}: list required."
                )
            evidence.append(
                JestAssertionEvidence(
                    test_name=str(payload.get("test_name", "")),
                    test_path=str(payload.get("test_path", "")),
                    matcher=str(payload.get("matcher", "")),
                    expected=[str(value) for value in expected],
                    actual=str(payload.get("actual", "")),
                    passed=bool(payload.get("passed", False)),
                    negated=bool(payload.get("negated", False)),
                    promise_mode=str(payload.get("promise_mode", "")),
                    error=str(payload.get("error", "")),
                )
            )
    return evidence, warnings


def _evidence_matches_case(
    evidence: JestAssertionEvidence,
    testcase: PCLTestCase,
    document_test_file: str,
) -> bool:
    if testcase.test_full_name:
        name_matches = evidence.test_name == testcase.test_full_name
    else:
        name_matches = evidence.test_name.endswith(testcase.testcase)
    if not name_matches:
        return False
    if not evidence.test_path:
        return True
    if testcase.test_source_path:
        return Path(evidence.test_path).resolve() == Path(
            testcase.test_source_path
        ).resolve()
    if document_test_file.startswith("複数"):
        return True
    return Path(evidence.test_path).name == document_test_file
