"""Parse a constrained subset of Jest/TypeScript tests into PCL documents."""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from teaforge.pcl.classification import classify_type
from teaforge.pcl.models import PCLDocument, PCLTestCase
from teaforge.pcl.parser import (
    _build_input_rows,
    _build_output_rows,
    _display_path,
    _merge_documents_by_subject,
)

TEST_FILE_SUFFIXES = (".test.ts", ".spec.ts", ".test.js", ".spec.js")
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
        for index, block in enumerate(_extract_test_blocks(content), start=1):
            raw_documents.append(_build_document_for_block(file_path, block, imports, index))

    if not raw_documents:
        raise ValueError(f"No supported Jest tests found under: {test_path}")

    return _merge_documents_by_subject(raw_documents)


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

    inputs = _extract_case_inputs(block.body, imports, subject.method, block.context)
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
        )
    )
    document.input_rows = _build_input_rows(document.testcases)
    document.output_rows = _build_output_rows(document.testcases)
    return document


def _collect_test_files(path: Path) -> list[Path]:
    """Expand a file or directory input into supported Jest-style test files."""
    if path.is_file():
        return [path] if _is_test_file(path) else []
    patterns = ("*.test.ts", "*.spec.ts", "*.test.js", "*.spec.js")
    files: list[Path] = []
    for pattern in patterns:
        files.extend(path.rglob(pattern))
    return sorted(set(files))


def _is_test_file(path: Path) -> bool:
    """Recognize supported Jest naming conventions."""
    return path.name.endswith(TEST_FILE_SUFFIXES)


def _extract_imports(file_path: Path, content: str) -> dict[str, JSImport]:
    """Map imported bindings in a Jest file to local source files when resolvable."""
    imports: dict[str, JSImport] = {}

    named_pattern = re.compile(r"import\s*\{(?P<names>.*?)\}\s*from\s*[\"'](?P<module>[^\"']+)[\"']", re.DOTALL)
    namespace_pattern = re.compile(r"import\s*\*\s*as\s*(?P<alias>[A-Za-z_$][\w$]*)\s*from\s*[\"'](?P<module>[^\"']+)[\"']")
    default_pattern = re.compile(r"import\s+(?P<alias>[A-Za-z_$][\w$]*)\s+from\s*[\"'](?P<module>[^\"']+)[\"']")

    for match in named_pattern.finditer(content):
        module_path = _resolve_module_path(file_path, match.group("module"))
        for raw_name in match.group("names").split(","):
            name = raw_name.strip()
            if not name:
                continue
            original_name, bind_name = _split_import_alias(name)
            imports[bind_name] = JSImport(file_path=module_path, original_name=original_name)

    for match in namespace_pattern.finditer(content):
        alias = match.group("alias")
        module_path = _resolve_module_path(file_path, match.group("module"))
        imports[alias] = JSImport(file_path=module_path, original_name="*")

    for match in default_pattern.finditer(content):
        alias = match.group("alias")
        module_path = _resolve_module_path(file_path, match.group("module"))
        imports.setdefault(alias, JSImport(file_path=module_path, original_name="default"))

    return imports


def _split_import_alias(token: str) -> tuple[str, str]:
    """Split a named import token into original and locally bound names."""
    parts = [part.strip() for part in token.split(" as ", 1)]
    if len(parts) == 2:
        return parts[0], parts[1]
    return token.strip(), token.strip()


@lru_cache(maxsize=None)
def _resolve_module_path(test_file: Path, module_name: str) -> Path | None:
    """Resolve a relative Jest import to one local JS/TS module path."""
    if not module_name.startswith("."):
        return None

    base_path = (test_file.parent / module_name).resolve()
    candidates = [base_path]
    if base_path.suffix:
        candidates.append(base_path.with_suffix(base_path.suffix))
    else:
        candidates.extend(base_path.with_suffix(suffix) for suffix in (".ts", ".js", ".tsx", ".jsx"))
        candidates.extend(
            (base_path / f"index{suffix}") for suffix in (".ts", ".js", ".tsx", ".jsx")
        )

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _extract_test_blocks(content: str) -> list[JestTestBlock]:
    """Extract supported `test()` and `it()` blocks from one Jest file."""
    blocks: list[JestTestBlock] = []
    pattern = re.compile(r"\b(?:it|test)(?P<modifiers>(?:\.(?:each|only|skip))*)\s*\(")
    cursor = 0
    counter = 1
    while True:
        match = pattern.search(content, cursor)
        if match is None:
            break
        open_paren = content.find("(", match.start())
        close_paren = _find_matching(content, open_paren, "(", ")")
        if close_paren == -1:
            break
        modifiers = match.group("modifiers") or ""
        if ".each" in modifiers:
            invocation_open = content.find("(", close_paren + 1)
            if invocation_open == -1:
                break
            invocation_close = _find_matching(content, invocation_open, "(", ")")
            if invocation_close == -1:
                break
            each_blocks = _parse_each_invocation(
                rows_expression=content[open_paren + 1 : close_paren],
                invocation=content[invocation_open + 1 : invocation_close],
                start_index=counter,
            )
            blocks.extend(each_blocks)
            counter += len(each_blocks)
            cursor = invocation_close + 1
            continue

        invocation = content[open_paren + 1 : close_paren]
        parsed = _parse_test_invocation(invocation)
        if parsed is not None:
            title, body = parsed
            identifier = _normalize_test_identifier(title, counter)
            blocks.append(
                JestTestBlock(
                    title=title,
                    body=body,
                    identifier=identifier,
                    context={},
                )
            )
            counter += 1
        cursor = close_paren + 1
    return blocks


