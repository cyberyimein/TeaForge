from pathlib import Path

from teaforge.jest.parser import parse_jest_documents


def test_parse_jest_documents_extracts_subjects_and_inputs():
    sample = Path("tests/fixtures/test_sample_jest.test.ts")

    documents = parse_jest_documents(sample)

    assert len(documents) == 2
    create_document = next(document for document in documents if document.method == "createUser")
    get_document = next(document for document in documents if document.method == "getUser")

    assert create_document.file == "user.ts"
    assert create_document.source_path == "tests/fixtures/jest_sample/src/user.ts"
    assert len(create_document.testcases) == 3
    assert create_document.testcases[0].inputs["name"] == "tea"
    assert create_document.testcases[0].inputs["age"] == "20"
    assert create_document.testcases[1].testname == "create_user_boundary_age_a_0"
    assert create_document.testcases[1].inputs["name"] == "a"
    assert create_document.testcases[1].inputs["age"] == "0"
    assert create_document.testcases[1].output_checks == ["result.age == 0"]
    assert create_document.testcases[1].type == "I"
    assert create_document.testcases[2].inputs["name"] == "tea-max"
    assert create_document.testcases[2].inputs["age"] == "120"
    assert any(row.item == "name" and row.value == "tea" for row in create_document.input_rows)
    assert any(row.item == "age" and row.value == "120" for row in create_document.input_rows)

    assert get_document.file == "user.ts"
    assert get_document.testcases[0].type == "E"
    assert get_document.output_rows[0].item == "raises"


def test_parse_jest_documents_resolves_commonjs_require(tmp_path):
    source = tmp_path / "src" / "user.js"
    test_file = tmp_path / "tests" / "user.test.js"
    source.parent.mkdir(parents=True)
    test_file.parent.mkdir(parents=True)
    source.write_text(
        "function createUser(input) { return { id: 1, ...input }; }\n"
        "function getUser(id) { if (id === 404) throw new Error('not found'); }\n"
        "module.exports = { createUser, getUser };\n",
        encoding="utf-8",
    )
    test_file.write_text(
        "const { createUser, getUser: loadUser } = require('../src/user');\n"
        "test('creates user', () => {\n"
        "  const actual = createUser({ name: 'tea' });\n"
        "  expect(actual.name).toBe('tea');\n"
        "});\n"
        "test('loads user', () => { expect(() => loadUser(404)).toThrow('not found'); });\n",
        encoding="utf-8",
    )

    documents = parse_jest_documents(test_file)

    assert [document.method for document in documents] == ["createUser", "getUser"]
    assert all(document.file == "user.js" for document in documents)
    assert documents[0].testcases[0].inputs == {"name": "tea"}


def test_parse_jest_documents_resolves_default_export_to_local_call_name(tmp_path):
    source = tmp_path / "src" / "create-user.js"
    test_file = tmp_path / "tests" / "create-user.test.js"
    source.parent.mkdir(parents=True)
    test_file.parent.mkdir(parents=True)
    source.write_text(
        "export default function createUser(input) { return input; }\n",
        encoding="utf-8",
    )
    test_file.write_text(
        "import makeUser from '../src/create-user.js';\n"
        "test('creates user', () => expect(makeUser({name: 'tea'})).toBeTruthy());\n",
        encoding="utf-8",
    )

    documents = parse_jest_documents(test_file)

    assert len(documents) == 1
    assert documents[0].file == "create-user.js"
    assert documents[0].method == "makeUser"


def test_parse_jest_documents_preserves_tsx_grammar_for_callback_analysis(tmp_path):
    source = tmp_path / "src" / "card.tsx"
    test_file = tmp_path / "tests" / "card.test.tsx"
    source.parent.mkdir(parents=True)
    test_file.parent.mkdir(parents=True)
    source.write_text(
        "export function createCard(input: { name: string }) { return input; }\n",
        encoding="utf-8",
    )
    test_file.write_text(
        "import { createCard } from '../src/card';\n"
        "test('renders card', () => {\n"
        "  const preview = <section>Tea</section>;\n"
        "  expect(createCard({ name: 'tea' })).toEqual({ name: 'tea' });\n"
        "  expect(preview).toBeTruthy();\n"
        "});\n",
        encoding="utf-8",
    )

    documents = parse_jest_documents(test_file)

    assert len(documents) == 1
    assert documents[0].file == "card.tsx"
    assert documents[0].method == "createCard"
    assert documents[0].testcases[0].inputs == {"name": "tea"}
