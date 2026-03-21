"""Parse pytest files into PCL documents and infer the production subject under test."""

from __future__ import annotations

import ast
import re
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
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


@dataclass(slots=True, frozen=True)
class ImportedSymbol:
    file_path: Path | None
    original_name: str


@dataclass(slots=True, frozen=True)
class SubjectLocation:
    file: str
    method: str
    source_path: str


@dataclass(slots=True, frozen=True)
class HttpRoute:
    method: str
    path: str
    handler: str
    module_path: Path


def parse_pytest_documents(pytest_path: Path) -> list[PCLDocument]:
    """Build one logical PCL document per inferred production subject."""
    files = _collect_test_files(pytest_path)
    if not files:
        raise ValueError(f"No pytest files found under: {pytest_path}")

    raw_documents: list[PCLDocument] = []
    for file_path in files:
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        imports = _extract_imports(tree)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
                "test_"
            ):
                raw_documents.append(_build_document_for_function(file_path, node, imports))

    return _merge_documents_by_subject(raw_documents)


def parse_pytest_path(pytest_path: Path) -> PCLDocument:
    """Keep the legacy single-document view by merging all inferred subjects."""
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
    imports: dict[str, ImportedSymbol],
) -> PCLDocument:
    """Build one intermediate document from a single pytest function node."""
    subject = _infer_subject_location(file_path, node, imports)
    document = PCLDocument.create(
        file=subject.file,
        method=subject.method,
        source_path=subject.source_path,
        test_file=file_path.name,
        test_method=node.name,
        test_source_path=_display_path(file_path),
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


def _merge_documents_by_subject(documents: list[PCLDocument]) -> list[PCLDocument]:
    """Group intermediate documents by the inferred production subject."""
    grouped: OrderedDict[tuple[str, str, str], list[PCLDocument]] = OrderedDict()
    for document in documents:
        key = (document.file, document.method, document.source_path)
        grouped.setdefault(key, []).append(document)

    merged_documents: list[PCLDocument] = []
    for related_documents in grouped.values():
        if len(related_documents) == 1:
            merged_documents.append(related_documents[0])
            continue
        merged_documents.append(_merge_related_documents(related_documents))
    return merged_documents


def _merge_related_documents(documents: list[PCLDocument]) -> PCLDocument:
    """Merge multiple pytest functions that target the same production function."""
    first = documents[0]
    merged = PCLDocument.create(
        file=first.file,
        method=first.method,
        source_path=first.source_path,
        test_file=_merge_source_labels([document.test_file for document in documents]),
        test_method=_merge_source_labels([document.test_method for document in documents]),
        test_source_path=_merge_source_labels([document.test_source_path for document in documents]),
    )
    merged.generated_at = first.generated_at

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


def _merge_source_labels(values: list[str]) -> str:
    """Collapse multiple test source labels into one display string."""
    unique_values = _dedupe_preserve_order(value for value in values if value)
    if not unique_values:
        return ""
    if len(unique_values) == 1:
        return unique_values[0]
    return f"複数 ({len(unique_values)} 件)"


def _infer_subject_location(
    file_path: Path,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: dict[str, ImportedSymbol],
) -> SubjectLocation:
    """Infer the production file and function that the pytest function exercises."""
    # Prefer proof from imports and HTTP routes. The fallback keeps Step1 document generation
    # usable, but downstream coverage analysis rejects unresolved test-file subjects.
    subject = _infer_direct_call_subject(node, imports)
    if subject is not None:
        return subject

    subject = _infer_http_subject(node, imports)
    if subject is not None:
        return subject

    return SubjectLocation(
        file=file_path.name,
        method=node.name,
        source_path=_display_path(file_path),
    )


def _infer_direct_call_subject(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: dict[str, ImportedSymbol],
) -> SubjectLocation | None:
    """Infer the tested subject from imported function or module calls."""
    for call in _iter_calls_in_order(node):
        if isinstance(call.func, ast.Name):
            imported = imports.get(call.func.id)
            if imported is None or imported.file_path is None:
                continue
            subject = _resolve_symbol_subject(imported.file_path, imported.original_name)
            if subject is not None:
                return subject

        if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name):
            imported = imports.get(call.func.value.id)
            if imported is None or imported.file_path is None:
                continue
            subject = _resolve_symbol_subject(imported.file_path, call.func.attr)
            if subject is not None:
                return subject
    return None


def _infer_http_subject(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: dict[str, ImportedSymbol],
) -> SubjectLocation | None:
    """Infer the tested route handler from HTTP client calls in the test body."""
    routes = _collect_candidate_routes(imports)
    if not routes:
        return None

    matched_routes: list[HttpRoute] = []
    for call in _iter_calls_in_order(node):
        if not isinstance(call.func, ast.Attribute) or call.func.attr not in HTTP_METHODS:
            continue
        if not call.args:
            continue
        request_path = _extract_path_literal(call.args[0])
        if not request_path:
            continue
        for route in routes:
            if route.method != call.func.attr:
                continue
            if _route_matches(request_path, route.path):
                matched_routes.append(route)
                break

    if not matched_routes:
        return None

    preferred_methods = _preferred_http_methods(node.name)
    if preferred_methods:
        for route in reversed(matched_routes):
            if route.method in preferred_methods:
                return _subject_from_route(route)

    return _subject_from_route(matched_routes[-1])


