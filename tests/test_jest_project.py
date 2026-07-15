import json
import os
from types import SimpleNamespace

import pytest

import teaforge.jest.project as project_module
from teaforge.jest.project import JestProject
from teaforge.process import ProcessResult, ProcessTimeoutError


def test_jest_project_discovers_hoisted_workspace_installation(tmp_path):
    workspace = tmp_path / "workspace"
    package = workspace / "packages" / "web"
    test_file = package / "tests" / "user.test.ts"
    executable_name = "jest.cmd" if os.name == "nt" else "jest"
    jest_executable = workspace / "node_modules" / ".bin" / executable_name
    test_file.parent.mkdir(parents=True)
    jest_executable.parent.mkdir(parents=True)
    (package / "package.json").write_text('{"name":"web"}', encoding="utf-8")
    test_file.write_text("test('ok', () => expect(1).toBe(1));", encoding="utf-8")
    jest_executable.write_text("", encoding="utf-8")

    project = JestProject.discover(test_file)

    assert project.root == package
    assert project.executable == jest_executable
    assert project.test_files == (test_file.resolve(),)


def test_jest_project_run_uses_target_cwd_environment_and_timeout(
    tmp_path, monkeypatch
):
    project = JestProject(
        root=tmp_path,
        executable=tmp_path / "node_modules" / ".bin" / "jest",
        test_files=(tmp_path / "user.test.js",),
    )

    def fake_run(command, *, cwd, environment, timeout_seconds, operation):
        assert command == [str(project.executable), "--version"]
        assert cwd == tmp_path
        assert environment == {"TEAFORGE_TEST": "1"}
        assert timeout_seconds == 17
        assert operation == "Jest version check"
        return SimpleNamespace(returncode=0, stdout="30.0.0", stderr="")

    monkeypatch.setattr(project_module, "run_process", fake_run)

    result = project.run(
        ["--version"],
        timeout_seconds=17,
        operation="Jest version check",
        environment={"TEAFORGE_TEST": "1"},
    )

    assert result.stdout == "30.0.0"


def test_jest_project_translates_timeout(monkeypatch, tmp_path):
    project = JestProject(
        root=tmp_path,
        executable=tmp_path / "node_modules" / ".bin" / "jest",
        test_files=(tmp_path / "user.test.js",),
    )

    def time_out(command, **kwargs):
        raise ProcessTimeoutError(
            operation=kwargs["operation"],
            timeout_seconds=kwargs["timeout_seconds"],
            result=ProcessResult(
                args=tuple(command),
                returncode=-1,
                stdout="",
                stderr="",
                duration_seconds=9,
            ),
        )

    monkeypatch.setattr(project_module, "run_process", time_out)

    with pytest.raises(ProcessTimeoutError, match="timed out after 9 seconds") as error:
        project.run(
            ["--runInBand"],
            timeout_seconds=9,
            operation="Jest test execution",
        )

    assert error.value.code == "process-timeout"
    assert error.value.result.duration_seconds == 9


def test_jest_project_preserves_and_deduplicates_setup_files(monkeypatch, tmp_path):
    project = JestProject(
        root=tmp_path,
        executable=tmp_path / "node_modules" / ".bin" / "jest",
        test_files=(tmp_path / "user.test.js",),
    )
    setup_file = str(tmp_path / "tests" / "setup.js")

    def fake_run(command, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "configs": [
                        {"setupFilesAfterEnv": [setup_file]},
                        {"setupFilesAfterEnv": [setup_file]},
                    ]
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(project_module, "run_process", fake_run)

    assert project.setup_files_after_env(timeout_seconds=20) == [setup_file]


def test_jest_project_never_falls_back_to_npx(tmp_path):
    test_file = tmp_path / "tests" / "user.test.js"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("test('ok', () => expect(1).toBe(1));", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name":"fixture"}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="No project-local Jest executable"):
        JestProject.discover(test_file)
