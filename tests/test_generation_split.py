import json
from pathlib import Path

from teaforge.pcl.service import generate_pcl


def test_generate_pcl_splits_large_function_into_multiple_sheets(tmp_path):
    cases = ", ".join(str(index) for index in range(26))
    ids = ", ".join(f'"case_{index}"' for index in range(26))
    test_file = tmp_path / "test_many_cases.py"
    test_file.write_text(
        (
            "import pytest\n\n"
            f"@pytest.mark.parametrize('value', [{cases}], ids=[{ids}])\n"
            "def test_many_cases(value):\n"
            '    """多数ケースを分割すること。"""\n'
            "    assert value >= 0\n"
        ),
        encoding="utf-8",
    )

    outputs = generate_pcl(test_file, tmp_path / "many.html")

    assert len(outputs) == 2
    first_html, first_json = outputs[0]
    second_html, second_json = outputs[1]
    assert first_html.parent.name == "test_many_cases"
    assert second_html.parent.name == "test_many_cases"
    assert first_html.name == "many-test-many-cases-sheet-01.html"
    assert second_html.name == "many-test-many-cases-sheet-02.html"
    assert first_json.exists()
    assert second_json.exists()
    assert first_html.read_text(encoding="utf-8").count('class="case-head"') == 25


def test_generate_pcl_groups_outputs_by_subject_method(tmp_path):
    outputs = generate_pcl(Path("demo/fastapi_crud/tests/test_items.py"), tmp_path / "demo.html")

    html_names = [html_path.name for html_path, _ in outputs]
    json_paths = {json_path.name: json_path for _, json_path in outputs}

    assert len(outputs) == 4
    assert len(html_names) == len(set(html_names))
    assert {html_path.parent.name for html_path, _ in outputs} == {"main"}
    assert "demo-create-item.html" in html_names
    assert "demo-get-item.html" in html_names
    assert "demo-update-item.html" in html_names
    assert "demo-delete-item.html" in html_names

    create_payload = json.loads(json_paths["demo-create-item.json"].read_text(encoding="utf-8"))
    update_payload = json.loads(json_paths["demo-update-item.json"].read_text(encoding="utf-8"))

    assert create_payload["method"] == "create_item"
    assert len(create_payload["testcases"]) == 10
    assert update_payload["method"] == "update_item"
    assert len(update_payload["testcases"]) == 9