def _subject_from_route(route: HttpRoute) -> SubjectLocation:
    """Convert a matched HTTP route into a standard subject descriptor."""
    return SubjectLocation(
        file=route.module_path.name,
        method=route.handler,
        source_path=_display_path(route.module_path),
    )


def _preferred_http_methods(test_name: str) -> set[str]:
    """Bias ambiguous route matches with the intent encoded in the test name."""
    lowered = test_name.lower()
    if "create_" in lowered:
        return {"post"}
    if "update_" in lowered:
        return {"put", "patch"}
    if "delete_" in lowered:
        return {"delete"}
    if "get_" in lowered or "read_" in lowered or "list_" in lowered:
        return {"get"}
    return set()


def _collect_candidate_routes(imports: dict[str, ImportedSymbol]) -> list[HttpRoute]:
    """Collect FastAPI-style route declarations from imported modules."""
    routes: list[HttpRoute] = []
    seen_modules: set[Path] = set()
    for imported in imports.values():
        if imported.file_path is None or imported.file_path in seen_modules:
            continue
        seen_modules.add(imported.file_path)
        routes.extend(_collect_http_routes(imported.file_path))
    return routes


def _iter_calls_in_order(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.Call]:
    """Return function calls in source order to preserve inference priority."""
    calls = [child for child in ast.walk(node) if isinstance(child, ast.Call)]
    calls.sort(key=lambda child: (getattr(child, "lineno", 0), getattr(child, "col_offset", 0)))
    return calls


def _collect_test_files(path: Path) -> list[Path]:
    """Expand a file or directory input into pytest-style test files."""
    if path.is_file():
        return [path] if _is_test_file(path) else []
    return sorted(file for file in path.rglob("*.py") if _is_test_file(file))


def _is_test_file(path: Path) -> bool:
    """Recognize the pytest file naming conventions supported by TeaForge."""
    name = path.name
    return name.startswith("test_") or name.endswith("_test.py")


def _extract_imports(tree: ast.Module) -> dict[str, ImportedSymbol]:
    """Map imported names in a test module to resolvable source files."""
    imports: dict[str, ImportedSymbol] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                bind_name = alias.asname or alias.name.split(".")[0]
                imports[bind_name] = ImportedSymbol(
                    file_path=_resolve_module_path(alias.name),
                    original_name=alias.name.rsplit(".", 1)[-1],
                )
        if isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            module_path = _resolve_module_path(module_name) if module_name else None
            for alias in node.names:
                if alias.name == "*":
                    continue
                bind_name = alias.asname or alias.name
                symbol_module_name = f"{module_name}.{alias.name}" if module_name else alias.name
                file_path = _resolve_module_path(symbol_module_name) or module_path
                imports[bind_name] = ImportedSymbol(
                    file_path=file_path,
                    original_name=alias.name,
                )
    return imports


@lru_cache(maxsize=None)
def _resolve_module_path(module_name: str) -> Path | None:
    """Resolve an import string to a local module or package path in the workspace."""
    if not module_name:
        return None
    base_path = Path.cwd() / Path(*module_name.split("."))
    module_file = base_path.with_suffix(".py")
    if module_file.exists():
        return module_file
    package_init = base_path / "__init__.py"
    if package_init.exists():
        return package_init
    return None


def _resolve_symbol_subject(module_path: Path, symbol_name: str) -> SubjectLocation | None:
    """Build a subject descriptor only when the target module really defines the symbol."""
    if not _module_defines_symbol(module_path, symbol_name):
        return None
    return SubjectLocation(
        file=module_path.name,
        method=symbol_name,
        source_path=_display_path(module_path),
    )


@lru_cache(maxsize=None)
def _module_defines_symbol(module_path: Path, symbol_name: str) -> bool:
    """Check whether a Python module declares the requested top-level function."""
    if module_path.suffix != ".py" or not module_path.exists():
        return False
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol_name:
            return True
    return False


@lru_cache(maxsize=None)
def _collect_http_routes(module_path: Path) -> tuple[HttpRoute, ...]:
    """Extract HTTP route declarations from one imported Python module."""
    if module_path.suffix != ".py" or not module_path.exists():
        return ()
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    routes: list[HttpRoute] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            route = _parse_http_route(module_path, decorator, node.name)
            if route is not None:
                routes.append(route)
    return tuple(routes)


def _parse_http_route(
    module_path: Path,
    decorator: ast.expr,
    handler_name: str,
) -> HttpRoute | None:
    """Parse one decorator into an HTTP route when it matches a supported pattern."""
    if not isinstance(decorator, ast.Call):
        return None
    if not isinstance(decorator.func, ast.Attribute):
        return None
    if decorator.func.attr not in HTTP_METHODS or not decorator.args:
        return None
    route_path = _extract_path_literal(decorator.args[0])
    if not route_path:
        return None
    return HttpRoute(
        method=decorator.func.attr,
        path=route_path,
        handler=handler_name,
        module_path=module_path,
    )