def _parse_each_invocation(
    rows_expression: str,
    invocation: str,
    start_index: int,
) -> list[JestTestBlock]:
    """Expand one `test.each(...)` invocation into one block per row."""
    title, cursor = _parse_title_and_cursor(invocation)
    if title is None:
        return []

    callback = _parse_callback_signature(invocation, cursor)
    if callback is None:
        return []

    parameter_names, body = callback
    rows = _parse_each_rows(rows_expression)
    blocks: list[JestTestBlock] = []
    for offset, row in enumerate(rows, start=0):
        context = _build_each_context(parameter_names, row)
        rendered_title = _render_each_title(title, parameter_names, row, context, start_index + offset)
        blocks.append(
            JestTestBlock(
                title=rendered_title,
                body=body,
                identifier=_normalize_test_identifier(rendered_title, start_index + offset),
                context=context,
            )
        )
    return blocks


def _parse_title_and_cursor(invocation: str) -> tuple[str | None, int]:
    """Parse the first title string from a Jest invocation payload."""
    start = _skip_whitespace(invocation, 0)
    string_result = _parse_string_literal(invocation, start)
    if string_result is None:
        return None, start
    title, cursor = string_result
    return title.strip(), cursor


def _parse_callback_signature(invocation: str, cursor: int) -> tuple[list[str], str] | None:
    """Parse callback parameters and body from an arrow-function invocation."""
    cursor = _skip_spaces(invocation, cursor)
    if cursor >= len(invocation) or invocation[cursor] != ",":
        return None
    cursor = _skip_spaces(invocation, cursor + 1)

    if cursor < len(invocation) and invocation[cursor] == "(":
        params_end = _find_matching(invocation, cursor, "(", ")")
        if params_end == -1:
            return None
        parameter_names = [
            name.strip() for name in _split_top_level(invocation[cursor + 1 : params_end], ",") if name.strip()
        ]
        body = _extract_callback_body(invocation, params_end + 1)
        if body is None:
            return None
        return parameter_names, body.strip()

    arrow_index = invocation.find("=>", cursor)
    if arrow_index == -1:
        return None
    parameter_name = invocation[cursor:arrow_index].strip()
    body = _extract_callback_body(invocation, arrow_index)
    if body is None:
        return None
    return ([parameter_name] if parameter_name else []), body.strip()


def _parse_each_rows(rows_expression: str) -> list[object]:
    """Parse a supported `test.each` rows expression into row payloads."""
    parsed = _parse_literal_expression(rows_expression)
    if isinstance(parsed, list):
        return parsed
    return []


def _build_each_context(parameter_names: list[str], row: object) -> dict[str, object]:
    """Map one parsed `test.each` row to callback parameter names."""
    if isinstance(row, dict):
        return dict(row)
    if isinstance(row, list):
        return {
            name: row[index] for index, name in enumerate(parameter_names) if index < len(row)
        }
    if len(parameter_names) == 1:
        return {parameter_names[0]: row}
    return {}


def _render_each_title(
    title: str,
    parameter_names: list[str],
    row: object,
    context: dict[str, object],
    index: int,
) -> str:
    """Render `%` and `$name` placeholders for one `test.each` row."""
    rendered = title
    if isinstance(row, list):
        row_values = [_stringify_value(value) for value in row]
    else:
        row_values = [_stringify_value(context[name]) for name in parameter_names if name in context]

    for token in ("%s", "%d", "%i", "%f", "%p", "%j", "%o"):
        while token in rendered and row_values:
            rendered = rendered.replace(token, row_values.pop(0), 1)

    for name, value in context.items():
        rendered = rendered.replace(f"${name}", _stringify_value(value))

    if rendered == title:
        rendered = f"{title} case {index:02d}"
    return rendered


