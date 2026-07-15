"""Inspect whether TeaForge can execute a requested workflow before generation."""

from __future__ import annotations

import importlib.util
import io
import json
import shutil
import sys
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, dataclass
from importlib import resources
from pathlib import Path

from teaforge import __version__
from teaforge.jest.project import JestProject
from teaforge.pcl.backends import normalize_pcl_framework
from teaforge.process import ProcessTimeoutError, bounded_process_detail, run_process


@dataclass(slots=True, frozen=True)
class CapabilityCheck:
    name: str
    status: str
    detail: str
    hint: str = ""


@dataclass(slots=True)
class DoctorReport:
    framework: str
    checks: list[CapabilityCheck]

    @property
    def ready(self) -> bool:
        return all(check.status != "error" for check in self.checks)

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "teaforge_version": __version__,
            "framework": self.framework,
            "ready": self.ready,
            "checks": [asdict(check) for check in self.checks],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def inspect_capabilities(
    *,
    framework: str,
    test_path: Path | None = None,
    require_mermaid: bool = False,
    require_pdf: bool = False,
    timeout_seconds: int = 10,
    python_executable: Path | None = None,
) -> DoctorReport:
    """Return a non-mutating readiness report for one TeaForge workflow."""
    normalized = normalize_pcl_framework(framework)
    if python_executable is not None and normalized != "pytest":
        raise ValueError("--python-executable is supported only for the pytest workflow.")
    checks = [
        CapabilityCheck(
            name="teaforge",
            status="ok",
            detail=f"TeaForge {__version__} on Python {sys.version.split()[0]}",
        )
    ]
    checks.extend(_resource_checks())
    checks.append(_javascript_syntax_check())

    if test_path is not None:
        resolved_test_path = test_path.expanduser().resolve()
        if resolved_test_path.exists():
            checks.append(
                CapabilityCheck("test-path", "ok", str(resolved_test_path))
            )
        else:
            checks.append(
                CapabilityCheck(
                    "test-path",
                    "error",
                    f"Path does not exist: {resolved_test_path}",
                    "Move/copy the tests into place or pass the correct --path.",
                )
            )
    else:
        resolved_test_path = None
        checks.append(
            CapabilityCheck(
                "test-path",
                "warning",
                "No target test path was supplied; project discovery was skipped.",
                "Pass --path to verify a real project.",
            )
        )

    if normalized == "pytest":
        checks.extend(
            _python_test_checks(
                python_executable=python_executable,
                timeout_seconds=timeout_seconds,
            )
        )
    elif normalized in {"jest", "angular"}:
        checks.extend(
            _jest_checks(resolved_test_path, timeout_seconds=timeout_seconds)
        )

    checks.append(
        _command_check(
            "mermaid",
            "mmdc",
            required=require_mermaid,
            install_hint="Install Mermaid CLI: npm install -g @mermaid-js/mermaid-cli",
            timeout_seconds=timeout_seconds,
        )
    )
    checks.append(_pdf_check(required=require_pdf))
    return DoctorReport(framework=normalized, checks=checks)


def format_doctor_report(report: DoctorReport) -> str:
    """Render a concise terminal view while preserving hints for agent callers."""
    labels = {"ok": "OK", "warning": "WARN", "error": "ERROR"}
    lines = [f"TeaForge doctor ({report.framework})"]
    for check in report.checks:
        lines.append(f"[{labels[check.status]}] {check.name}: {check.detail}")
        if check.hint:
            lines.append(f"       Hint: {check.hint}")
    lines.append(f"Ready: {'yes' if report.ready else 'no'}")
    return "\n".join(lines)


def _resource_checks() -> list[CapabilityCheck]:
    required_resources = (
        ("pcl-template", "teaforge.templates", "pcl.html"),
        ("coverage-template", "teaforge.templates", "coverage_report.html"),
        ("jest-listener", "teaforge.jest.assets", "runtime-listener.cjs"),
    )
    checks: list[CapabilityCheck] = []
    for name, package, filename in required_resources:
        present = resources.files(package).joinpath(filename).is_file()
        checks.append(
            CapabilityCheck(
                name,
                "ok" if present else "error",
                f"Packaged resource {'found' if present else 'missing'}: {filename}",
                "Reinstall TeaForge from a valid wheel." if not present else "",
            )
        )
    return checks


def _javascript_syntax_check() -> CapabilityCheck:
    """Verify that the packaged JS/TS grammars can build structural evidence."""
    try:
        from teaforge.javascript.syntax import extract_test_cases

        cases = extract_test_cases(
            "test('probe', () => expect(1).toBe(1));",
            suffix=".js",
            source_name="doctor-probe.js",
        )
        if len(cases) != 1 or cases[0].title != "probe":
            raise RuntimeError("the parser returned unexpected probe evidence")
    except Exception as exc:
        return CapabilityCheck(
            "javascript-syntax",
            "error",
            f"Tree-sitter JavaScript/TypeScript parser is unavailable: {exc}",
            "Reinstall TeaForge from a valid wheel with its base dependencies.",
        )
    return CapabilityCheck(
        "javascript-syntax",
        "ok",
        "Tree-sitter JavaScript/TypeScript grammars parsed the probe source.",
    )


