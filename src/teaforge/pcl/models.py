"""Define the serialized data contract for generated PCL documents."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(slots=True)
class PCLMatrixRow:
    category: str
    item: str
    value: str
    values: dict[str, str]


@dataclass(slots=True)
class PCLTestCase:
    testcase: str
    testname: str
    testcasecode: str
    inputs: dict[str, str]
    output: str
    type: str
    output_checks: list[str] = field(default_factory=list)
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
            sheet_number=1,
            sheet_count=1,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the document and nested dataclasses into plain dictionaries."""
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PCLDocument":
        """Rebuild the nested dataclasses from JSON payloads embedded in reports."""
        return cls(
            title=payload["title"],
            file=payload["file"],
            method=payload["method"],
            source_path=payload["source_path"],
            test_file=payload.get("test_file", payload["file"]),
            test_method=payload.get("test_method", payload["method"]),
            test_source_path=payload.get("test_source_path", payload["source_path"]),
            generated_at=payload["generated_at"],
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
                    output_checks=row.get("output_checks", []),
                    executed_date=row.get("executed_date", ""),
                    bug_number=row.get("bug_number", ""),
                )
                for row in payload.get("testcases", [])
            ],
            input_rows=[PCLMatrixRow(**row) for row in payload.get("input_rows", [])],
            output_rows=[PCLMatrixRow(**row) for row in payload.get("output_rows", [])],
        )
