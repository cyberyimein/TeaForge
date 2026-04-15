from pathlib import Path

from teaforge.angular.parser import parse_angular_documents


def test_parse_angular_documents_extracts_page_level_fields():
    documents = parse_angular_documents(Path("tests/fixtures/angular_sample"))

    assert len(documents) == 2
    user_page = next(document for document in documents if document.method == "UserPageComponent")
    user_form_page = next(document for document in documents if document.method == "UserFormPageComponent")

    assert user_page.file == "user-page.component.ts"
    assert user_page.source_path == "tests/fixtures/angular_sample/user-page.component.ts"
    assert len(user_page.testcases) == 2
    first_case = user_page.testcases[0]
    assert first_case.screen_name == "UserPage"
    assert first_case.entry_url == "/users/new"
    assert first_case.inputs["form.name"] == "tea"
    assert first_case.inputs["form.quantity"] == "1"
    assert "open:/users/new" in first_case.input_actions
    assert "click:submitButton" in first_case.input_actions
    assert "output.save emitted with {name: tea, quantity: 1}" in first_case.ui_outputs
    assert "dom:messageEl.textContent contains saved" in first_case.ui_outputs
    assert any(item.startswith("navigate:/done") for item in first_case.navigation_outputs)

    second_case = user_form_page.testcases[0]
    assert second_case.screen_name == "UserFormPage"
    assert second_case.entry_url == "/users/form"
    assert second_case.inputs["form.email"] == "bad-mail"
    assert "focus:emailInput" in second_case.input_actions
    assert "blur:emailInput" in second_case.input_actions
    assert second_case.preconditions == ["provider.userFormService.loadPreset returns {email: preset@example.com}"]
    assert second_case.ui_outputs == ["dom:screen.getByRole(\"alert\") contains 入力エラー"]
