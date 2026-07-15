import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import teaforge.jest.project as project_module
import teaforge.jest.runtime as runtime_module
from teaforge.jest.parser import parse_jest_documents
from teaforge.jest.project import collect_jest_test_files
from teaforge.jest.runtime import (
    JestAssertionEvidence,
    JestEvidenceRun,
    JestRuntimeEvidenceUnavailableError,
    capture_jest_assertions,
    enrich_documents_with_runtime_evidence,
    load_jest_evidence,
)
from teaforge.pcl.backends import parse_documents_for_framework
from teaforge.pcl.render import render_pcl_html


def test_runtime_evidence_enriches_jest_document_without_replacing_static_expectation():
    documents = parse_jest_documents(Path("tests/fixtures/test_sample_jest.test.ts"))
    create_document = next(document for document in documents if document.method == "createUser")
    original_checks = list(create_document.testcases[0].output_checks)
    evidence = [
        JestAssertionEvidence(
            test_name="create user normal",
            test_path=str(Path("tests/fixtures/test_sample_jest.test.ts").resolve()),
            matcher="toBe",
            expected=['"tea"'],
            actual='"tea"',
            passed=True,
        ),
        JestAssertionEvidence(
            test_name="create user normal",
            test_path=str(Path("tests/fixtures/test_sample_jest.test.ts").resolve()),
            matcher="toBe",
            expected=["20"],
            actual="20",
            passed=True,
        ),
    ]

    matched = enrich_documents_with_runtime_evidence(documents, evidence)

    case = create_document.testcases[0]
    assert matched == 1
    assert case.output_checks == original_checks
    assert case.execution_status == "passed"
    assert case.assertion_evidence[0].actual == '"tea"'
    html = render_pcl_html(create_document)
    assert "Jest 実行証拠" in html
    assert '"tea"' in html


