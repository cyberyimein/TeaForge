from __future__ import annotations

import ast
from collections import OrderedDict
from pathlib import Path
from typing import Any

from .classification import classify_type
from .models import PCLDocument, PCLMatrixRow, PCLTestCase

KNOWN_FIXTURE_NAMES = {
    "cache",
    "capfd",
    "capfdbinary",
    "capsys",
    "capsysbinary",
    "client",
    "monkeypatch",
    "request",
    "tmp_path",
    "tmp_path_factory",
}
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def parse_pytest_documents(pytest_path: Path) -> list[PCLDocument]:
    files = _collect_test_files(pytest_path)
    if not files:
        raise ValueError(f"No pytest files found under: {pytest_path}")

    documents: list[PCLDocument] = []
    for file_path in files:
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
                "test_"
            ):
                documents.append(_build_document_for_function(file_path, node))

    return documents


def parse_pytest_path(pytest_path: Path) -> PCLDocument:
    documents = parse_pytest_documents(pytest_path)
    if len(documents) == 1:
        return documents[0]

    merged = PCLDocument.create(
        file=documents[0].file if len({doc.file for doc in documents}) == 1 else f"複数 ({len(documents)} ファイル)",
        method=f"複数 ({len(documents)} メソッド)",
        source_path=str(pytest_path),
    )
    case_idx = 1
    for document in documents:
        for case in document.testcases:
            merged.testcases.append(
                PCLTestCase(
                    testcase=case.testcase,
                    testname=case.testname,
                    testcasecode=f"TC-{case_idx:03d}",
                    inputs=case.inputs,
                    output=case.output,
                    type=case.type,
                    output_checks=case.output_checks,
                    executed_date=case.executed_date,
                    bug_number=case.bug_number,
                )
            )
            case_idx += 1

    merged.input_rows = _build_input_rows(merged.testcases)
    merged.output_rows = _build_output_rows(merged.testcases)
    return merged


def _build_document_for_function(
    file_path: Path,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> PCLDocument:
    document = PCLDocument.create(
        file=file_path.name,
        method=node.name,
        source_path=_display_path(file_path),
    )

    for case_idx, case in enumerate(_extract_cases_from_function(node), start=1):
        document.testcases.append(
            PCLTestCase(
                testcase=case["testcase"],
                testname=case["testname"],
                testcasecode=f"TC-{case_idx:03d}",
                inputs=case["inputs"],
                output=case["output"],
                type=case["type"],
                output_checks=case["output_checks"],
            )
        )

    document.input_rows = _build_input_rows(document.testcases)
    document.output_rows = _build_output_rows(document.testcases)
    return document


def _collect_test_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if _is_test_file(path) else []
    return sorted(file for file in path.rglob("*.py") if _is_test_file(file))


def _is_test_file(path: Path) -> bool:
    name = path.name
    return name.startswith("test_") or name.endswith("_test.py")


def _extract_cases_from_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[dict[str, Any]]:
    docstring = ast.get_docstring(node) or ""
    testcase_title = docstring.splitlines()[0].strip() if docstring else _to_title(node.name)
    markers = _extract_markers(node.decorator_list)
    output_checks = _extract_output_expectations(node)
    output_expectation = "; ".join(output_checks) if output_checks else "明示的な assert はありません"
    parametrize = _extract_parametrize(node.decorator_list)
    input_templates = _extract_input_templates(node)

    if not parametrize:
        inputs = _build_case_inputs({}, input_templates)
        return [
            {
                "testcase": testcase_title,
                "testname": node.name,
                "inputs": inputs,
                "output": output_expectation,
                "output_checks": output_checks,
                "type": classify_type(" ".join(markers), node.name, docstring, output_expectation),
            }
        ]

    ids = parametrize["ids"]
    raw_rows = parametrize["rows"]
    cases: list[dict[str, Any]] = []
    for idx, raw_row in enumerate(raw_rows):
        case_id = ids[idx] if idx < len(ids) else f"case_{idx + 1}"
        cases.append(
            {
                "testcase": testcase_title,
                "testname": f"{node.name}[{case_id}]",
                "inputs": _build_case_inputs(raw_row, input_templates),
                "output": output_expectation,
                "output_checks": output_checks,
                "type": classify_type(
                    " ".join(markers),
                    node.name,
                    docstring,
                    case_id,
                    output_expectation,
                ),
            }
        )
    return cases


def _extract_markers(decorators: list[ast.expr]) -> list[str]:
    markers: list[str] = []
    for dec in decorators:
        target = dec.func if isinstance(dec, ast.Call) else dec
        marker = _extract_marker_name(target)
        if marker:
            markers.append(marker)
    return markers


def _extract_marker_name(expr: ast.expr) -> str | None:
    if isinstance(expr, ast.Attribute):
        chain = _attr_chain(expr)
        if len(chain) >= 3 and chain[0] == "pytest" and chain[1] == "mark":
            return chain[2]
    return None


def _extract_parametrize(decorators: list[ast.expr]) -> dict[str, Any] | None:
    for dec in decorators:
        if not isinstance(dec, ast.Call):
            continue
        if not _is_pytest_parametrize(dec.func):
            continue
        if len(dec.args) < 2:
            continue
        argnames = _parse_argnames(dec.args[0])
        rows = _parse_rows(argnames, dec.args[1])
        ids = _parse_ids(dec.keywords)
        return {"argnames": argnames, "rows": rows, "ids": ids}
    return None


def _is_pytest_parametrize(func: ast.expr) -> bool:
    if isinstance(func, ast.Attribute):
        return _attr_chain(func) == ["pytest", "mark", "parametrize"]
    return False


def _parse_argnames(node: ast.expr) -> list[str]:
    value = _evaluate_node(node, {})
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(part).strip() for part in value]
    return ["value"]


