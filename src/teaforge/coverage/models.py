from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(slots=True)
class CoverageMetric:
    covered: int
    total: int
    percent: float
    missing: int = 0


@dataclass(slots=True)
class FunctionCoverage:
    name: str
    lineno: int
    end_lineno: int
    page_number: int | None
    c0: CoverageMetric
    c1: CoverageMetric
    missing_lines: list[int] = field(default_factory=list)
    missing_branches: list[str] = field(default_factory=list)
    diagram_included: bool = False
    mermaid_path: str = ""
    svg_path: str = ""
    svg_data_uri: str = ""


@dataclass(slots=True)
class CoverageDocument:
    title: str
    file: str
    source_path: str
    test_path: str
    generated_at: str
    page_count: int
    c0: CoverageMetric
    c1: CoverageMetric
    requested_functions: list[str] = field(default_factory=list)
    functions: list[FunctionCoverage] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        file: str,
        source_path: str,
        test_path: str,
        c0: CoverageMetric,
        c1: CoverageMetric,
        requested_functions: list[str],
        functions: list[FunctionCoverage],
    ) -> "CoverageDocument":
        return cls(
            title="Coverage Report",
            file=file,
            source_path=source_path,
            test_path=test_path,
            generated_at=datetime.now(UTC).isoformat(),
            page_count=max(1, 1 + sum(1 for function in functions if function.page_number is not None)),
            c0=c0,
            c1=c1,
            requested_functions=requested_functions,
            functions=functions,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