def _parse_test_invocation(invocation: str) -> tuple[str, str] | None:
    """Parse the title and callback body from one Jest invocation payload."""
    start = _skip_whitespace(invocation, 0)
    string_result = _parse_string_literal(invocation, start)
    if string_result is None:
        return None
    title, cursor = string_result
    callback_body = _extract_callback_body(invocation, cursor)
    if callback_body is None:
        return None
    return title.strip(), callback_body.strip()


def _skip_whitespace(text: str, cursor: int) -> int:
    """Advance past whitespace and commas."""
    while cursor < len(text) and text[cursor] in " \t\r\n,":
        cursor += 1
    return cursor


def _skip_spaces(text: str, cursor: int) -> int:
    """Advance past whitespace without consuming punctuation."""
    while cursor < len(text) and text[cursor] in " \t\r\n":
        cursor += 1
    return cursor


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


def _extract_callback_body(invocation: str, cursor: int) -> str | None:
    """Extract the callback block body from an arrow/function callback."""
    arrow_index = invocation.find("=>", cursor)
    function_index = invocation.find("function", cursor)
    if arrow_index == -1 and function_index == -1:
        return None
    search_from = arrow_index + 2 if arrow_index != -1 else function_index + len("function")
    open_brace = invocation.find("{", search_from)
    if open_brace == -1:
        return None
    close_brace = _find_matching(invocation, open_brace, "{", "}")
    if close_brace == -1:
        return None
    return invocation[open_brace + 1 : close_brace]


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
    for call in _iter_calls_in_order(block.body):
        subject = _subject_from_call(call, imports)
        if subject is not None:
            return subject

        for nested_call in _iter_calls_in_order(call.arg_text):
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
    symbol_name = imported.original_name if imported.original_name != "default" else call.callee
    return _resolve_symbol_subject(imported.file_path, symbol_name)


def _resolve_symbol_subject(module_path: Path, symbol_name: str) -> SubjectLocation | None:
    """Build a subject descriptor when the imported module really defines the symbol."""
    if not _module_defines_symbol(module_path, symbol_name):
        return None
    return SubjectLocation(
        file=module_path.name,
        method=symbol_name,
        source_path=_display_path(module_path),
    )


@lru_cache(maxsize=None)
def _module_defines_symbol(module_path: Path, symbol_name: str) -> bool:
    """Check whether a JS/TS module declares the requested exported symbol."""
    if not module_path.exists() or module_path.suffix not in {".ts", ".tsx", ".js", ".jsx"}:
        return False
    source = module_path.read_text(encoding="utf-8")
    patterns = (
        rf"\bexport\s+(?:async\s+)?function\s+{re.escape(symbol_name)}\b",
        rf"\b(?:export\s+)?(?:const|let|var)\s+{re.escape(symbol_name)}\s*=",
        rf"\bexport\s+class\s+{re.escape(symbol_name)}\b",
        rf"\bclass\s+{re.escape(symbol_name)}\b",
    )
    return any(re.search(pattern, source) for pattern in patterns)


def _iter_calls_in_order(body: str) -> list[CallMatch]:
    """Return function calls in source order for subject inference and input extraction."""
    calls: list[CallMatch] = []
    pattern = re.compile(r"\b(?:(?P<namespace>[A-Za-z_$][\w$]*)\.)?(?P<name>[A-Za-z_$][\w$]*)\s*\(")
    cursor = 0
    while True:
        match = pattern.search(body, cursor)
        if match is None:
            break
        open_paren = body.find("(", match.start())
        close_paren = _find_matching(body, open_paren, "(", ")")
        if close_paren == -1:
            break
        namespace = match.group("namespace")
        name = match.group("name")
        callee = f"{namespace}.{name}" if namespace else name
        calls.append(CallMatch(callee=callee, arg_text=body[open_paren + 1 : close_paren], start=match.start()))
        cursor = close_paren + 1
    return calls


def _extract_case_inputs(
    body: str,
    imports: dict[str, JSImport],
    subject_method: str,
    context: dict[str, object],
) -> dict[str, str]:
    """Extract one testcase input dictionary from the first matching subject call."""
    for call in _iter_calls_in_order(body):
        if call.callee == subject_method or call.callee.endswith(f".{subject_method}"):
            return _render_inputs_from_call(body, call.arg_text, context)
        if call.callee in imports:
            imported = imports[call.callee]
            if imported.original_name == subject_method:
                return _render_inputs_from_call(body, call.arg_text, context)

        for nested_call in _iter_calls_in_order(call.arg_text):
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