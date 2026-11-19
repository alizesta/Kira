"""Regression tests for hidden, cancellable voice installer subprocesses."""
import subprocess
import unittest
from unittest import mock

from kira import local_voice


class _FinishedProcess:
    pid = 123
    returncode = 0

    def poll(self):
        return self.returncode

    def communicate(self, timeout=None):
        return "installed", ""

    def terminate(self):
        self.returncode = -15

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


class _BlockedProcess(_FinishedProcess):
    returncode = None

    def communicate(self, timeout=None):
        raise subprocess.TimeoutExpired("pip", timeout)


class _CancelAfterStart:
    def __init__(self):
        self.calls = 0

    def is_set(self):
        self.calls += 1
        return self.calls >= 2


class LocalVoiceProcessTests(unittest.TestCase):
    def test_windows_installer_does_not_create_a_console_window(self):
        process = _FinishedProcess()
        with mock.patch.object(local_voice.os, "name", "nt"), \
             mock.patch("kira.local_voice.subprocess.Popen", return_value=process) as popen:
            result = local_voice._run_install_command(["python", "-m", "pip"], timeout=5)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            popen.call_args.kwargs["creationflags"],
            getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def test_cancelled_installer_terminates_the_running_process(self):
        process = _BlockedProcess()
        with mock.patch("kira.local_voice.subprocess.Popen", return_value=process):
            with self.assertRaisesRegex(RuntimeError, "لغو شد"):
                local_voice._run_install_command(
                    ["python", "-m", "pip"], timeout=30,
                    cancel_event=_CancelAfterStart(),
                )
        self.assertEqual(process.returncode, -15)

    def test_pre_cancelled_installer_never_starts_a_process(self):
        event = mock.Mock()
        event.is_set.return_value = True
        with mock.patch("kira.local_voice.subprocess.Popen") as popen:
            with self.assertRaisesRegex(RuntimeError, "لغو شد"):
                local_voice._run_install_command(
                    ["python", "-m", "pip"], timeout=30, cancel_event=event,
                )
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
