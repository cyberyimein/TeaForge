"""Run external tools with bounded output, deadlines, and process-tree cleanup."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Sequence

DEFAULT_PROCESS_DETAIL_LIMIT = 8_000
DEFAULT_PROCESS_OUTPUT_LIMIT = 4 * 1024 * 1024
DEFAULT_TERMINATE_GRACE_SECONDS = 2.0
_OUTPUT_MARKER_RESERVE = 128
_ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


@dataclass(slots=True, frozen=True)
class ProcessResult:
    """One completed external process with memory-bounded captured streams."""

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    stdout_truncated: bool = False
    stderr_truncated: bool = False


class ProcessTimeoutError(RuntimeError):
    """A workflow deadline expired after TeaForge cleaned up the process tree."""

    code = "process-timeout"

    def __init__(
        self,
        *,
        operation: str,
        timeout_seconds: float,
        result: ProcessResult,
    ) -> None:
        self.operation = operation
        self.timeout_seconds = timeout_seconds
        self.result = result
        super().__init__(f"{operation} timed out after {timeout_seconds:g} seconds.")


@dataclass(slots=True, frozen=True)
class WorkflowDeadline:
    """Share one monotonic timeout budget across every process in a workflow."""

    operation: str
    timeout_seconds: float
    started_at: float
    _clock: Callable[[], float] = field(repr=False, compare=False)

    @classmethod
    def start(
        cls,
        operation: str,
        timeout_seconds: float,
        *,
        clock: Callable[[], float] | None = None,
    ) -> "WorkflowDeadline":
        if timeout_seconds <= 0:
            raise ValueError("Workflow timeout must be greater than zero seconds.")
        selected_clock = clock or time.monotonic
        return cls(
            operation=operation,
            timeout_seconds=timeout_seconds,
            started_at=selected_clock(),
            _clock=selected_clock,
        )

    def remaining_seconds(self) -> float:
        """Return the remaining budget or fail before another process is started."""
        elapsed = max(self._clock() - self.started_at, 0.0)
        remaining = self.timeout_seconds - elapsed
        if remaining > 0:
            return remaining
        raise ProcessTimeoutError(
            operation=self.operation,
            timeout_seconds=self.timeout_seconds,
            result=ProcessResult(
                args=(),
                returncode=-1,
                stdout="",
                stderr="",
                duration_seconds=elapsed,
            ),
        )


class _BoundedByteCapture:
    """Drain a byte stream while retaining only a diagnostic head and tail."""

    def __init__(self, limit: int) -> None:
        if limit < 1024:
            raise ValueError("Process output limit must be at least 1024 bytes.")
        storage_limit = limit - _OUTPUT_MARKER_RESERVE
        self._limit = limit
        self._head_limit = storage_limit // 3
        self._tail_limit = storage_limit - self._head_limit
        self._head = bytearray()
        self._tail = bytearray()
        self._total = 0

    @property
    def truncated(self) -> bool:
        return self._total > self._head_limit + self._tail_limit

    def feed(self, chunk: bytes) -> None:
        if not chunk:
            return
        self._total += len(chunk)
        head_space = self._head_limit - len(self._head)
        if head_space > 0:
            self._head.extend(chunk[:head_space])
            chunk = chunk[head_space:]
        if chunk:
            self._tail.extend(chunk)
            if len(self._tail) > self._tail_limit:
                del self._tail[: len(self._tail) - self._tail_limit]

    def text(self) -> str:
        if not self.truncated:
            captured = bytes(self._head + self._tail)
        else:
            omitted = self._total - len(self._head) - len(self._tail)
            marker = f"\n... [process output truncated {omitted} bytes] ...\n".encode()
            captured = bytes(self._head) + marker + bytes(self._tail)
        return (
            captured[: self._limit]
            .decode("utf-8", errors="replace")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
        )


def run_process(
    command: Sequence[str | os.PathLike[str]],
    *,
    operation: str,
    timeout_seconds: float,
    cwd: Path | str | None = None,
    environment: Mapping[str, str] | None = None,
    output_limit: int = DEFAULT_PROCESS_OUTPUT_LIMIT,
    terminate_grace_seconds: float = DEFAULT_TERMINATE_GRACE_SECONDS,
) -> ProcessResult:
    """Run one command without a shell and clean up its process tree on timeout."""
    if not command:
        raise ValueError("Process command must not be empty.")
    if timeout_seconds <= 0:
        raise ValueError("Process timeout must be greater than zero seconds.")
    if terminate_grace_seconds < 0:
        raise ValueError("Process terminate grace period must not be negative.")

    normalized_command = tuple(os.fspath(part) for part in command)
    stdout_capture = _BoundedByteCapture(output_limit)
    stderr_capture = _BoundedByteCapture(output_limit)
    popen_options: dict[str, object] = {}
    if os.name == "nt":
        popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_options["start_new_session"] = True

    started = time.monotonic()
    process = subprocess.Popen(
        normalized_command,
        cwd=os.fspath(cwd) if cwd is not None else None,
        env=dict(environment) if environment is not None else None,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **popen_options,
    )
    job_handle = _assign_windows_kill_job(process) if os.name == "nt" else None
    readers = (
        threading.Thread(
            target=_drain_stream,
            args=(process.stdout, stdout_capture),
            name="teaforge-stdout",
            daemon=True,
        ),
        threading.Thread(
            target=_drain_stream,
            args=(process.stderr, stderr_capture),
            name="teaforge-stderr",
            daemon=True,
        ),
    )
    for reader in readers:
        reader.start()

    timed_out = False
    deadline = started + timeout_seconds
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
    if not timed_out:
        for reader in readers:
            reader.join(timeout=max(deadline - time.monotonic(), 0.0))
        timed_out = any(reader.is_alive() for reader in readers)

    if timed_out:
        _terminate_process_tree(process, job_handle)
        _wait_for_exit(process, terminate_grace_seconds)
        for reader in readers:
            reader.join(timeout=terminate_grace_seconds)
        if process.poll() is None or any(reader.is_alive() for reader in readers):
            _kill_process_tree(process, job_handle)
            _wait_for_exit(process, terminate_grace_seconds)
            for stream in (process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()
            for reader in readers:
                reader.join(timeout=terminate_grace_seconds)

    _close_windows_job(job_handle)

    result = ProcessResult(
        args=normalized_command,
        returncode=process.returncode,
        stdout=stdout_capture.text(),
        stderr=stderr_capture.text(),
        duration_seconds=time.monotonic() - started,
        stdout_truncated=stdout_capture.truncated,
        stderr_truncated=stderr_capture.truncated,
    )
    if timed_out:
        raise ProcessTimeoutError(
            operation=operation,
            timeout_seconds=timeout_seconds,
            result=result,
        )
    return result


def _drain_stream(stream, capture: _BoundedByteCapture) -> None:
    if stream is None:
        return
    try:
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                return
            capture.feed(chunk)
    finally:
        stream.close()


def _wait_for_exit(process: subprocess.Popen[bytes], timeout_seconds: float) -> None:
    if process.poll() is not None:
        return
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        pass


def _terminate_process_tree(process: subprocess.Popen[bytes], job_handle) -> None:
    if os.name == "nt":
        if job_handle is not None:
            _terminate_windows_job(job_handle, exit_code=1)
            return
        if process.poll() is not None:
            return
        if _taskkill_windows_tree(process.pid):
            return
        try:
            process.terminate()
        except OSError:
            pass
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def _kill_process_tree(process: subprocess.Popen[bytes], job_handle) -> None:
    if os.name == "nt" and job_handle is not None:
        _terminate_windows_job(job_handle, exit_code=1)
        return
    if os.name == "nt":
        if process.poll() is not None:
            return
        if _taskkill_windows_tree(process.pid):
            return
        try:
            process.kill()
        except OSError:
            pass
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _taskkill_windows_tree(process_id: int) -> bool:
    """Use Windows' built-in tree termination when Job Object assignment is unavailable."""
    if os.name != "nt":
        return False
    try:
        cleanup = subprocess.Popen(
            ["taskkill", "/PID", str(process_id), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return cleanup.wait(timeout=5) == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _assign_windows_kill_job(process: subprocess.Popen[bytes]):
    """Assign a Windows process to a kill-on-close Job Object when available."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
        ]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        information = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        information.BasicLimitInformation.LimitFlags = 0x00002000
        configured = kernel32.SetInformationJobObject(
            job,
            9,
            ctypes.byref(information),
            ctypes.sizeof(information),
        )
        assigned = kernel32.AssignProcessToJobObject(job, int(process._handle))
        if not configured or not assigned:
            kernel32.CloseHandle(job)
            return None
        return job
    except Exception:
        return None


def _close_windows_job(job_handle) -> None:
    if os.name != "nt" or job_handle is None:
        return
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle(job_handle)
    except Exception:
        pass


def _terminate_windows_job(job_handle, *, exit_code: int) -> None:
    if os.name != "nt" or job_handle is None:
        return
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.TerminateJobObject(
            job_handle,
            exit_code,
        )
    except Exception:
        pass


def bounded_process_detail(
    stderr: str | None,
    stdout: str | None,
    *,
    limit: int = DEFAULT_PROCESS_DETAIL_LIMIT,
) -> str:
    """Select stderr-first diagnostics, remove terminal control text, and cap size."""
    if limit < 128:
        raise ValueError("Process detail limit must be at least 128 characters.")
    detail = (stderr or stdout or "").strip().replace("\x00", "")
    detail = _ANSI_ESCAPE.sub("", detail)
    if len(detail) <= limit:
        return detail

    marker = f"\n... [truncated {len(detail) - limit} characters] ...\n"
    remaining = max(limit - len(marker), 2)
    head_length = remaining // 3
    tail_length = remaining - head_length
    return f"{detail[:head_length]}{marker}{detail[-tail_length:]}"
