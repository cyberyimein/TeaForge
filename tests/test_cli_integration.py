from pathlib import Path

from typer.testing import CliRunner

from teaforge.cli import app

runner = CliRunner()


def test_generate_and_get_commands(tmp_path):
    html_path = tmp_path / "pcl.html"
    source = Path("tests/fixtures/test_sample_pytest.py")

    result = runner.invoke(
        app,
        ["pcl", "generate", "--path", str(source), "--output", str(html_path)],
    )
    assert result.exit_code == 0

    output_dir = tmp_path / "test_sample_pytest"
    generated_html = output_dir / "pcl-test-create-user-normal.html"
    generated_json = output_dir / "pcl-test-create-user-normal.json"
    assert generated_html.exists()
    assert generated_json.exists()
    assert (output_dir / "pcl-test-create-user-boundary.html").exists()
    assert (output_dir / "pcl-test-get-user-exceptional-not-found.html").exists()
    html_content = generated_html.read_text(encoding="utf-8")
    assert html_content.count('class="case-head"') == 25
    assert "Bug No." in html_content
    assert "実施日" in html_content

    get_result = runner.invoke(
        app,
        ["get", "--path", str(generated_html), "--testcase", "TC-001"],
    )
    assert get_result.exit_code == 0
    assert "テストケース番号: TC-001" in get_result.stdout


def test_get_command_reads_embedded_html_without_sibling_json(tmp_path):
    html_path = tmp_path / "pcl.html"
    source = Path("tests/fixtures/test_sample_pytest.py")

    result = runner.invoke(
        app,
        ["pcl", "generate", "--path", str(source), "--output", str(html_path)],
    )
    assert result.exit_code == 0

    generated_html = tmp_path / "test_sample_pytest" / "pcl-test-create-user-normal.html"
    generated_json = generated_html.with_suffix(".json")
    generated_json.unlink()

    get_result = runner.invoke(
        app,
        ["get", "--path", str(generated_html), "--testcase", "TC-001"],
    )
    assert get_result.exit_code == 0
    assert "テストケース番号: TC-001" in get_result.stdout
