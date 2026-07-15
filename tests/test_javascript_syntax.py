import pytest

from teaforge.javascript.syntax import (
    JavaScriptSyntaxError,
    extract_imports,
    extract_test_cases,
    parse_calls,
    parse_source_functions,
    source_defines_symbol,
)


def test_imports_are_structural_and_ignore_comments_strings_and_regex_literals():
    source = r'''
// import { fake } from "./comment";
const sample = "const hidden = require('./string')";
const pattern = /require\(['"]\.\/regex/;
import primary, { createUser as makeUser, getUser } from "../src/user";
import * as helpers from "../src/helpers";
const { load: loadUser, save } = require("../src/store");
const api = require("../src/api").client;
'''

    imports = extract_imports(source, suffix=".ts", source_name="user.test.ts")

    assert [(item.module, item.local_name, item.imported_name) for item in imports] == [
        ("../src/user", "primary", "default"),
        ("../src/user", "makeUser", "createUser"),
        ("../src/user", "getUser", "getUser"),
        ("../src/helpers", "helpers", "*"),
        ("../src/store", "loadUser", "load"),
        ("../src/store", "save", "save"),
        ("../src/api", "api", "client"),
    ]


def test_nested_describe_each_preserves_full_names_and_row_context():
    source = '''
describe.each([{ role: "admin" }, { role: "guest" }])("role $role", ({ role }) => {
  describe("creation", () => {
    test(`creates ${role}`, () => {
      const actual = createUser({ role });
      expect(actual.role).toBe(role);
    });
  });
});
'''

    cases = extract_test_cases(source, suffix=".ts", source_name="user.test.ts")

    assert [case.title for case in cases] == ["creates admin", "creates guest"]
    assert [case.full_name for case in cases] == [
        "role admin creation creates admin",
        "role guest creation creates guest",
    ]
    assert [case.context for case in cases] == [
        {"role": "admin"},
        {"role": "guest"},
    ]
    assert "createUser({ role })" in cases[0].body


def test_test_each_expands_positional_rows_without_matching_fake_tests():
    source = '''
const text = "test('fake', () => {})";
// test("comment", () => {});
test.each([
  ["a", 0],
  ["tea-max", 120],
])("create user %s %d", (name, age) => {
  expect(createUser({ name, age }).age).toBe(age);
});
'''

    cases = extract_test_cases(source, suffix=".js")

    assert [case.title for case in cases] == [
        "create user a 0",
        "create user tea-max 120",
    ]
    assert [case.context for case in cases] == [
        {"name": "a", "age": 0},
        {"name": "tea-max", "age": 120},
    ]


@pytest.mark.parametrize(
    ("suffix", "source", "expected"),
    [
        (".js", "export function value() { return 1; }", ["value"]),
        (
            ".ts",
            "export function identity<T>(value: T): T { return value; }",
            ["identity"],
        ),
        (".tsx", "export const Card = () => <section>Tea</section>;", ["Card"]),
    ],
)
def test_language_matrix_parses_javascript_typescript_and_tsx(
    suffix: str,
    source: str,
    expected: list[str],
):
    assert [
        function.name
        for function in parse_source_functions(source, suffix=suffix)
    ] == expected


def test_source_function_index_handles_arrows_classes_and_ignores_nested_helpers():
    source = '''
export async function loadUser<T>(id: number): Promise<T> {
  function nestedHelper() { return id; }
  return fetchUser<T>(id);
}
export const saveUser = async (input: User) => {
  return persist(input);
};
export const oneArg = value => value;
export class UserService {
  constructor() {}
  load(id: number) { return loadUser(id); }
  save = (input: User) => persist(input);
  private internal() { return true; }
}
'''

    functions = parse_source_functions(source, suffix=".ts", source_name="user.ts")

    assert [function.name for function in functions] == [
        "loadUser",
        "saveUser",
        "oneArg",
        "UserService.load",
        "UserService.save",
        "UserService.internal",
    ]
    assert "nestedHelper" not in {function.name for function in functions}
    assert all(function.start_line <= function.end_line for function in functions)


def test_calls_are_structural_and_keep_nested_source_order():
    source = '''
const fake = "hiddenCall(1)";
const result = createUser(normalize({ name: "tea" }));
expect(result.name).toBe("tea");
'''

    calls = parse_calls(source, suffix=".ts")

    assert [call.callee for call in calls] == [
        "createUser",
        "normalize",
        "expect",
    ]
    assert calls[0].arguments == ('normalize({ name: "tea" })',)


def test_export_and_commonjs_symbol_evidence_is_structural():
    esm = '''
const hidden = () => 0;
export function createUser() { return hidden(); }
const load = () => 1;
export { load as loadUser };
'''
    commonjs = '''
function createUser() {}
function loadUser() {}
module.exports = { createUser, load: loadUser };
'''

    assert source_defines_symbol(esm, "createUser", suffix=".ts")
    assert source_defines_symbol(esm, "loadUser", suffix=".ts")
    assert source_defines_symbol(commonjs, "createUser", suffix=".js")
    assert source_defines_symbol(commonjs, "load", suffix=".js")
    assert not source_defines_symbol(esm, "hidden", suffix=".ts")
    assert not source_defines_symbol(esm, "fake", suffix=".ts")


def test_default_export_is_proven_without_treating_local_declarations_as_exports():
    source = '''
const localOnly = () => false;
export default function createUser() { return true; }
'''

    assert source_defines_symbol(source, "default", suffix=".js")
    assert not source_defines_symbol(source, "createUser", suffix=".js")
    assert not source_defines_symbol(source, "localOnly", suffix=".js")


def test_invalid_syntax_reports_stable_code_and_source_location():
    with pytest.raises(JavaScriptSyntaxError) as error:
        extract_test_cases(
            "test('broken', () => {",
            suffix=".ts",
            source_name="broken.test.ts",
        )

    assert error.value.code == "javascript-syntax-error"
    assert "broken.test.ts:1:" in str(error.value)
