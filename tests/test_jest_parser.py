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
