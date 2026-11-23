"""Bounded subprocess execution for Kode's autonomous coding workflow."""
from __future__ import annotations

from collections import deque
import os
import subprocess
import threading


def run_bounded_process(
    cmd,
    *,
    cwd,
    env,
    should_stop,
    timeout,
    max_capture_bytes,
    max_observation,
    redact,
):
    """Run a bounded process while retaining only a safe, bounded output tail."""
    import signal
    import time

    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        **kwargs,
    )

    chunks = deque()
    captured_bytes = 0
    truncated = False
    capture_lock = threading.Lock()

    def drain_output():
        nonlocal captured_bytes, truncated
        try:
            while True:
                block = proc.stdout.read(64 * 1024)
                if not block:
                    break
                with capture_lock:
                    chunks.append(block)
                    captured_bytes += len(block)
                    while captured_bytes > max_capture_bytes and chunks:
                        excess = captured_bytes - max_capture_bytes
                        oldest = chunks[0]
                        if len(oldest) <= excess:
                            captured_bytes -= len(chunks.popleft())
                        else:
                            chunks[0] = oldest[excess:]
                            captured_bytes -= excess
                        truncated = True
        except (OSError, ValueError):
            pass
        finally:
            try:
                proc.stdout.close()
            except (OSError, ValueError):
                pass

    reader = threading.Thread(
        target=drain_output,
        name="ai1code-process-output",
        daemon=True,
    )
    reader.start()

    end = time.monotonic() + timeout
    note = ""
    while proc.poll() is None or reader.is_alive():
        if should_stop():
            note = "\n(با Stop متوقف شد)"
        elif time.monotonic() > end:
            note = f"\n(بعد از {timeout} ثانیه متوقف شد)"
        if note:
            try:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5,
                        check=False,
                    )
                else:
                    os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError, subprocess.TimeoutExpired):
                try:
                    proc.kill()
                except (ProcessLookupError, OSError):
                    pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except (ProcessLookupError, OSError):
                    pass
                proc.wait(timeout=2)
            reader.join(timeout=5)
            if reader.is_alive():
                try:
                    proc.stdout.close()
                except (OSError, ValueError):
                    pass
                reader.join(timeout=1)
            break
        time.sleep(0.3)

    if proc.poll() is None:
        proc.wait()
    reader.join(timeout=5)

    with capture_lock:
        out = b"".join(chunks)
        was_truncated = truncated

    # The ring buffer can begin in the middle of a line. Drop that partial
    # line before secret redaction so a key assignment is never split away
    # from its marker and accidentally exposed in the retained output.
    if was_truncated:
        first_line_end = out.find(b"\n")
        out = out[first_line_end + 1:] if first_line_end >= 0 else b""

    output = redact(out.decode("utf-8", "replace"))
    if was_truncated:
        output += "\n[بخش ابتدایی خروجی طولانی برای محدودیت حافظه حذف شد]"
    return_code = proc.returncode if not note else -1
    return return_code, (output + note)[-max_observation:]

