from pathlib import Path

from teaforge.pcl.parser import parse_pytest_documents, parse_pytest_path


def test_parse_pytest_documents_splits_by_test_function():
    sample = Path("tests/fixtures/test_sample_pytest.py")
    documents = parse_pytest_documents(sample)

    assert len(documents) == 3
    assert [document.method for document in documents] == [
        "test_create_user_normal",
        "test_create_user_boundary",
        "test_get_user_exceptional_not_found",
    ]
    assert documents[1].title == "プログラムチェックリスト"
    assert len(documents[1].testcases) == 2
    assert documents[1].testcases[0].testcasecode == "TC-001"


def test_parse_pytest_path_keeps_merged_view_for_compatibility():
    sample = Path("tests/fixtures/test_sample_pytest.py")
    document = parse_pytest_path(sample)

    assert len(document.testcases) == 4
    assert any(case.type == "I" for case in document.testcases)
    assert any(case.type == "E" for case in document.testcases)


def test_parse_demo_pytest_extracts_real_input_values():
    sample = Path("demo/fastapi_crud/tests/test_items.py")
    documents = parse_pytest_documents(sample)
    first_document = next(document for document in documents if document.method == "test_create_item_normal")
    boundary_document = next(
        document for document in documents if document.method == "test_create_item_boundary_name"
    )

    first_case = first_document.testcases[0]
    assert first_case.inputs["name"] == "tea-green"
    assert first_case.inputs["quantity"] == "10"

    boundary_case = boundary_document.testcases[0]
    assert boundary_case.inputs["name"] == "a"
    assert boundary_case.inputs["quantity"] == "1"

    assert all("client" not in case.inputs for document in documents for case in document.testcases)
    assert any(row.item == "name" and row.value == "tea-green" for row in first_document.input_rows)
