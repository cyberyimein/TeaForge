from pathlib import Path

from teaforge.discovery import discover_files


def test_discovery_prunes_dependency_and_environment_trees(tmp_path):
    included = tmp_path / "packages" / "app" / "tests" / "user.test.js"
    included.parent.mkdir(parents=True)
    included.write_text("test('ok', () => {});", encoding="utf-8")

    for directory_name in ("node_modules", ".venv", "dist", "__pycache__"):
        ignored = tmp_path / directory_name / "nested" / "ignored.test.js"
        ignored.parent.mkdir(parents=True)
        ignored.write_text("test('ignored', () => {});", encoding="utf-8")

    files = discover_files(
        tmp_path,
        is_candidate=lambda path: path.name.endswith(".test.js"),
    )

    assert files == [included]


def test_discovery_accepts_one_explicit_file_even_under_excluded_directory(tmp_path):
    explicit = tmp_path / "node_modules" / "fixture.test.js"
    explicit.parent.mkdir(parents=True)
    explicit.write_text("test('fixture', () => {});", encoding="utf-8")

    files = discover_files(
        explicit,
        is_candidate=lambda path: path.name.endswith(".test.js"),
    )

    assert files == [explicit]


def test_discovery_returns_no_files_for_missing_path(tmp_path):
    assert discover_files(
        tmp_path / "missing",
        is_candidate=Path.is_file,
    ) == []
