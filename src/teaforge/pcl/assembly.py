"""Assemble framework-neutral test evidence into PCL documents and matrices."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import replace

from .models import PCLDocument, PCLMatrixRow, PCLTestCase


def merge_documents_by_subject(documents: list[PCLDocument]) -> list[PCLDocument]:
    """Group intermediate documents by their inferred production subject."""
    grouped: OrderedDict[tuple[str, str, str], list[PCLDocument]] = OrderedDict()
    for document in documents:
        key = (document.file, document.method, document.source_path)
        grouped.setdefault(key, []).append(document)

    return [
        related[0] if len(related) == 1 else _merge_related_documents(related)
        for related in grouped.values()
    ]


def build_input_rows(cases: list[PCLTestCase]) -> list[PCLMatrixRow]:
    """Build the PCL input matrix rows from testcase input values."""
    row_hits: OrderedDict[tuple[str, str], dict[str, str]] = OrderedDict()
    for case in cases:
        for item, value in case.inputs.items():
            key = (item, value)
            row_hits.setdefault(key, {})
            row_hits[key][case.testcasecode] = "○"

    return _build_rows("input", cases, row_hits)


def build_output_rows(cases: list[PCLTestCase]) -> list[PCLMatrixRow]:
    """Build the PCL output matrix rows from testcase assertions."""
    row_hits: OrderedDict[tuple[str, str], dict[str, str]] = OrderedDict()
    for case in cases:
        checks = case.output_checks or ([case.output] if case.output else [])
        for check in checks:
            item, value = _split_output_check(check)
            key = (item, value)
            row_hits.setdefault(key, {})
            row_hits[key][case.testcasecode] = "○"

    return _build_rows("output", cases, row_hits)


def _merge_related_documents(documents: list[PCLDocument]) -> PCLDocument:
    """Merge test documents that target the same production subject."""
    first = documents[0]
    merged = PCLDocument.create(
        file=first.file,
        method=first.method,
        source_path=first.source_path,
        test_file=_merge_source_labels([document.test_file for document in documents]),
        test_method=_merge_source_labels([document.test_method for document in documents]),
        test_source_path=_merge_source_labels(
            [document.test_source_path for document in documents]
        ),
    )
    merged.generated_at = first.generated_at

    case_idx = 1
    for document in documents:
        for case in document.testcases:
            merged.testcases.append(replace(case, testcasecode=f"TC-{case_idx:03d}"))
            case_idx += 1

    merged.input_rows = build_input_rows(merged.testcases)
    merged.output_rows = build_output_rows(merged.testcases)
    return merged


def _merge_source_labels(values: list[str]) -> str:
    unique_values = list(dict.fromkeys(value for value in values if value))
    if not unique_values:
        return ""
    if len(unique_values) == 1:
        return unique_values[0]
    return f"複数 ({len(unique_values)} 件)"


def _build_rows(
    category: str,
    cases: list[PCLTestCase],
    row_hits: OrderedDict[tuple[str, str], dict[str, str]],
) -> list[PCLMatrixRow]:
    rows: list[PCLMatrixRow] = []
    for (item, value), hits in _group_keys_by_item(row_hits).items():
        rows.append(
            PCLMatrixRow(
                category=category,
                item=item,
                value=value,
                values={case.testcasecode: hits.get(case.testcasecode, "") for case in cases},
            )
        )
    return rows


def _split_output_check(check: str) -> tuple[str, str]:
    if check.startswith("raises "):
        return ("raises", check.removeprefix("raises ").strip())
    if " == " in check:
        left, right = check.split(" == ", 1)
        return (left.strip(), right.strip())
    return ("assertion", check)


def _group_keys_by_item(
    row_hits: OrderedDict[tuple[str, str], dict[str, str]],
) -> OrderedDict[tuple[str, str], dict[str, str]]:
    item_groups: OrderedDict[
        str, list[tuple[tuple[str, str], dict[str, str]]]
    ] = OrderedDict()
    for key, hits in row_hits.items():
        item_groups.setdefault(key[0], []).append((key, hits))

    grouped: OrderedDict[tuple[str, str], dict[str, str]] = OrderedDict()
    for entries in item_groups.values():
        for key, hits in entries:
            grouped[key] = hits
    return grouped
