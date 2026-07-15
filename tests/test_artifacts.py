from pathlib import Path

import pytest

import teaforge.artifacts as artifacts_module
from teaforge.artifacts import json_for_html_script, write_text_atomic


def test_json_for_html_script_preserves_data_without_closing_script_element():
    serialized = json_for_html_script(
        {"test": "</script><script>alert('tea')</script>", "separator": "\u2028"}
    )

    assert "</script>" not in serialized
    assert "\\u003c/script\\u003e" in serialized
    assert "\\u2028" in serialized


def test_atomic_write_replaces_complete_artifact(tmp_path):
    target = tmp_path / "report.json"
    target.write_text("old", encoding="utf-8")

    write_text_atomic(target, "new content")

    assert target.read_text(encoding="utf-8") == "new content"
    assert list(tmp_path.glob(".report.json.*.tmp")) == []


def test_atomic_write_preserves_old_artifact_when_replace_fails(
    tmp_path, monkeypatch
):
    target = tmp_path / "report.html"
    target.write_text("valid old report", encoding="utf-8")

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("disk refused replacement")

    monkeypatch.setattr(artifacts_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="disk refused replacement"):
        write_text_atomic(target, "partial new report")

    assert target.read_text(encoding="utf-8") == "valid old report"
    assert list(tmp_path.glob(".report.html.*.tmp")) == []