def _python_test_checks(
    *,
    python_executable: Path | None,
    timeout_seconds: int,
) -> list[CapabilityCheck]:
    selected_python = (
        python_executable or Path(sys.executable)
    ).expanduser().absolute()
    if not selected_python.is_file():
        return [
            CapabilityCheck(
                "python-executable",
                "error",
                f"Python executable does not exist: {selected_python}",
                "Pass the Python launcher inside the target project's virtual environment.",
            )
        ]
    checks: list[CapabilityCheck] = []
    for module_name, install_name in (("pytest", "pytest"), ("coverage", "coverage")):
        try:
            result = run_process(
                [
                    str(selected_python),
                    "-c",
                    (
                        f"import {module_name}; "
                        f"print(getattr({module_name}, '__version__', 'available'))"
                    ),
                ],
                operation=f"{module_name} capability check",
                timeout_seconds=timeout_seconds,
            )
            present = result.returncode == 0
            version = result.stdout.strip() if present else ""
            failure = bounded_process_detail(result.stderr, result.stdout)
        except (OSError, ProcessTimeoutError) as exc:
            present = False
            version = ""
            failure = str(exc)
        checks.append(
            CapabilityCheck(
                module_name,
                "ok" if present else "error",
                (
                    f"{module_name} {version or 'available'} via {selected_python}"
                    if present
                    else f"{module_name} is unavailable via {selected_python}: {failure}"
                ),
                (
                    f"Install it in the target environment: {selected_python} -m pip install {install_name}"
                    if not present
                    else ""
                ),
            )
        )
    return checks


def _jest_checks(
    test_path: Path | None,
    *,
    timeout_seconds: int,
) -> list[CapabilityCheck]:
    checks = [
        _command_check(
            "node",
            "node",
            required=True,
            install_hint="Install a supported Node.js release.",
            timeout_seconds=timeout_seconds,
        )
    ]
    if test_path is None or not test_path.exists():
        return checks
    try:
        project = JestProject.discover(test_path)
        version_result = project.run(
            ["--version"],
            timeout_seconds=timeout_seconds,
            operation="Jest version check",
        )
        if version_result.returncode != 0:
            detail = bounded_process_detail(
                version_result.stderr, version_result.stdout
            )
            raise RuntimeError(f"Jest --version failed: {detail}")
        version = version_result.stdout.strip() or "unknown version"
        checks.append(
            CapabilityCheck(
                "jest",
                "ok",
                f"{version} at {project.executable} (root: {project.root})",
            )
        )
        checks.append(
            CapabilityCheck(
                "jest-tests",
                "ok",
                f"Discovered {len(project.test_files)} exact test file(s).",
            )
        )
    except RuntimeError as exc:
        checks.append(
            CapabilityCheck(
                "jest",
                "error",
                str(exc),
                "Run the target project's package-manager install command first.",
            )
        )
    return checks


def _command_check(
    name: str,
    executable: str,
    *,
    required: bool,
    install_hint: str,
    timeout_seconds: int,
) -> CapabilityCheck:
    path = shutil.which(executable)
    if path is None:
        return CapabilityCheck(
            name,
            "error" if required else "warning",
            f"Executable not found on PATH: {executable}",
            install_hint,
        )
    try:
        result = run_process(
            [path, "--version"],
            operation=f"{name} version check",
            timeout_seconds=timeout_seconds,
        )
    except (OSError, ProcessTimeoutError) as exc:
        return CapabilityCheck(
            name,
            "error" if required else "warning",
            f"Could not execute {path}: {exc}",
            install_hint,
        )
    detail = (result.stdout or result.stderr).strip().splitlines()
    version = detail[0] if detail else "version unavailable"
    status = "ok" if result.returncode == 0 else ("error" if required else "warning")
    return CapabilityCheck(name, status, f"{version} at {path}", install_hint if status != "ok" else "")


def _pdf_check(*, required: bool) -> CapabilityCheck:
    if importlib.util.find_spec("weasyprint") is None:
        return CapabilityCheck(
            "pdf",
            "error" if required else "warning",
            "WeasyPrint is not installed.",
            "Install TeaForge with the PDF extra: pip install 'teaforge[pdf]'",
        )
    try:
        diagnostics = io.StringIO()
        with redirect_stdout(diagnostics), redirect_stderr(diagnostics):
            from weasyprint import HTML

            payload = HTML(string="<html><body>TeaForge</body></html>").write_pdf()
        if not payload.startswith(b"%PDF-"):
            raise RuntimeError("WeasyPrint returned an invalid PDF payload.")
    except (OSError, RuntimeError) as exc:
        return CapabilityCheck(
            "pdf",
            "error" if required else "warning",
            f"WeasyPrint is installed but not operational: {exc}",
            "Install the required Pango/Cairo system libraries.",
        )
    return CapabilityCheck("pdf", "ok", "WeasyPrint produced a valid PDF payload.")