def test_capture_jest_assertions_uses_project_local_jest_and_jsonl(tmp_path, monkeypatch):
    project = tmp_path / "project"
    test_file = project / "sample.test.js"
    jest_bin = project / "node_modules" / ".bin" / "jest"
    project_setup = project / "tests" / "setup.js"
    test_file.parent.mkdir(parents=True)
    jest_bin.parent.mkdir(parents=True)
    (project / "package.json").write_text('{"name":"fixture"}', encoding="utf-8")
    test_file.write_text("test('runtime value', () => expect(2).toBe(2));", encoding="utf-8")
    jest_bin.write_text("", encoding="utf-8")
    now = [50.0]
    timeout_budgets: list[float] = []
    monkeypatch.setattr("teaforge.process.time.monotonic", lambda: now[0])

    def fake_run(
        command,
        *,
        cwd,
        environment,
        timeout_seconds,
        operation,
    ):
        assert command[0] == str(jest_bin)
        timeout_budgets.append(timeout_seconds)
        if "--showConfig" in command:
            now[0] += 6
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "configs": [
                            {"setupFilesAfterEnv": [str(project_setup)]}
                        ]
                    }
                ),
                stderr="",
            )
        assert "--runTestsByPath" in command
        assert "--setupFilesAfterEnv" in command
        setup_values = [
            command[index + 1]
            for index, value in enumerate(command)
            if value == "--setupFilesAfterEnv"
        ]
        assert setup_values[0] == str(project_setup)
        assert setup_values[-1].endswith("runtime-listener.cjs")
        assert cwd == project
        payload = {
            "schema_version": 1,
            "kind": "assertion",
            "test_name": "runtime value",
            "test_path": str(test_file),
            "matcher": "toBe",
            "expected": ["2"],
            "actual": "2",
            "passed": True,
        }
        Path(environment["TEAFORGE_JEST_EVIDENCE_PATH"]).write_text(
            json.dumps(payload) + "\n", encoding="utf-8"
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(project_module, "run_process", fake_run)

    evidence = capture_jest_assertions(test_file, timeout_seconds=15)

    assert evidence == [
        JestAssertionEvidence(
            test_name="runtime value",
            test_path=str(test_file),
            matcher="toBe",
            expected=["2"],
            actual="2",
            passed=True,
        )
    ]
    assert timeout_budgets == pytest.approx([15.0, 9.0])


def test_auto_evidence_mode_records_static_fallback_warning(monkeypatch):
    def fail_capture(_path, *, timeout_seconds):
        raise JestRuntimeEvidenceUnavailableError("local Jest is unavailable")

    monkeypatch.setattr(runtime_module, "capture_jest_run", fail_capture)

    documents = parse_documents_for_framework(
        Path("tests/fixtures/test_sample_jest.test.ts"),
        "jest",
        evidence_mode="auto",
    )

    assert all(document.evidence_mode == "static-fallback" for document in documents)
    assert all("local Jest is unavailable" in document.evidence_warnings[0] for document in documents)


def test_runtime_evidence_mode_fails_when_capture_cannot_run(monkeypatch):
    def fail_capture(_path, *, timeout_seconds):
        raise JestRuntimeEvidenceUnavailableError("local Jest is unavailable")

    monkeypatch.setattr(runtime_module, "capture_jest_run", fail_capture)

    with pytest.raises(RuntimeError, match="local Jest is unavailable"):
        parse_documents_for_framework(
            Path("tests/fixtures/test_sample_jest.test.ts"),
            "jest",
            evidence_mode="runtime",
        )


def test_auto_evidence_mode_does_not_hide_jest_execution_failures(monkeypatch):
    def fail_capture(_path, *, timeout_seconds):
        raise RuntimeError("Jest configuration failed")

    monkeypatch.setattr(runtime_module, "capture_jest_run", fail_capture)

    with pytest.raises(RuntimeError, match="Jest configuration failed"):
        parse_documents_for_framework(
            Path("tests/fixtures/test_sample_jest.test.ts"),
            "jest",
            evidence_mode="auto",
        )


def test_runtime_collection_includes_jsx_and_tsx_tests(tmp_path):
    js_test = tmp_path / "user.test.js"
    jsx_test = tmp_path / "view.spec.jsx"
    tsx_test = tmp_path / "component.test.tsx"
    ignored = tmp_path / "helper.tsx"
    for path in (js_test, jsx_test, tsx_test, ignored):
        path.write_text("", encoding="utf-8")

    assert collect_jest_test_files(tmp_path) == [tsx_test, js_test, jsx_test]


def test_runtime_evidence_records_failing_jest_process_without_losing_report(
    monkeypatch,
):
    test_path = Path("tests/fixtures/test_sample_jest.test.ts")
    evidence = JestAssertionEvidence(
        test_name="create user normal",
        test_path=str(test_path.resolve()),
        matcher="toBe",
        expected=['"coffee"'],
        actual='"tea"',
        passed=False,
        error="expected coffee",
    )
    monkeypatch.setattr(
        runtime_module,
        "capture_jest_run",
        lambda path, *, timeout_seconds: JestEvidenceRun(
            evidence=[evidence],
            exit_code=1,
            stderr="one test failed",
            warnings=("Jest evidence was capped.",),
        ),
    )

    documents = parse_documents_for_framework(
        test_path,
        "jest",
        evidence_mode="runtime",
    )

    create_document = next(
        document for document in documents if document.method == "createUser"
    )
    assert create_document.runtime_exit_code == 1
    assert create_document.runtime_tests_passed is False
    assert create_document.evidence_warnings[0] == "Jest evidence was capped."
    assert "failing tests" in create_document.evidence_warnings[1]
    assert create_document.testcases[0].execution_status == "failed"


def test_runtime_evidence_uses_describe_identity_for_duplicate_test_titles(tmp_path):
    source = tmp_path / "user.ts"
    test_file = tmp_path / "user.test.ts"
    source.write_text(
        "export function createUser(role: string) { return role; }",
        encoding="utf-8",
    )
    test_file.write_text(
        'import { createUser } from "./user";\n'
        'describe("admin", () => {\n'
        '  test("creates user", () => { expect(createUser("admin")).toBe("admin"); });\n'
        '});\n'
        'describe("guest", () => {\n'
        '  test("creates user", () => { expect(createUser("guest")).toBe("guest"); });\n'
        '});\n',
        encoding="utf-8",
    )
    documents = parse_jest_documents(test_file)
    evidence = [
        JestAssertionEvidence(
            test_name="admin creates user",
            test_path=str(test_file.resolve()),
            matcher="toBe",
            expected=['"admin"'],
            actual='"admin"',
            passed=True,
        ),
        JestAssertionEvidence(
            test_name="guest creates user",
            test_path=str(test_file.resolve()),
            matcher="toBe",
            expected=['"guest"'],
            actual='"guest"',
            passed=True,
        ),
    ]

    matched = enrich_documents_with_runtime_evidence(documents, evidence)

    cases = documents[0].testcases
    assert matched == 2
    assert [case.test_full_name for case in cases] == [
        "admin creates user",
        "guest creates user",
    ]
    assert [case.assertion_evidence[0].actual for case in cases] == [
        '"admin"',
        '"guest"',
    ]


def test_runtime_evidence_uses_full_test_path_for_duplicate_names(tmp_path):
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    for directory, value in ((first_dir, "tea"), (second_dir, "coffee")):
        directory.mkdir()
        (directory / "user.js").write_text(
            "export function createUser() { return 'user'; }",
            encoding="utf-8",
        )
        (directory / "user.test.js").write_text(
            "import { createUser } from './user';\n"
            f"test('creates user', () => expect(createUser()).toBe('{value}'));\n",
            encoding="utf-8",
        )

    documents = [
        *parse_jest_documents(first_dir / "user.test.js"),
        *parse_jest_documents(second_dir / "user.test.js"),
    ]
    evidence = [
        JestAssertionEvidence(
            test_name="creates user",
            test_path=str(first_dir / "user.test.js"),
            matcher="toBe",
            expected=['"tea"'],
            actual='"tea"',
            passed=True,
        ),
        JestAssertionEvidence(
            test_name="creates user",
            test_path=str(second_dir / "user.test.js"),
            matcher="toBe",
            expected=['"coffee"'],
            actual='"coffee"',
            passed=True,
        ),
    ]

    matched = enrich_documents_with_runtime_evidence(documents, evidence)

    assert matched == 2
    assert [
        document.testcases[0].assertion_evidence[0].actual
        for document in documents
    ] == ['"tea"', '"coffee"']


def test_evidence_loader_preserves_producer_warning(tmp_path):
    path = tmp_path / "evidence.jsonl"
    assertion = {
        "schema_version": 1,
        "kind": "assertion",
        "test_name": "redacted value",
        "test_path": "sample.test.js",
        "matcher": "toEqual",
        "expected": ['{"password":"[REDACTED]"}'],
        "actual": '{"password":"[REDACTED]"}',
        "passed": True,
    }
    warning = {
        "schema_version": 1,
        "kind": "warning",
        "message": "Jest evidence was capped at 1 assertion records.",
    }
    path.write_text(
        json.dumps(assertion) + "\n" + json.dumps(warning) + "\n",
        encoding="utf-8",
    )

    evidence, warnings = load_jest_evidence(path)

    assert evidence[0].actual == '{"password":"[REDACTED]"}'
    assert warnings == ["Jest evidence was capped at 1 assertion records."]


def test_evidence_loader_rejects_unknown_schema(tmp_path):
    path = tmp_path / "future.jsonl"
    path.write_text(
        json.dumps({"schema_version": 99, "kind": "assertion"}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="Unsupported Jest evidence schema"):
        load_jest_evidence(path)


def test_evidence_loader_rejects_oversized_file(tmp_path, monkeypatch):
    path = tmp_path / "large.jsonl"
    path.write_text("123456", encoding="utf-8")
    monkeypatch.setattr(runtime_module, "MAX_EVIDENCE_FILE_BYTES", 5)

    with pytest.raises(RuntimeError, match="too large to load safely"):
        load_jest_evidence(path)


def test_real_jest_listener_redacts_sensitive_runtime_values():
    jest = Path("demo/jest_runtime/node_modules/.bin/jest")
    if not jest.exists():
        pytest.skip("locked Jest demo dependencies are not installed")

    evidence = capture_jest_assertions(
        Path("demo/jest_runtime/tests/user.test.js"),
        timeout_seconds=30,
    )

    rendered_values = "\n".join(
        [value for item in evidence for value in [item.actual, *item.expected]]
    )
    assert "demo-secret" not in rendered_values
    assert "[REDACTED]" in rendered_values
