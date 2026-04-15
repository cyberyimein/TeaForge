from pathlib import Path

from teaforge.playwright.parser import parse_playwright_documents


def test_parse_playwright_documents_extracts_page_actions_and_navigation():
    documents = parse_playwright_documents(Path("tests/fixtures/playwright_sample/user-page.spec.ts"))

    assert len(documents) == 2
    list_page = next(document for document in documents if document.method == "UsersPage")
    form_page = next(document for document in documents if document.method == "UsersNewPage")

    first_case = list_page.testcases[0]
    assert first_case.screen_name == "UsersPage"
    assert first_case.entry_url == "/users"
    assert first_case.input_actions == ["open:/users", "click:[data-testid=row-1]"]
    assert first_case.navigation_outputs == ["url == /detail?id=1", "url.query.id == 1"]
    assert first_case.verification_mode == "playwright"

    second_case = form_page.testcases[0]
    assert second_case.screen_name == "UsersNewPage"
    assert second_case.entry_url == "/users/new"
    assert "type:#email=bad-mail" in second_case.input_actions
    assert "focus:#password" in second_case.input_actions
    assert second_case.ui_outputs == ["dom:page.locator(\"[role=alert]\") contains 入力エラー"]