def _extract_path_literal(node: ast.expr) -> str | None:
    """Convert static or f-string route expressions into a comparable path pattern."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                parts.append("{param}")
        return "".join(parts)
    return None


def _route_matches(request_path: str, route_path: str) -> bool:
    """Match a concrete request path against a route template with path params."""
    if request_path == route_path:
        return True
    return re.fullmatch(_route_pattern(route_path), request_path) is not None


def _route_pattern(route_path: str) -> str:
    """Translate a route template into a regex usable for request matching."""
    if route_path == "/":
        return r"/"
    segments = route_path.strip("/").split("/")
    pattern_segments: list[str] = []
    for segment in segments:
        if segment.startswith("{") and segment.endswith("}"):
            pattern_segments.append(r"[^/]+")
        else:
            pattern_segments.append(re.escape(segment))
    prefix = "/" if route_path.startswith("/") else ""
    return f"{prefix}{'/'.join(pattern_segments)}"


def _extract_cases_from_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[dict[str, Any]]:
    """Extract one or more testcase payloads from a pytest function definition."""
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
    """Collect pytest marker names from a function's decorators."""
    markers: list[str] = []
    for dec in decorators:
        target = dec.func if isinstance(dec, ast.Call) else dec
        marker = _extract_marker_name(target)
        if marker:
            markers.append(marker)
    return markers


def _extract_marker_name(expr: ast.expr) -> str | None:
    """Return the marker name when the expression looks like pytest.mark.<name>."""
    if isinstance(expr, ast.Attribute):
        chain = _attr_chain(expr)
        if len(chain) >= 3 and chain[0] == "pytest" and chain[1] == "mark":
            return chain[2]
    return None


def _extract_parametrize(decorators: list[ast.expr]) -> dict[str, Any] | None:
    """Parse the first supported pytest.mark.parametrize decorator, if present."""
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
    """Identify the exact attribute chain used by pytest parametrization."""
    if isinstance(func, ast.Attribute):
        return _attr_chain(func) == ["pytest", "mark", "parametrize"]
    return False


def _parse_argnames(node: ast.expr) -> list[str]:
    """Normalize the parametrize argnames expression into a list of names."""
    value = _evaluate_node(node, {})
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(part).strip() for part in value]
    return ["value"]


def _parse_rows(argnames: list[str], node: ast.expr) -> list[dict[str, Any]]:
    """Normalize parametrized row data into dictionaries keyed by argument name."""
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
    """Extract explicit pytest parametrize ids when they are statically evaluable."""
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
    """Collect request payload expressions from HTTP client calls in the test."""
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
    """Append key/value expressions from one literal dict payload into the template map."""
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
    """Render input values for one testcase from templates or parametrize rows."""
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
    """Extract assert and pytest.raises expectations from the test body."""
    expectations: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Assert):
            expectations.append(ast.unparse(child.test))
        if isinstance(child, ast.With):
            expectations.extend(_extract_raises_expectation(child.items))
    return expectations


def _extract_raises_expectation(items: list[ast.withitem]) -> list[str]:
    """Extract pytest.raises expectations from with-statement contexts."""
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
    """Build the PCL input matrix rows from testcase input values."""
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
    """Build the PCL output matrix rows from testcase assertions."""
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
    """Split one textual expectation into a matrix item/value pair."""
    if check.startswith("raises "):
        return ("raises", check.removeprefix("raises ").strip())
    if " == " in check:
        left, right = check.split(" == ", 1)
        return (left.strip(), right.strip())
    return ("assertion", check)


def _group_keys_by_item(
    row_hits: OrderedDict[tuple[str, str], dict[str, str]],
) -> OrderedDict[tuple[str, str], dict[str, str]]:
    """Preserve insertion order while grouping matrix rows by item name."""
    item_groups: OrderedDict[str, list[tuple[tuple[str, str], dict[str, str]]]] = OrderedDict()
    for key, hits in row_hits.items():
        item_groups.setdefault(key[0], []).append((key, hits))

    grouped: OrderedDict[tuple[str, str], dict[str, str]] = OrderedDict()
    for entries in item_groups.values():
        for key, hits in entries:
            grouped[key] = hits
    return grouped


def _evaluate_node(node: ast.AST, context: dict[str, Any]) -> Any:
    """Evaluate a limited subset of AST nodes into plain Python values."""
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
    """Render one AST value into a PCL-friendly input cell string."""
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
    """Flatten an attribute expression into its dotted-name parts."""
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
    """Remove duplicates while keeping the first-seen order stable."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _to_text(value: Any) -> str:
    """Convert supported values into display text for generated reports."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return repr(value)


def _to_title(test_name: str) -> str:
    """Turn a pytest function name into a human-readable fallback title."""
    if test_name.startswith("test_"):
        test_name = test_name[5:]
    return test_name.replace("_", " ").strip().capitalize()


def _display_path(path: Path) -> str:
    """Prefer workspace-relative paths when reporting resolved source locations."""
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)
