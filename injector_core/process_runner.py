"""Start a launcher only after Injector has recorded how to stop its processes."""
import os
import signal
import subprocess
import sys
import threading
import time


_DIAGNOSTIC_BYTES = 64 * 1024


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    for name, arguments, result in (
        ("CreateJobObjectW", [wintypes.LPVOID, wintypes.LPCWSTR], wintypes.HANDLE),
        ("GetCurrentProcess", [], wintypes.HANDLE),
        ("AssignProcessToJobObject", [wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
        ("OpenJobObjectW", [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
        ("TerminateJobObject", [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        ("SetInformationJobObject", [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD], wintypes.BOOL),
        ("QueryInformationJobObject", [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD, wintypes.LPVOID], wintypes.BOOL),
        ("CloseHandle", [wintypes.HANDLE], wintypes.BOOL),
    ):
        function = getattr(kernel, name)
        function.argtypes = arguments
        function.restype = result

    class BasicLimits(ctypes.Structure):
        _fields_ = [("ProcessTimeLimit", ctypes.c_longlong), ("JobTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", ctypes.c_ulonglong * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    class BasicAccounting(ctypes.Structure):
        _fields_ = [("Times", ctypes.c_longlong * 4), ("TotalPageFaultCount", wintypes.DWORD),
                    ("TotalProcesses", wintypes.DWORD), ("ActiveProcesses", wintypes.DWORD),
                    ("TotalTerminatedProcesses", wintypes.DWORD)]


def _join_job(name):
    handle = kernel.CreateJobObjectW(None, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
            raise ctypes.WinError(ctypes.get_last_error())
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    return handle


def terminate_job(name):
    job_object_terminate, job_object_query = 0x0008, 0x0004
    handle = kernel.OpenJobObjectW(job_object_terminate | job_object_query, False, name)
    if not handle:
        error = ctypes.get_last_error()
        if error == 2:  # ERROR_FILE_NOT_FOUND: no live job with this name
            return False
        raise ctypes.WinError(error)
    try:
        if not kernel.TerminateJobObject(handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())
        accounting = BasicAccounting()
        deadline = time.monotonic() + 3
        while True:
            if not kernel.QueryInformationJobObject(handle, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None):
                raise ctypes.WinError(ctypes.get_last_error())
            if not accounting.ActiveProcesses:
                break
            if time.monotonic() >= deadline:
                raise OSError("managed process shutdown timed out")
            time.sleep(0.02)
    finally:
        kernel.CloseHandle(handle)
    return True


def _save_diagnostics(path, content):
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
    except OSError:
        pass


def main():
    job, diagnostics, *command = sys.argv[1:]
    try:
        if os.name == "nt":
            # Leaving the job handle open cleans up the tree on runner exit.
            _join_job(job)
        if sys.stdin.buffer.read(1) != b"1":
            return 1
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, bufsize=0,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except OSError as error:
        _save_diagnostics(diagnostics, str(error).encode("utf-8", errors="replace"))
        return 1

    tail = bytearray()
    lock = threading.Lock()

    def drain():
        with process.stdout:
            while chunk := process.stdout.read(4096):
                with lock:
                    tail.extend(chunk)
                    del tail[:max(0, len(tail) - _DIAGNOSTIC_BYTES)]

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        result = process.wait()
        # A descendant can still hold the output pipe after its launcher exits.
        reader.join(timeout=0.3)
        with lock:
            report = f"Exit code: {result}\n".encode("utf-8") + bytes(tail)
        _save_diagnostics(diagnostics, report)
        return result
    finally:
        if os.name == "posix":
            os.killpg(os.getpgrp(), signal.SIGKILL)


if __name__ == "__main__":
    sys.exit(main())
