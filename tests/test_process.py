import os
import sys
import time

import pytest

from teaforge.process import (
    ProcessTimeoutError,
    WorkflowDeadline,
    bounded_process_detail,
    run_process,
)


def test_process_detail_prefers_stderr_and_removes_terminal_controls():
    detail = bounded_process_detail("\x1b[31mfailed\x1b[0m", "ignored")

    assert detail == "failed"


def test_process_detail_preserves_head_and_tail_when_truncated():
    detail = bounded_process_detail(None, "start" + ("x" * 500) + "finish", limit=128)

    assert detail.startswith("start")
    assert "truncated" in detail
    assert detail.endswith("finish")
    assert len(detail) <= 128


def test_process_detail_rejects_unusable_limit():
    with pytest.raises(ValueError, match="at least 128"):
        bounded_process_detail("error", None, limit=20)


def test_run_process_returns_structured_result():
    result = run_process(
        [sys.executable, "-c", "print('ready')"],
        operation="probe",
        timeout_seconds=5,
    )

    assert result.returncode == 0
    assert result.stdout == "ready\n"
    assert result.stderr == ""
    assert result.duration_seconds >= 0
    assert result.stdout_truncated is False


def test_run_process_drains_large_output_with_a_memory_bound():
    result = run_process(
        [sys.executable, "-c", "print('start' + 'x' * 10000 + 'finish')"],
        operation="large-output probe",
        timeout_seconds=5,
        output_limit=1024,
    )

    assert result.stdout.startswith("start")
    assert "process output truncated" in result.stdout
    assert result.stdout.rstrip().endswith("finish")
    assert len(result.stdout.encode()) <= 1024
    assert result.stdout_truncated is True


def test_run_process_timeout_carries_bounded_diagnostics():
    with pytest.raises(ProcessTimeoutError) as error:
        run_process(
            [
                sys.executable,
                "-c",
                "import time; print('started', flush=True); time.sleep(30)",
            ],
            operation="slow probe",
            timeout_seconds=0.1,
            terminate_grace_seconds=0.2,
        )

    assert error.value.code == "process-timeout"
    assert error.value.result.stdout == "started\n"
    assert "0.1 seconds" in str(error.value)


def test_workflow_deadline_shares_one_monotonic_budget():
    now = [10.0]
    deadline = WorkflowDeadline.start(
        "two-stage workflow",
        12,
        clock=lambda: now[0],
    )

    now[0] = 14.5

    assert deadline.remaining_seconds() == pytest.approx(7.5)


def test_workflow_deadline_fails_before_starting_another_process():
    now = [10.0]
    deadline = WorkflowDeadline.start(
        "two-stage workflow",
        5,
        clock=lambda: now[0],
    )
    now[0] = 15.0

    with pytest.raises(ProcessTimeoutError) as error:
        deadline.remaining_seconds()

    assert error.value.code == "process-timeout"
    assert error.value.result.args == ()
    assert error.value.result.duration_seconds == pytest.approx(5.0)
    assert "two-stage workflow timed out after 5 seconds" in str(error.value)


def test_run_process_timeout_terminates_descendants():
    parent = (
        "import subprocess, sys, time; time.sleep(0.2); "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        "print(child.pid, flush=True); time.sleep(30)"
    )

    with pytest.raises(ProcessTimeoutError) as error:
        run_process(
            [sys.executable, "-c", parent],
            operation="process-tree probe",
            timeout_seconds=0.5,
            terminate_grace_seconds=0.2,
        )

    child_pid = int(error.value.result.stdout.strip())
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if not _process_is_alive(child_pid):
            break
        time.sleep(0.02)
    else:
        pytest.fail(f"descendant process {child_pid} survived the workflow timeout")


def _process_is_alive(process_id: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(process_id, 0)
        except ProcessLookupError:
            return False
        return True

    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(
        process_query_limited_information,
        False,
        process_id,
    )
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)
