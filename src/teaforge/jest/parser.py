"""Parse a constrained subset of Jest/TypeScript tests into PCL documents."""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from teaforge.discovery import discover_files
from teaforge.javascript.syntax import (
    extract_imports as extract_javascript_imports,
)
from teaforge.javascript.syntax import (
    extract_test_cases as extract_javascript_test_cases,
)
from teaforge.javascript.syntax import (
    parse_calls as parse_javascript_calls,
)
from teaforge.javascript.syntax import (
    source_defines_symbol,
)
from teaforge.pcl.assembly import build_input_rows, build_output_rows, merge_documents_by_subject
from teaforge.pcl.classification import classify_type
from teaforge.pcl.models import PCLDocument, PCLTestCase
from teaforge.pcl.parser import (
    _display_path,
)

TEST_FILE_SUFFIXES = (
    ".test.ts",
    ".spec.ts",
    ".test.tsx",
    ".spec.tsx",
    ".test.js",
    ".spec.js",
    ".test.jsx",
    ".spec.jsx",
)
DECLARATION_PREFIXES = ("const", "let", "var")


@dataclass(slots=True, frozen=True)
class JSImport:
    file_path: Path | None
    original_name: str


@dataclass(slots=True, frozen=True)
class SubjectLocation:
    file: str
    method: str
    source_path: str


@dataclass(slots=True, frozen=True)
class JestTestBlock:
    title: str
    body: str
    identifier: str
    context: dict[str, object]
    suffix: str = ".ts"
    full_name: str = ""


@dataclass(slots=True, frozen=True)
class CallMatch:
    callee: str
    arg_text: str
    start: int


def parse_jest_documents(test_path: Path) -> list[PCLDocument]:
    """Build one logical PCL document per inferred production subject from Jest tests."""
    files = _collect_test_files(test_path)
    if not files:
        raise ValueError(f"No Jest files found under: {test_path}")

    raw_documents: list[PCLDocument] = []
    for file_path in files:
        content = file_path.read_text(encoding="utf-8")
        imports = _extract_imports(file_path, content)
        for index, block in enumerate(
            _extract_test_blocks(
                content,
                suffix=file_path.suffix,
                source_name=str(file_path),
            ),
            start=1,
        ):
            raw_documents.append(_build_document_for_block(file_path, block, imports, index))

    if not raw_documents:
        raise ValueError(f"No supported Jest tests found under: {test_path}")

    return merge_documents_by_subject(raw_documents)


def _build_document_for_block(
    file_path: Path,
    block: JestTestBlock,
    imports: dict[str, JSImport],
    index: int,
) -> PCLDocument:
    """Convert one Jest test block into an intermediate PCL document."""
    subject = _infer_subject_location(file_path, block, imports)
    document = PCLDocument.create(
        file=subject.file,
        method=subject.method,
        source_path=subject.source_path,
        test_file=file_path.name,
        test_method=block.identifier,
        test_source_path=_display_path(file_path),
    )

    inputs = _extract_case_inputs(
        block.body,
        imports,
        subject.method,
        block.context,
        suffix=block.suffix,
    )
    output_checks = _extract_output_expectations(block.body, block.context)
    output = "; ".join(output_checks) if output_checks else "No explicit expect() assertion found"
    document.testcases.append(
        PCLTestCase(
            testcase=block.title,
            testname=block.identifier,
            testcasecode=f"TC-{index:03d}",
            inputs=inputs,
            output=output,
            type=classify_type(block.title, block.identifier, output),
            output_checks=output_checks,
            test_full_name=block.full_name or block.title,
            test_source_path=_display_path(file_path),
        )
    )
    document.input_rows = build_input_rows(document.testcases)
    document.output_rows = build_output_rows(document.testcases)
    return document


def _collect_test_files(path: Path) -> list[Path]:
    """Expand a file or directory input into supported Jest-style test files."""
    return discover_files(path, is_candidate=_is_test_file)


def _is_test_file(path: Path) -> bool:
    """Recognize supported Jest naming conventions."""
    return path.name.endswith(TEST_FILE_SUFFIXES)


def _extract_imports(file_path: Path, content: str) -> dict[str, JSImport]:
    """Map structural ESM/CommonJS bindings to resolvable local source files."""
    return {
        binding.local_name: JSImport(
            file_path=_resolve_module_path(file_path, binding.module),
            original_name=binding.imported_name,
        )
        for binding in extract_javascript_imports(
            content,
            suffix=file_path.suffix,
            source_name=str(file_path),
        )
    }


