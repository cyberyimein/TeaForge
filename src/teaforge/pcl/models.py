"""Define the serialized data contract for generated PCL documents."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

PCL_SCHEMA_VERSION = 1


@dataclass(slots=True)
class PCLMatrixRow:
    category: str
    item: str
    value: str
    values: dict[str, str]


@dataclass(slots=True)
class PCLAssertionEvidence:
    matcher: str
    expected: list[str]
    actual: str
    passed: bool
    negated: bool = False
    promise_mode: str = ""
    source: str = "jest-runtime"
    error: str = ""


@dataclass(slots=True)
class PCLTestCase:
    testcase: str
    testname: str
    testcasecode: str
    inputs: dict[str, str]
    output: str
    type: str
    screen_name: str = ""
    entry_url: str = ""
    preconditions: list[str] = field(default_factory=list)
    input_actions: list[str] = field(default_factory=list)
    ui_outputs: list[str] = field(default_factory=list)
    navigation_outputs: list[str] = field(default_factory=list)
    verification_mode: str = ""
    output_checks: list[str] = field(default_factory=list)
    test_full_name: str = ""
    test_source_path: str = ""
    assertion_evidence: list[PCLAssertionEvidence] = field(default_factory=list)
    execution_status: str = ""
    runtime_test_name: str = ""
    runtime_test_path: str = ""
    executed_date: str = ""
    bug_number: str = ""


@dataclass(slots=True)
class PCLDocument:
    title: str
    file: str
    method: str
    source_path: str
    test_file: str
    test_method: str
    test_source_path: str
    generated_at: str
    schema_version: int = PCL_SCHEMA_VERSION
    evidence_mode: str = "static"
    evidence_warnings: list[str] = field(default_factory=list)
    runtime_exit_code: int | None = None
    runtime_tests_passed: bool | None = None
    sheet_number: int = 1
    sheet_count: int = 1
    testcases: list[PCLTestCase] = field(default_factory=list)
    input_rows: list[PCLMatrixRow] = field(default_factory=list)
    output_rows: list[PCLMatrixRow] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        file: str,
        method: str,
        source_path: str,
        *,
        test_file: str | None = None,
        test_method: str | None = None,
        test_source_path: str | None = None,
    ) -> "PCLDocument":
        """Create a document with consistent defaults for generation and lookup flows."""
        return cls(
            title="プログラムチェックリスト",
            file=file,
            method=method,
            source_path=source_path,
            test_file=test_file or file,
            test_method=test_method or method,
            test_source_path=test_source_path or source_path,
            generated_at=datetime.now(UTC).isoformat(),
            schema_version=PCL_SCHEMA_VERSION,
            evidence_mode="static",
            evidence_warnings=[],
            runtime_exit_code=None,
            runtime_tests_passed=None,
            sheet_number=1,
            sheet_count=1,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the document and nested dataclasses into plain dictionaries."""
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PCLDocument":
        """Rebuild the nested dataclasses from JSON payloads embedded in reports."""
        schema_version = int(payload.get("schema_version", 0))
        if schema_version not in (0, PCL_SCHEMA_VERSION):
            raise ValueError(
                f"Unsupported PCL schema version: {schema_version}. "
                f"This TeaForge release supports version {PCL_SCHEMA_VERSION}."
            )
        return cls(
            title=payload["title"],
            file=payload["file"],
            method=payload["method"],
            source_path=payload["source_path"],
            test_file=payload.get("test_file", payload["file"]),
            test_method=payload.get("test_method", payload["method"]),
            test_source_path=payload.get("test_source_path", payload["source_path"]),
            generated_at=payload["generated_at"],
            schema_version=PCL_SCHEMA_VERSION,
            evidence_mode=payload.get("evidence_mode", "static"),
            evidence_warnings=payload.get("evidence_warnings", []),
            runtime_exit_code=payload.get("runtime_exit_code"),
            runtime_tests_passed=payload.get("runtime_tests_passed"),
            sheet_number=payload.get("sheet_number", 1),
            sheet_count=payload.get("sheet_count", 1),
            testcases=[
                PCLTestCase(
                    testcase=row["testcase"],
                    testname=row["testname"],
                    testcasecode=row["testcasecode"],
                    inputs=row.get("inputs", {}),
                    output=row.get("output", ""),
                    type=row.get("type", "N"),
                    screen_name=row.get("screen_name", ""),
                    entry_url=row.get("entry_url", ""),
                    preconditions=row.get("preconditions", []),
                    input_actions=row.get("input_actions", []),
                    ui_outputs=row.get("ui_outputs", []),
                    navigation_outputs=row.get("navigation_outputs", []),
                    verification_mode=row.get("verification_mode", ""),
                    output_checks=row.get("output_checks", []),
                    test_full_name=row.get("test_full_name", ""),
                    test_source_path=row.get("test_source_path", ""),
                    assertion_evidence=[
                        PCLAssertionEvidence(
                            matcher=evidence.get("matcher", ""),
                            expected=evidence.get("expected", []),
                            actual=evidence.get("actual", ""),
                            passed=bool(evidence.get("passed", False)),
                            negated=bool(evidence.get("negated", False)),
                            promise_mode=evidence.get("promise_mode", ""),
                            source=evidence.get("source", "jest-runtime"),
                            error=evidence.get("error", ""),
                        )
                        for evidence in row.get("assertion_evidence", [])
                    ],
                    execution_status=row.get("execution_status", ""),
                    runtime_test_name=row.get("runtime_test_name", ""),
                    runtime_test_path=row.get("runtime_test_path", ""),
                    executed_date=row.get("executed_date", ""),
                    bug_number=row.get("bug_number", ""),
                )
                for row in payload.get("testcases", [])
            ],
            input_rows=[PCLMatrixRow(**row) for row in payload.get("input_rows", [])],
            output_rows=[PCLMatrixRow(**row) for row in payload.get("output_rows", [])],
        )
