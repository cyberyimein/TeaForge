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
    create_document = next(document for document in documents if document.method == "create_item")
    first_case = next(case for case in create_document.testcases if case.testname == "test_create_item_normal")
    assert first_case.inputs["name"] == "tea-green"
    assert first_case.inputs["quantity"] == "10"

    boundary_case = next(
        case
        for case in create_document.testcases
        if case.testname == "test_create_item_boundary_name_inside[boundary_min_name_inside]"
    )
    assert boundary_case.inputs["name"] == "a"
    assert boundary_case.inputs["quantity"] == "1"

    assert all("client" not in case.inputs for document in documents for case in document.testcases)
    assert any(row.item == "name" and row.value == "tea-green" for row in create_document.input_rows)


def test_parse_demo_pytest_uses_tested_code_file_and_method():
    sample = Path("demo/fastapi_crud/tests/test_items.py")
    documents = parse_pytest_documents(sample)

    assert len(documents) == 4
    create_document = next(document for document in documents if document.method == "create_item")
    update_document = next(document for document in documents if document.method == "update_item")
    get_document = next(document for document in documents if document.method == "get_item")
    delete_document = next(document for document in documents if document.method == "delete_item")

    assert create_document.file == "main.py"
    assert create_document.source_path == "demo/fastapi_crud/app/main.py"
    assert update_document.file == "main.py"
    assert update_document.source_path == "demo/fastapi_crud/app/main.py"
    assert get_document.file == "main.py"
    assert get_document.source_path == "demo/fastapi_crud/app/main.py"
    assert delete_document.file == "main.py"
    assert delete_document.source_path == "demo/fastapi_crud/app/main.py"
    assert len(create_document.testcases) == 10
    assert len(update_document.testcases) == 9
    assert len(get_document.testcases) == 2
    assert len(delete_document.testcases) == 2