@lru_cache(maxsize=None)
def _resolve_module_path(test_file: Path, module_name: str) -> Path | None:
    """Resolve a relative Jest import to one local JS/TS module path."""
    if not module_name.startswith("."):
        return None

    base_path = (test_file.parent / module_name).resolve()
    candidates = [base_path]
    known_suffixes = {".ts", ".js", ".tsx", ".jsx"}
    if base_path.suffix in known_suffixes:
        candidates.append(base_path.with_suffix(base_path.suffix))
    else:
        candidates.extend(
            Path(f"{base_path}{suffix}") for suffix in (".ts", ".js", ".tsx", ".jsx")
        )
        candidates.extend(
            (base_path / f"index{suffix}") for suffix in (".ts", ".js", ".tsx", ".jsx")
        )

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _extract_test_blocks(
    content: str,
    *,
    suffix: str = ".ts",
    source_name: str = "<memory>",
) -> list[JestTestBlock]:
    """Extract Jest tests from structural syntax evidence."""
    return [
        JestTestBlock(
            title=case.title,
            body=case.body,
            identifier=_normalize_test_identifier(case.title, index),
            context=case.context,
            suffix=suffix,
            full_name=case.full_name,
        )
        for index, case in enumerate(
            extract_javascript_test_cases(
                content,
                suffix=suffix,
                source_name=source_name,
            ),
            start=1,
        )
    ]


def _parse_string_literal(text: str, cursor: int) -> tuple[str, int] | None:
    """Parse a simple JS/TS string literal starting at the given cursor."""
    if cursor >= len(text) or text[cursor] not in {'"', "'", "`"}:
        return None
    quote = text[cursor]
    cursor += 1
    value: list[str] = []
    while cursor < len(text):
        char = text[cursor]
        if char == "\\" and cursor + 1 < len(text):
            value.append(text[cursor + 1])
            cursor += 2
            continue
        if char == quote:
            return "".join(value), cursor + 1
        value.append(char)
        cursor += 1
    return None


def _find_matching(text: str, open_index: int, open_char: str, close_char: str) -> int:
    """Find the matching closing delimiter while skipping strings and comments."""
    depth = 0
    cursor = open_index
    while cursor < len(text):
        char = text[cursor]
        next_char = text[cursor + 1] if cursor + 1 < len(text) else ""
        if char in {'"', "'", "`"}:
            literal = _parse_string_literal(text, cursor)
            if literal is None:
                return -1
            _, cursor = literal
            continue
        if char == "/" and next_char == "/":
            newline = text.find("\n", cursor)
            if newline == -1:
                return -1
            cursor = newline + 1
            continue
        if char == "/" and next_char == "*":
            end_comment = text.find("*/", cursor + 2)
            if end_comment == -1:
                return -1
            cursor = end_comment + 2
            continue
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return cursor
        cursor += 1
    return -1


def _normalize_test_identifier(title: str, index: int) -> str:
    """Build a stable identifier for one Jest test block."""
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    return slug or f"jest_test_{index:03d}"


def _infer_subject_location(
    file_path: Path,
    block: JestTestBlock,
    imports: dict[str, JSImport],
) -> SubjectLocation:
    """Infer the tested production file and function from imported function calls."""
    for call in _iter_calls_in_order(block.body, suffix=block.suffix):
        subject = _subject_from_call(call, imports)
        if subject is not None:
            return subject

        for nested_call in _iter_calls_in_order(call.arg_text, suffix=block.suffix):
            subject = _subject_from_call(nested_call, imports)
            if subject is not None:
                return subject

    return SubjectLocation(
        file=file_path.name,
        method=block.identifier,
        source_path=_display_path(file_path),
    )


def _subject_from_call(call: CallMatch, imports: dict[str, JSImport]) -> SubjectLocation | None:
    """Resolve one scanned call into a tested subject when it matches an import."""
    if "." in call.callee:
        alias, method = call.callee.split(".", 1)
        imported = imports.get(alias)
        if imported is None or imported.file_path is None:
            return None
        return _resolve_symbol_subject(imported.file_path, method)

    imported = imports.get(call.callee)
    if imported is None or imported.file_path is None:
        return None
    if imported.original_name == "default":
        return _resolve_symbol_subject(
            imported.file_path,
            "default",
            method_name=call.callee,
        )
    return _resolve_symbol_subject(imported.file_path, imported.original_name)


def _resolve_symbol_subject(
    module_path: Path,
    symbol_name: str,
    *,
    method_name: str | None = None,
) -> SubjectLocation | None:
    """Build a subject descriptor when the imported module really defines the symbol."""
    if not _module_defines_symbol(module_path, symbol_name):
        return None
    return SubjectLocation(
        file=module_path.name,
        method=method_name or symbol_name,
        source_path=_display_path(module_path),
    )


