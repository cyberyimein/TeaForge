from teaforge.pcl.models import PCLDocument, PCLTestCase
from teaforge.pcl.render import render_pcl_html
from teaforge.pcl.service import get_testcase_description


def test_render_pcl_html_shows_frontend_sections_when_case_has_page_fields():
    document = PCLDocument.create(
        file="user-page.component.ts",
        method="UserPage",
        source_path="src/app/user-page.component.ts",
    )
    document.testcases.append(
        PCLTestCase(
            testcase="user page submit normal",
            testname="user_page_submit_normal",
            testcasecode="TC-001",
            inputs={"form.name": "tea", "form.quantity": "1"},
            output="saved message appears",
            type="N",
            screen_name="UserPage",
            entry_url="/users/new",
            preconditions=["logged-in user", "mock save API returns 200"],
            input_actions=["open:/users/new", "click:button.submit"],
            ui_outputs=["dom:.message contains saved"],
            navigation_outputs=["url == /done?id=1"],
            verification_mode="unit",
        )
    )

    html = render_pcl_html(document)

    assert "前端ページUT補足" in html
    assert "UserPage" in html
    assert "/users/new" in html
    assert "open:/users/new" in html
    assert "click:button.submit" in html
    assert "dom:.message contains saved" in html
    assert "url == /done?id=1" in html
    assert "teaforge-pcl-data" in html


def test_get_testcase_description_includes_frontend_page_fields():
    document = PCLDocument.create(
        file="user-page.component.ts",
        method="UserPage",
        source_path="src/app/user-page.component.ts",
    )
    document.testcases.append(
        PCLTestCase(
            testcase="user page submit normal",
            testname="user_page_submit_normal",
            testcasecode="TC-001",
            inputs={"form.name": "tea"},
            output="saved message appears",
            type="N",
            screen_name="UserPage",
            entry_url="/users/new",
            preconditions=["logged-in user"],
            input_actions=["open:/users/new", "click:button.submit"],
            ui_outputs=["dom:.message contains saved"],
            navigation_outputs=["url == /done?id=1"],
            verification_mode="playwright",
        )
    )

    description = get_testcase_description(document, "TC-001")

    assert "画面: UserPage" in description
    assert "入口URL: /users/new" in description
    assert "前提条件: logged-in user" in description
    assert "操作: open:/users/new; click:button.submit" in description
    assert "画面確認: dom:.message contains saved" in description
    assert "遷移確認: url == /done?id=1" in description
    assert "確認方法: playwright" in description