def _parse_rows(argnames: list[str], node: ast.expr) -> list[dict[str, Any]]:
    value = _evaluate_node(node, {})
    if len(argnames) == 1:
        if isinstance(value, (list, tuple)):
            return [{argnames[0]: item} for item in value]
        return [{argnames[0]: value}]

    if not isinstance(value, (list, tuple)):
        return [{arg: "<unsupported>" for arg in argnames}]

    rows: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, (list, tuple)) and len(item) == len(argnames):
            rows.append({arg: raw for arg, raw in zip(argnames, item)})
        else:
            rows.append({arg: "<unsupported>" for arg in argnames})
    return rows


def _parse_ids(keywords: list[ast.keyword]) -> list[str]:
    for keyword in keywords:
        if keyword.arg != "ids":
            continue
        value = _evaluate_node(keyword.value, {})
        if isinstance(value, (list, tuple)):
            return [_to_text(item) for item in value]
    return []


def _extract_input_templates(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> OrderedDict[str, list[ast.expr]]:
    templates: OrderedDict[str, list[ast.expr]] = OrderedDict()
    calls = [
        child for child in ast.walk(node) if isinstance(child, ast.Call)
    ]
    calls.sort(key=lambda child: (getattr(child, "lineno", 0), getattr(child, "col_offset", 0)))
    for child in calls:
        if not isinstance(child, ast.Call):
            continue
        if not isinstance(child.func, ast.Attribute) or child.func.attr not in HTTP_METHODS:
            continue
        for keyword in child.keywords:
            if keyword.arg == "json" and isinstance(keyword.value, ast.Dict):
                _append_dict_template(templates, keyword.value)
            if keyword.arg == "params" and isinstance(keyword.value, ast.Dict):
                _append_dict_template(templates, keyword.value)
    return templates


def _append_dict_template(
    templates: OrderedDict[str, list[ast.expr]],
    payload: ast.Dict,
) -> None:
    for key_node, value_node in zip(payload.keys, payload.values):
        if key_node is None:
            continue
        key_value = _evaluate_node(key_node, {})
        if not isinstance(key_value, str):
            continue
        templates.setdefault(key_value, []).append(value_node)


def _build_case_inputs(
    raw_row: dict[str, Any],
    input_templates: OrderedDict[str, list[ast.expr]],
) -> dict[str, str]:
    inputs: OrderedDict[str, str] = OrderedDict()
    for key, expr_nodes in input_templates.items():
        rendered_values = [_render_input_value(expr, raw_row) for expr in expr_nodes]
        unique_values = _dedupe_preserve_order(value for value in rendered_values if value)
        if unique_values:
            inputs[key] = " -> ".join(unique_values)

    if inputs:
        return dict(inputs)

    for key, value in raw_row.items():
        if key in KNOWN_FIXTURE_NAMES:
            continue
        text = _to_text(value)
        if text:
            inputs[key] = text
    return dict(inputs)


def _extract_output_expectations(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    expectations: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Assert):
            expectations.append(ast.unparse(child.test))
        if isinstance(child, ast.With):
            expectations.extend(_extract_raises_expectation(child.items))
    return expectations


def _extract_raises_expectation(items: list[ast.withitem]) -> list[str]:
    expectations: list[str] = []
    for item in items:
        context_expr = item.context_expr
        if not isinstance(context_expr, ast.Call):
            continue
        if not isinstance(context_expr.func, ast.Attribute):
            continue
        if _attr_chain(context_expr.func) != ["pytest", "raises"]:
            continue
        if context_expr.args:
            expectations.append(f"raises {ast.unparse(context_expr.args[0])}")
    return expectations


def _build_input_rows(cases: list[PCLTestCase]) -> list[PCLMatrixRow]:
    row_hits: OrderedDict[tuple[str, str], dict[str, str]] = OrderedDict()
    for case in cases:
        for item, value in case.inputs.items():
            key = (item, value)
            row_hits.setdefault(key, {})
            row_hits[key][case.testcasecode] = "○"

    rows: list[PCLMatrixRow] = []
    for (item, value), hits in _group_keys_by_item(row_hits).items():
        rows.append(
            PCLMatrixRow(
                category="input",
                item=item,
                value=value,
                values={case.testcasecode: hits.get(case.testcasecode, "") for case in cases},
            )
        )
    return rows


def _build_output_rows(cases: list[PCLTestCase]) -> list[PCLMatrixRow]:
    row_hits: OrderedDict[tuple[str, str], dict[str, str]] = OrderedDict()
    for case in cases:
        checks = case.output_checks or ([case.output] if case.output else [])
        for check in checks:
            item, value = _split_output_check(check)
            key = (item, value)
            row_hits.setdefault(key, {})
            row_hits[key][case.testcasecode] = "○"

    rows: list[PCLMatrixRow] = []
    for (item, value), hits in _group_keys_by_item(row_hits).items():
        rows.append(
            PCLMatrixRow(
                category="output",
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
    item_groups: OrderedDict[str, list[tuple[tuple[str, str], dict[str, str]]]] = OrderedDict()
    for key, hits in row_hits.items():
        item_groups.setdefault(key[0], []).append((key, hits))

    grouped: OrderedDict[tuple[str, str], dict[str, str]] = OrderedDict()
    for entries in item_groups.values():
        for key, hits in entries:
            grouped[key] = hits
    return grouped


def _evaluate_node(node: ast.AST, context: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return context.get(node.id, ast.unparse(node))
    if isinstance(node, ast.List):
        return [_evaluate_node(item, context) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_evaluate_node(item, context) for item in node.elts)
    if isinstance(node, ast.Dict):
        return {
            _evaluate_node(key, context): _evaluate_node(value, context)
            for key, value in zip(node.keys, node.values)
            if key is not None
        }
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        operand = _evaluate_node(node.operand, context)
        if isinstance(operand, (int, float)):
            return -operand
    if isinstance(node, ast.BinOp):
        left = _evaluate_node(node.left, context)
        right = _evaluate_node(node.right, context)
        if isinstance(node.op, ast.Mult) and isinstance(left, str) and isinstance(right, int):
            return left * right
        if isinstance(node.op, ast.Mult) and isinstance(left, int) and isinstance(right, str):
            return left * right
        if isinstance(node.op, ast.Add) and isinstance(left, (str, int, float)) and isinstance(
            right, (str, int, float)
        ):
            return left + right
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            rendered = _evaluate_node(value, context)
            parts.append(_to_text(rendered))
        return "".join(parts)
    if isinstance(node, ast.FormattedValue):
        return _evaluate_node(node.value, context)
    return ast.unparse(node)


def _render_input_value(node: ast.AST, context: dict[str, Any]) -> str:
    if isinstance(node, ast.Name) and node.id not in context:
        return ""
    if isinstance(node, (ast.Subscript, ast.Call, ast.Lambda)):
        return ""
    rendered = _evaluate_node(node, context)
    text = _to_text(rendered)
    if text in KNOWN_FIXTURE_NAMES or text.startswith("<unsupported>"):
        return ""
    return text


def _attr_chain(expr: ast.Attribute) -> list[str]:
    chain: list[str] = []
    cursor: ast.expr = expr
    while isinstance(cursor, ast.Attribute):
        chain.append(cursor.attr)
        cursor = cursor.value
    if isinstance(cursor, ast.Name):
        chain.append(cursor.id)
    chain.reverse()
    return chain


def _dedupe_preserve_order(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return repr(value)


def _to_title(test_name: str) -> str:
    if test_name.startswith("test_"):
        test_name = test_name[5:]
    return test_name.replace("_", " ").strip().capitalize()


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)