@lru_cache(maxsize=None)
def _module_defines_symbol(module_path: Path, symbol_name: str) -> bool:
    """Check whether a JS/TS module declares the requested exported symbol."""
    if not module_path.exists() or module_path.suffix not in {".ts", ".tsx", ".js", ".jsx"}:
        return False
    source = module_path.read_text(encoding="utf-8")
    return source_defines_symbol(
        source,
        symbol_name,
        suffix=module_path.suffix,
        source_name=str(module_path),
    )


def _iter_calls_in_order(body: str, *, suffix: str = ".ts") -> list[CallMatch]:
    """Return function calls in source order for subject inference and input extraction."""
    return [
        CallMatch(
            callee=call.callee,
            arg_text=call.argument_text,
            start=call.start_byte,
        )
        for call in parse_javascript_calls(
            body,
            suffix=suffix,
            source_name="Jest callback",
        )
    ]


def _extract_case_inputs(
    body: str,
    imports: dict[str, JSImport],
    subject_method: str,
    context: dict[str, object],
    *,
    suffix: str = ".ts",
) -> dict[str, str]:
    """Extract one testcase input dictionary from the first matching subject call."""
    for call in _iter_calls_in_order(body, suffix=suffix):
        if call.callee == subject_method or call.callee.endswith(f".{subject_method}"):
            return _render_inputs_from_call(body, call.arg_text, context)
        if call.callee in imports:
            imported = imports[call.callee]
            if imported.original_name == subject_method:
                return _render_inputs_from_call(body, call.arg_text, context)

        for nested_call in _iter_calls_in_order(call.arg_text, suffix=suffix):
            if nested_call.callee == subject_method or nested_call.callee.endswith(
                f".{subject_method}"
            ):
                return _render_inputs_from_call(body, nested_call.arg_text, context)
            if nested_call.callee in imports:
                imported = imports[nested_call.callee]
                if imported.original_name == subject_method:
                    return _render_inputs_from_call(body, nested_call.arg_text, context)
    return {}


def _render_inputs_from_call(body: str, arg_text: str, context: dict[str, object]) -> dict[str, str]:
    """Render one call's arguments into PCL-friendly input cells."""
    args = [segment.strip() for segment in _split_top_level(arg_text, ",") if segment.strip()]
    if not args:
        return {}

    if len(args) == 1:
        resolved = _resolve_expression(body, args[0], context)
        if isinstance(resolved, dict):
            return resolved
        return {"arg1": _stringify_value(resolved)}

    rendered: OrderedDict[str, str] = OrderedDict()
    for index, segment in enumerate(args, start=1):
        rendered[f"arg{index}"] = _stringify_value(_resolve_expression(body, segment, context))
    return dict(rendered)


def _resolve_expression(body: str, expression: str, context: dict[str, object] | None = None):
    """Resolve a variable reference or literal expression into a display value."""
    trimmed = expression.strip()
    if context and trimmed in context:
        return context[trimmed]
    if re.fullmatch(r"[A-Za-z_$][\w$]*", trimmed):
        declaration = _find_variable_declaration(body, trimmed)
        if declaration is not None:
            return _parse_literal_expression(declaration, context)
    return _parse_literal_expression(trimmed, context)


def _find_variable_declaration(body: str, variable_name: str) -> str | None:
    """Find the last simple const/let/var declaration for one variable name."""
    pattern = re.compile(
        rf"\b(?:{'|'.join(DECLARATION_PREFIXES)})\s+{re.escape(variable_name)}\s*=\s*(?P<expr>.+?);",
        re.DOTALL,
    )
    matches = list(pattern.finditer(body))
    if not matches:
        return None
    return matches[-1].group("expr").strip()


def _parse_literal_expression(expression: str, context: dict[str, object] | None = None):
    """Parse a small, report-oriented subset of JS/TS literal expressions."""
    trimmed = expression.strip()
    if trimmed.startswith("{") and trimmed.endswith("}"):
        return _parse_object_literal(trimmed, context)
    if trimmed.startswith("[") and trimmed.endswith("]"):
        return _parse_array_literal(trimmed, context)
    string_value = _parse_string_literal(trimmed, 0)
    if string_value is not None and string_value[1] == len(trimmed):
        return string_value[0]
    if re.fullmatch(r"-?\d+(?:\.\d+)?", trimmed):
        return int(trimmed) if re.fullmatch(r"-?\d+", trimmed) else float(trimmed)
    if trimmed in {"true", "false", "null", "undefined"}:
        return trimmed
    if context and trimmed in context:
        return context[trimmed]
    return trimmed


