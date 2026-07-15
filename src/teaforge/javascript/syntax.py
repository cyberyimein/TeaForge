"""Build structural Static Evidence without executing or modifying target projects."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Iterator

import tree_sitter_javascript
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser, Tree

JAVASCRIPT_SUFFIXES = {".js", ".jsx", ".mjs", ".cjs"}
TYPESCRIPT_SUFFIXES = {".ts", ".mts", ".cts"}
TSX_SUFFIXES = {".tsx"}
SUPPORTED_SUFFIXES = JAVASCRIPT_SUFFIXES | TYPESCRIPT_SUFFIXES | TSX_SUFFIXES
TEST_ROOTS = {"test", "it"}
DESCRIBE_ROOTS = {"describe"}


class JavaScriptSyntaxError(ValueError):
    """Report a source location that could not be represented as safe Static Evidence."""

    code = "javascript-syntax-error"


@dataclass(slots=True, frozen=True)
class JavaScriptImport:
    module: str
    local_name: str
    imported_name: str


@dataclass(slots=True, frozen=True)
class JavaScriptTestCase:
    title: str
    full_name: str
    body: str
    context: dict[str, object]
    start_byte: int


@dataclass(slots=True, frozen=True)
class JavaScriptCall:
    callee: str
    argument_text: str
    arguments: tuple[str, ...]
    start_byte: int


@dataclass(slots=True, frozen=True)
class JavaScriptFunction:
    name: str
    start_line: int
    end_line: int


@dataclass(slots=True, frozen=True)
class _ParsedSource:
    source: bytes
    tree: Tree
    suffix: str
    source_name: str

    def text(self, node: Node) -> str:
        return self.source[node.start_byte : node.end_byte].decode(
            "utf-8", errors="replace"
        )


@dataclass(slots=True, frozen=True)
class _Callback:
    node: Node
    body: Node
    parameter_names: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class _Invocation:
    title_node: Node
    callback: _Callback
    rows_node: Node | None


_UNRESOLVED = object()


def extract_imports(
    source: str,
    *,
    suffix: str,
    source_name: str = "<memory>",
) -> list[JavaScriptImport]:
    """Return ESM and statically provable CommonJS bindings in source order."""
    parsed = _parse(source, suffix=suffix, source_name=source_name)
    imports: list[JavaScriptImport] = []
    for statement in parsed.tree.root_node.named_children:
        if statement.type == "import_statement":
            imports.extend(_esm_imports(parsed, statement))
        elif statement.type in {"lexical_declaration", "variable_declaration"}:
            imports.extend(_commonjs_imports(parsed, statement))
    return imports


def extract_test_cases(
    source: str,
    *,
    suffix: str,
    source_name: str = "<memory>",
) -> list[JavaScriptTestCase]:
    """Return literal Jest test cases with lexical describe identity and each rows."""
    parsed = _parse(source, suffix=suffix, source_name=source_name)
    cases: list[JavaScriptTestCase] = []
    _visit_test_scope(
        parsed,
        parsed.tree.root_node,
        suite_titles=(),
        inherited_context={},
        output=cases,
    )
    cases.sort(key=lambda case: case.start_byte)
    return cases


def parse_calls(
    source: str,
    *,
    suffix: str,
    source_name: str = "<memory>",
) -> list[JavaScriptCall]:
    """Return structurally parsed call expressions in lexical source order."""
    parsed = _parse(source, suffix=suffix, source_name=source_name)
    calls: list[JavaScriptCall] = []
    for node in _walk(parsed.tree.root_node):
        if node.type != "call_expression":
            continue
        function = node.child_by_field_name("function")
        arguments_node = node.child_by_field_name("arguments")
        if function is None or arguments_node is None:
            continue
        callee = _callee_path(parsed, function)
        if not callee:
            continue
        arguments = tuple(
            parsed.text(argument) for argument in arguments_node.named_children
        )
        argument_text = parsed.source[
            arguments_node.start_byte + 1 : arguments_node.end_byte - 1
        ].decode("utf-8", errors="replace")
        calls.append(
            JavaScriptCall(
                callee=callee,
                argument_text=argument_text,
                arguments=arguments,
                start_byte=node.start_byte,
            )
        )
    calls.sort(key=lambda call: call.start_byte)
    return calls


def parse_source_functions(
    source: str,
    *,
    suffix: str,
    source_name: str = "<memory>",
) -> list[JavaScriptFunction]:
    """Return top-level functions and class methods from one structural index."""
    parsed = _parse(source, suffix=suffix, source_name=source_name)
    functions: list[JavaScriptFunction] = []
    for statement in parsed.tree.root_node.named_children:
        declaration = _unwrap_export(statement)
        if declaration is None:
            continue
        if declaration.type in {"function_declaration", "generator_function_declaration"}:
            name_node = declaration.child_by_field_name("name")
            if name_node is not None:
                functions.append(_function_fact(parsed, parsed.text(name_node), declaration))
            continue
        if declaration.type in {"lexical_declaration", "variable_declaration"}:
            for declarator in declaration.named_children:
                if declarator.type != "variable_declarator":
                    continue
                name_node = declarator.child_by_field_name("name")
                value_node = declarator.child_by_field_name("value")
                if (
                    name_node is not None
                    and name_node.type == "identifier"
                    and value_node is not None
                    and value_node.type
                    in {"arrow_function", "function_expression", "generator_function"}
                ):
                    functions.append(
                        _function_fact(parsed, parsed.text(name_node), declaration)
                    )
            continue
        if declaration.type in {"class_declaration", "abstract_class_declaration"}:
            functions.extend(_class_functions(parsed, declaration))
            continue
        if declaration.type == "expression_statement":
            assignment = next(
                (
                    child
                    for child in declaration.named_children
                    if child.type == "assignment_expression"
                ),
                None,
            )
            if assignment is not None:
                assigned = _assigned_function(parsed, assignment)
                if assigned is not None:
                    functions.append(assigned)
    unique = {
        (function.name, function.start_line, function.end_line): function
        for function in functions
    }
    return sorted(unique.values(), key=lambda item: (item.start_line, item.name))


def source_defines_symbol(
    source: str,
    symbol_name: str,
    *,
    suffix: str,
    source_name: str = "<memory>",
) -> bool:
    """Prove that a module declares or explicitly exports a requested symbol."""
    parsed = _parse(source, suffix=suffix, source_name=source_name)
    symbols: set[str] = set()
    for statement in parsed.tree.root_node.named_children:
        if statement.type == "export_statement":
            prefix = parsed.text(statement).lstrip()
            if prefix.startswith("export default"):
                symbols.add("default")
            symbols.update(_exported_names(parsed, statement))
            declaration = _unwrap_export(statement)
            if declaration is not None and not prefix.startswith("export default"):
                symbols.update(_declaration_names(parsed, declaration))
            continue
        elif statement.type == "expression_statement":
            symbols.update(_commonjs_export_names(parsed, statement))
    return symbol_name in symbols


def _parse(source: str, *, suffix: str, source_name: str) -> _ParsedSource:
    normalized_suffix = _normalize_suffix(suffix)
    source_bytes = source.encode("utf-8")
    parser = Parser(_language(normalized_suffix))
    tree = parser.parse(source_bytes)
    parsed = _ParsedSource(
        source=source_bytes,
        tree=tree,
        suffix=normalized_suffix,
        source_name=source_name,
    )
    if tree.root_node.has_error:
        problem = next(
            (
                node
                for node in _walk(tree.root_node)
                if node.is_error or node.is_missing
            ),
            tree.root_node,
        )
        line = problem.start_point.row + 1
        column = problem.start_point.column + 1
        excerpt = parsed.text(problem).strip().replace("\n", " ")[:120]
        detail = f" near {excerpt!r}" if excerpt else ""
        raise JavaScriptSyntaxError(
            f"Could not parse JavaScript/TypeScript Static Evidence in "
            f"{source_name}:{line}:{column}{detail}."
        )
    return parsed


def _normalize_suffix(suffix: str) -> str:
    normalized = suffix.lower()
    if not normalized.startswith("."):
        normalized = f".{normalized}"
    if normalized not in SUPPORTED_SUFFIXES:
        raise ValueError(
            f"Unsupported JavaScript/TypeScript suffix: {suffix}. "
            f"Supported values: {', '.join(sorted(SUPPORTED_SUFFIXES))}"
        )
    return normalized


@lru_cache(maxsize=None)
def _language(suffix: str) -> Language:
    if suffix in JAVASCRIPT_SUFFIXES:
        return Language(tree_sitter_javascript.language())
    if suffix in TSX_SUFFIXES:
        return Language(tree_sitter_typescript.language_tsx())
    return Language(tree_sitter_typescript.language_typescript())


def _walk(node: Node) -> Iterator[Node]:
    yield node
    for child in node.named_children:
        yield from _walk(child)


def _esm_imports(parsed: _ParsedSource, statement: Node) -> list[JavaScriptImport]:
    source_node = statement.child_by_field_name("source")
    if source_node is None:
        return []
    module = _static_string(parsed, source_node, {})
    if module is None:
        return []
    clause = next(
        (child for child in statement.named_children if child.type == "import_clause"),
        None,
    )
    if clause is None:
        return []
    result: list[JavaScriptImport] = []
    for child in clause.named_children:
        if child.type == "identifier":
            result.append(JavaScriptImport(module, parsed.text(child), "default"))
        elif child.type == "namespace_import":
            identifier = next(
                (item for item in child.named_children if item.type == "identifier"),
                None,
            )
            if identifier is not None:
                result.append(JavaScriptImport(module, parsed.text(identifier), "*"))
        elif child.type == "named_imports":
            for specifier in child.named_children:
                if specifier.type != "import_specifier":
                    continue
                name = specifier.child_by_field_name("name")
                alias = specifier.child_by_field_name("alias")
                if name is not None:
                    result.append(
                        JavaScriptImport(
                            module,
                            parsed.text(alias or name),
                            parsed.text(name),
                        )
                    )
    return result


def _commonjs_imports(
    parsed: _ParsedSource,
    declaration: Node,
) -> list[JavaScriptImport]:
    result: list[JavaScriptImport] = []
    for declarator in declaration.named_children:
        if declarator.type != "variable_declarator":
            continue
        name = declarator.child_by_field_name("name")
        value = declarator.child_by_field_name("value")
        if name is None or value is None:
            continue
        require = _require_value(parsed, value)
        if require is None:
            continue
        module, member = require
        if name.type == "identifier":
            result.append(
                JavaScriptImport(module, parsed.text(name), member or "*")
            )
        elif name.type == "object_pattern":
            for binding in name.named_children:
                if binding.type == "pair_pattern":
                    key = binding.child_by_field_name("key")
                    local = binding.child_by_field_name("value")
                    if key is not None and local is not None:
                        result.append(
                            JavaScriptImport(
                                module,
                                parsed.text(local),
                                parsed.text(key),
                            )
                        )
                elif binding.type == "shorthand_property_identifier_pattern":
                    binding_name = parsed.text(binding)
                    result.append(
                        JavaScriptImport(module, binding_name, binding_name)
                    )
    return result


def _require_value(parsed: _ParsedSource, node: Node) -> tuple[str, str | None] | None:
    member: str | None = None
    call = node
    if node.type == "member_expression":
        call = node.child_by_field_name("object")
        property_node = node.child_by_field_name("property")
        if property_node is not None:
            member = parsed.text(property_node)
    if call is None or call.type != "call_expression":
        return None
    function = call.child_by_field_name("function")
    arguments = call.child_by_field_name("arguments")
    if (
        function is None
        or parsed.text(function) != "require"
        or arguments is None
        or len(arguments.named_children) != 1
    ):
        return None
    module = _static_string(parsed, arguments.named_children[0], {})
    return (module, member) if module is not None else None


def _visit_test_scope(
    parsed: _ParsedSource,
    node: Node,
    *,
    suite_titles: tuple[str, ...],
    inherited_context: dict[str, object],
    output: list[JavaScriptTestCase],
) -> None:
    if node.type == "call_expression":
        suite_invocation = _decode_invocation(parsed, node, DESCRIBE_ROOTS)
        if suite_invocation is not None:
            for rendered_title, row_context in _expand_invocation(
                parsed, suite_invocation, inherited_context
            ):
                merged_context = {**inherited_context, **row_context}
                _visit_test_scope(
                    parsed,
                    suite_invocation.callback.body,
                    suite_titles=(*suite_titles, rendered_title),
                    inherited_context=merged_context,
                    output=output,
                )
            return

        test_invocation = _decode_invocation(parsed, node, TEST_ROOTS)
        if test_invocation is not None:
            for rendered_title, row_context in _expand_invocation(
                parsed, test_invocation, inherited_context
            ):
                merged_context = {**inherited_context, **row_context}
                output.append(
                    JavaScriptTestCase(
                        title=rendered_title,
                        full_name=" ".join((*suite_titles, rendered_title)).strip(),
                        body=_callback_body_text(parsed, test_invocation.callback.body),
                        context=merged_context,
                        start_byte=node.start_byte,
                    )
                )
            return

    for child in node.named_children:
        _visit_test_scope(
            parsed,
            child,
            suite_titles=suite_titles,
            inherited_context=inherited_context,
            output=output,
        )


def _decode_invocation(
    parsed: _ParsedSource,
    call: Node,
    roots: set[str],
) -> _Invocation | None:
    function = call.child_by_field_name("function")
    arguments = call.child_by_field_name("arguments")
    if function is None or arguments is None:
        return None
    rows_node: Node | None = None
    callee = _callee_path(parsed, function)
    if callee is None and function.type == "call_expression":
        each_function = function.child_by_field_name("function")
        each_arguments = function.child_by_field_name("arguments")
        each_callee = (
            _callee_path(parsed, each_function) if each_function is not None else None
        )
        if (
            each_callee
            and _root_name(each_callee) in roots
            and each_callee.split(".")[-1] == "each"
            and each_arguments is not None
            and each_arguments.named_children
        ):
            callee = each_callee
            rows_node = each_arguments.named_children[0]
    if callee is None or _root_name(callee) not in roots:
        return None
    if callee.split(".")[-1] == "each" and rows_node is None:
        return None
    invocation_arguments = arguments.named_children
    if len(invocation_arguments) < 2:
        return None
    callback = _callback(parsed, invocation_arguments[1])
    if callback is None:
        return None
    return _Invocation(
        title_node=invocation_arguments[0],
        callback=callback,
        rows_node=rows_node,
    )


def _callback(parsed: _ParsedSource, node: Node) -> _Callback | None:
    if node.type not in {"arrow_function", "function_expression", "function"}:
        return None
    body = node.child_by_field_name("body")
    if body is None:
        return None
    parameters = node.child_by_field_name("parameters")
    parameter_names = tuple(_pattern_names(parsed, parameters)) if parameters else ()
    return _Callback(node=node, body=body, parameter_names=parameter_names)


def _pattern_names(parsed: _ParsedSource, node: Node) -> list[str]:
    if node.type in {
        "identifier",
        "shorthand_property_identifier_pattern",
    }:
        return [parsed.text(node)]
    if node.type in {"required_parameter", "optional_parameter"}:
        pattern = node.child_by_field_name("pattern")
        return _pattern_names(parsed, pattern) if pattern is not None else []
    if node.type == "assignment_pattern":
        left = node.child_by_field_name("left")
        return _pattern_names(parsed, left) if left is not None else []
    names: list[str] = []
    for child in node.named_children:
        if child.type in {"type_annotation", "predefined_type", "type_identifier"}:
            continue
        names.extend(_pattern_names(parsed, child))
    return names


def _expand_invocation(
    parsed: _ParsedSource,
    invocation: _Invocation,
    inherited_context: dict[str, object],
) -> list[tuple[str, dict[str, object]]]:
    if invocation.rows_node is None:
        title = _static_string(parsed, invocation.title_node, inherited_context)
        return [(title, {})] if title is not None else []

    rows = _literal_value(parsed, invocation.rows_node, inherited_context)
    if not isinstance(rows, list):
        return []
    expanded: list[tuple[str, dict[str, object]]] = []
    for index, row in enumerate(rows, start=1):
        context = _row_context(invocation.callback.parameter_names, row)
        combined = {**inherited_context, **context}
        title = _static_string(parsed, invocation.title_node, combined)
        if title is None:
            continue
        expanded.append((_render_each_title(title, row, context, index), context))
    return expanded


def _row_context(parameter_names: tuple[str, ...], row: object) -> dict[str, object]:
    if isinstance(row, dict):
        return dict(row)
    if isinstance(row, list):
        return {
            name: row[index]
            for index, name in enumerate(parameter_names)
            if index < len(row)
        }
    if len(parameter_names) == 1:
        return {parameter_names[0]: row}
    return {}


def _render_each_title(
    title: str,
    row: object,
    context: dict[str, object],
    index: int,
) -> str:
    rendered = title
    values = row if isinstance(row, list) else list(context.values())
    pending = [_display_value(value) for value in values]
    for token in ("%s", "%d", "%i", "%f", "%p", "%j", "%o"):
        while token in rendered and pending:
            rendered = rendered.replace(token, pending.pop(0), 1)
    for name, value in context.items():
        rendered = rendered.replace(f"${name}", _display_value(value))
    if rendered == title:
        rendered = f"{title} case {index:02d}"
    return rendered


def _static_string(
    parsed: _ParsedSource,
    node: Node,
    context: dict[str, object],
) -> str | None:
    if node.type == "string":
        raw = parsed.text(node)
        return _decode_quoted_string(raw)
    if node.type == "template_string":
        parts: list[str] = []
        for child in node.named_children:
            if child.type == "string_fragment":
                parts.append(parsed.text(child))
            elif child.type == "escape_sequence":
                parts.append(_decode_escape(parsed.text(child)))
            elif child.type == "template_substitution":
                expression = next(iter(child.named_children), None)
                value = (
                    _literal_value(parsed, expression, context)
                    if expression is not None
                    else _UNRESOLVED
                )
                if value is _UNRESOLVED:
                    return None
                parts.append(_display_value(value))
        return "".join(parts)
    return None


def _literal_value(
    parsed: _ParsedSource,
    node: Node,
    context: dict[str, object],
) -> object:
    if node.type in {"string", "template_string"}:
        value = _static_string(parsed, node, context)
        return value if value is not None else _UNRESOLVED
    if node.type == "number":
        raw = parsed.text(node).replace("_", "")
        try:
            return float(raw) if any(char in raw for char in ".eE") else int(raw, 0)
        except ValueError:
            return _UNRESOLVED
    if node.type in {"true", "false"}:
        return node.type == "true"
    if node.type == "null":
        return "null"
    if node.type == "undefined":
        return "undefined"
    if node.type == "identifier":
        return context.get(parsed.text(node), _UNRESOLVED)
    if node.type == "array":
        values: list[object] = []
        for child in node.named_children:
            value = _literal_value(parsed, child, context)
            if value is _UNRESOLVED:
                return _UNRESOLVED
            values.append(value)
        return values
    if node.type == "object":
        result: dict[str, object] = {}
        for child in node.named_children:
            if child.type == "pair":
                key_node = child.child_by_field_name("key")
                value_node = child.child_by_field_name("value")
                if key_node is None or value_node is None:
                    return _UNRESOLVED
                key = _property_name(parsed, key_node, context)
                value = _literal_value(parsed, value_node, context)
                if key is None or value is _UNRESOLVED:
                    return _UNRESOLVED
                result[key] = value
            elif child.type == "shorthand_property_identifier":
                key = parsed.text(child)
                value = context.get(key, _UNRESOLVED)
                if value is _UNRESOLVED:
                    return _UNRESOLVED
                result[key] = value
            else:
                return _UNRESOLVED
        return result
    if node.type in {
        "parenthesized_expression",
        "as_expression",
        "satisfies_expression",
        "type_assertion",
    }:
        expression = node.child_by_field_name("expression") or next(
            (
                child
                for child in node.named_children
                if child.type not in {"type_annotation", "type_identifier"}
            ),
            None,
        )
        return (
            _literal_value(parsed, expression, context)
            if expression is not None
            else _UNRESOLVED
        )
    if node.type == "unary_expression":
        argument = node.child_by_field_name("argument")
        if argument is None:
            return _UNRESOLVED
        value = _literal_value(parsed, argument, context)
        operator = parsed.text(node)[: argument.start_byte - node.start_byte].strip()
        if isinstance(value, (int, float)) and operator in {"+", "-"}:
            return value if operator == "+" else -value
    if node.type == "member_expression":
        object_node = node.child_by_field_name("object")
        property_node = node.child_by_field_name("property")
        if object_node is not None and property_node is not None:
            owner = _literal_value(parsed, object_node, context)
            key = parsed.text(property_node)
            if isinstance(owner, dict) and key in owner:
                return owner[key]
    return _UNRESOLVED


def _property_name(
    parsed: _ParsedSource,
    node: Node,
    context: dict[str, object],
) -> str | None:
    if node.type in {"property_identifier", "identifier", "number"}:
        return parsed.text(node)
    value = _static_string(parsed, node, context)
    return value


def _decode_quoted_string(raw: str) -> str:
    if len(raw) < 2:
        return raw
    inner = raw[1:-1]
    result: list[str] = []
    cursor = 0
    while cursor < len(inner):
        if inner[cursor] == "\\" and cursor + 1 < len(inner):
            escape = inner[cursor : cursor + 2]
            result.append(_decode_escape(escape))
            cursor += 2
        else:
            result.append(inner[cursor])
            cursor += 1
    return "".join(result)


def _decode_escape(raw: str) -> str:
    escapes = {
        "\\n": "\n",
        "\\r": "\r",
        "\\t": "\t",
        "\\b": "\b",
        "\\f": "\f",
        "\\v": "\v",
        "\\0": "\0",
        "\\\\": "\\",
        "\\\"": '"',
        "\\'": "'",
        "\\`": "`",
    }
    return escapes.get(raw, raw[1:] if raw.startswith("\\") else raw)


def _display_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict):
        return "{" + ", ".join(
            f"{key}: {_display_value(inner)}" for key, inner in value.items()
        ) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(_display_value(inner) for inner in value) + "]"
    return str(value)


def _callback_body_text(parsed: _ParsedSource, body: Node) -> str:
    if body.type == "statement_block":
        return parsed.source[body.start_byte + 1 : body.end_byte - 1].decode(
            "utf-8", errors="replace"
        ).strip()
    return parsed.text(body).strip()


def _callee_path(parsed: _ParsedSource, node: Node) -> str | None:
    if node.type in {"identifier", "property_identifier"}:
        return parsed.text(node)
    if node.type in {"member_expression", "optional_chain"}:
        owner = node.child_by_field_name("object")
        property_node = node.child_by_field_name("property")
        if owner is None or property_node is None:
            return None
        owner_path = _callee_path(parsed, owner)
        return (
            f"{owner_path}.{parsed.text(property_node)}" if owner_path else None
        )
    return None


def _root_name(callee: str) -> str:
    return callee.split(".", 1)[0]


def _unwrap_export(statement: Node) -> Node | None:
    if statement.type != "export_statement":
        return statement
    return statement.child_by_field_name("declaration") or next(
        (
            child
            for child in statement.named_children
            if child.type
            in {
                "function_declaration",
                "generator_function_declaration",
                "class_declaration",
                "abstract_class_declaration",
                "lexical_declaration",
                "variable_declaration",
                "expression_statement",
            }
        ),
        None,
    )


def _function_fact(
    parsed: _ParsedSource,
    name: str,
    node: Node,
) -> JavaScriptFunction:
    return JavaScriptFunction(
        name=name,
        start_line=node.start_point.row + 1,
        end_line=node.end_point.row + 1,
    )


def _class_functions(
    parsed: _ParsedSource,
    declaration: Node,
) -> list[JavaScriptFunction]:
    name_node = declaration.child_by_field_name("name")
    body = declaration.child_by_field_name("body")
    if name_node is None or body is None:
        return []
    class_name = parsed.text(name_node)
    functions: list[JavaScriptFunction] = []
    for member in body.named_children:
        if member.type == "method_definition":
            method_name = member.child_by_field_name("name")
            if method_name is None or parsed.text(method_name) == "constructor":
                continue
            functions.append(
                _function_fact(
                    parsed,
                    f"{class_name}.{parsed.text(method_name)}",
                    member,
                )
            )
        elif member.type == "public_field_definition":
            field_name = member.child_by_field_name("name")
            value = member.child_by_field_name("value")
            if (
                field_name is not None
                and value is not None
                and value.type in {"arrow_function", "function_expression"}
            ):
                functions.append(
                    _function_fact(
                        parsed,
                        f"{class_name}.{parsed.text(field_name)}",
                        member,
                    )
                )
    return functions


def _assigned_function(
    parsed: _ParsedSource,
    assignment: Node,
) -> JavaScriptFunction | None:
    left = assignment.child_by_field_name("left")
    right = assignment.child_by_field_name("right")
    if (
        left is None
        or right is None
        or right.type not in {"function_expression", "arrow_function"}
    ):
        return None
    name = _member_property(parsed, left)
    return _function_fact(parsed, name, assignment) if name else None


def _member_property(parsed: _ParsedSource, node: Node) -> str | None:
    if node.type != "member_expression":
        return None
    property_node = node.child_by_field_name("property")
    return parsed.text(property_node) if property_node is not None else None


def _exported_names(parsed: _ParsedSource, statement: Node) -> set[str]:
    names: set[str] = set()
    for node in _walk(statement):
        if node.type != "export_specifier":
            continue
        name = node.child_by_field_name("name")
        alias = node.child_by_field_name("alias")
        if name is not None:
            names.add(parsed.text(alias or name))
    return names


def _declaration_names(parsed: _ParsedSource, declaration: Node) -> set[str]:
    names: set[str] = set()
    if declaration.type in {
        "function_declaration",
        "generator_function_declaration",
        "class_declaration",
        "abstract_class_declaration",
    }:
        name_node = declaration.child_by_field_name("name")
        if name_node is not None:
            names.add(parsed.text(name_node))
    elif declaration.type in {"lexical_declaration", "variable_declaration"}:
        for declarator in declaration.named_children:
            if declarator.type != "variable_declarator":
                continue
            name_node = declarator.child_by_field_name("name")
            if name_node is not None and name_node.type == "identifier":
                names.add(parsed.text(name_node))
    return names


def _commonjs_export_names(parsed: _ParsedSource, statement: Node) -> set[str]:
    names: set[str] = set()
    for node in _walk(statement):
        if node.type != "assignment_expression":
            continue
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None:
            continue
        left_text = parsed.text(left)
        if left_text in {"module.exports", "exports"} and right is not None:
            if right.type == "object":
                for child in right.named_children:
                    if child.type == "shorthand_property_identifier":
                        names.add(parsed.text(child))
                    elif child.type == "pair":
                        key = child.child_by_field_name("key")
                        if key is not None:
                            rendered = _property_name(parsed, key, {})
                            if rendered:
                                names.add(rendered)
        elif left_text.startswith(("exports.", "module.exports.")):
            property_name = _member_property(parsed, left)
            if property_name:
                names.add(property_name)
    return names