def _parse_object_literal(expression: str, context: dict[str, object] | None = None) -> dict[str, str]:
    """Parse a flat object literal into stringified key/value pairs."""
    inner = expression[1:-1].strip()
    if not inner:
        return {}
    result: OrderedDict[str, str] = OrderedDict()
    for part in _split_top_level(inner, ","):
        stripped = part.strip()
        if not stripped:
            continue
        if ":" not in stripped:
            key = stripped.strip('"\'`')
            value = context.get(key, key) if context else key
            result[key] = _stringify_value(value)
            continue
        key_text, value_text = _split_once_top_level(stripped, ":")
        key = key_text.strip().strip('"\'`')
        value = _parse_literal_expression(value_text.strip(), context)
        result[key] = _stringify_value(value)
    return dict(result)


def _parse_array_literal(expression: str, context: dict[str, object] | None = None) -> list[object]:
    """Parse a flat array literal into nested Python values."""
    inner = expression[1:-1].strip()
    if not inner:
        return []
    return [
        _parse_literal_expression(part.strip(), context)
        for part in _split_top_level(inner, ",")
        if part.strip()
    ]


def _stringify_value(value) -> str:
    """Convert parsed literal values into PCL cell text."""
    if isinstance(value, dict):
        return "{" + ", ".join(f"{key}: {inner}" for key, inner in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(_stringify_value(inner) for inner in value) + "]"
    return str(value)


def _split_top_level(text: str, separator: str) -> list[str]:
    """Split text by one separator while respecting nested delimiters and strings."""
    parts: list[str] = []
    start = 0
    depth_paren = 0
    depth_brace = 0
    depth_bracket = 0
    cursor = 0
    while cursor < len(text):
        char = text[cursor]
        if char in {'"', "'", "`"}:
            literal = _parse_string_literal(text, cursor)
            if literal is None:
                break
            _, cursor = literal
            continue
        if char == "(":
            depth_paren += 1
        elif char == ")":
            depth_paren -= 1
        elif char == "{":
            depth_brace += 1
        elif char == "}":
            depth_brace -= 1
        elif char == "[":
            depth_bracket += 1
        elif char == "]":
            depth_bracket -= 1
        elif (
            char == separator
            and depth_paren == 0
            and depth_brace == 0
            and depth_bracket == 0
        ):
            parts.append(text[start:cursor])
            start = cursor + 1
        cursor += 1
    parts.append(text[start:])
    return parts


def _split_once_top_level(text: str, separator: str) -> tuple[str, str]:
    """Split one text segment into two parts at the first top-level separator."""
    parts = _split_top_level(text, separator)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], separator.join(parts[1:])


def _extract_output_expectations(body: str, context: dict[str, object] | None = None) -> list[str]:
    """Extract Jest `expect()` assertions into PCL output rows."""
    expectations: list[str] = []
    pattern = re.compile(r"\bexpect\s*\(")
    cursor = 0
    while True:
        match = pattern.search(body, cursor)
        if match is None:
            break
        open_paren = body.find("(", match.start())
        close_paren = _find_matching(body, open_paren, "(", ")")
        if close_paren == -1:
            break
        actual = body[open_paren + 1 : close_paren].strip()
        tail = body[close_paren + 1 :]
        matcher_match = re.match(
            r"\s*\.(?:(?P<rejects>rejects)\.)?(?P<matcher>toBe|toEqual|toStrictEqual|toContain|toThrow)\s*\(",
            tail,
        )
        if matcher_match is not None:
            matcher = matcher_match.group("matcher")
            matcher_open = close_paren + 1 + matcher_match.end() - 1
            matcher_close = _find_matching(body, matcher_open, "(", ")")
            if matcher_close != -1:
                expected = body[matcher_open + 1 : matcher_close].strip()
                expectations.extend(_format_expectation(actual, matcher, expected, context))
                cursor = matcher_close + 1
                continue
        cursor = close_paren + 1
    return expectations


def _format_expectation(
    actual: str,
    matcher: str,
    expected: str,
    context: dict[str, object] | None = None,
) -> list[str]:
    """Format one Jest matcher into the existing output-row vocabulary."""
    rendered_expected = _stringify_value(_parse_literal_expression(expected, context))
    if matcher in {"toBe", "toEqual", "toStrictEqual", "toContain"}:
        return [f"{actual} == {rendered_expected}"]
    if matcher == "toThrow":
        return [f"raises {rendered_expected or 'Error'}"]
    return []
