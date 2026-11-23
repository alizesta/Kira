"""Cancellation and process-reaping regressions for process-backed tools."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from kira.tools.cancellation import current_cancel_event
from kira.tools.winrunner import FixedScript, run_fixed


class _CancelOnSecondCheck:
    def __init__(self):
        self.checks = 0

    def is_set(self):
        self.checks += 1
        return self.checks >= 2


class _FakeProcess:
    pid = 2_147_483_000

    def __init__(self, stdout=b'{"ok":true}', stderr=b"", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.terminated = False
        self.killed = False
        self.communicate_calls = []

    def poll(self):
        return self.returncode

    def communicate(self, timeout=None):
        self.communicate_calls.append(timeout)
        if self.returncode is None and timeout is not None:
            raise subprocess.TimeoutExpired("powershell", timeout)
        return self.stdout, self.stderr

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class ToolAgentCancellationContextTests(unittest.TestCase):
    def test_tool_agent_scopes_the_owning_character_stop_event_to_handlers(self):
        from kira.tools.agent import ToolAgent

        class Registry:
            def __init__(self):
                self.seen_event = None

            def get(self, _name):
                return SimpleNamespace(categories=())

            def execute(self, _name, _args):
                self.seen_event = current_cancel_event()
                return "executed"

        agent = ToolAgent.__new__(ToolAgent)
        agent._init_session_turn_states()
        agent.registry = Registry()

        with agent._use_session("kira"):
            expected_event = agent._cancel
            result = agent._execute_guarded("probe", {})

        self.assertEqual(result, "executed")
        self.assertIs(agent.registry.seen_event, expected_event)
        self.assertIsNone(current_cancel_event())


class WinRunnerCancellationTests(unittest.TestCase):
    def setUp(self):
        self.script = FixedScript("test", 'Write-Output "{\"ok\":true}"')

    def test_pre_cancelled_operation_does_not_start_powershell(self):
        event = mock.Mock()
        event.is_set.return_value = True

        with mock.patch("kira.tools.winrunner.subprocess.Popen") as popen:
            result = run_fixed(self.script, cancel_event=event)

        self.assertTrue(result["cancelled"])
        popen.assert_not_called()

    def test_stop_terminates_and_reaps_the_running_process(self):
        event = _CancelOnSecondCheck()
        process = _FakeProcess(stdout=b"", returncode=None)

        with mock.patch(
            "kira.tools.winrunner.subprocess.Popen", return_value=process
        ) as popen:
            result = run_fixed(self.script, cancel_event=event)

        self.assertTrue(result["cancelled"])
        self.assertTrue(process.terminated)
        self.assertFalse(process.killed)
        self.assertGreaterEqual(len(process.communicate_calls), 1)
        self.assertTrue(popen.called)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_completed_process_wins_a_race_with_a_late_stop(self):
        event = mock.Mock()
        event.is_set.return_value = True
        process = _FakeProcess(stdout=b'{"ok":true}', returncode=0)

        with mock.patch(
            "kira.tools.winrunner.subprocess.Popen", return_value=process
        ):
            result = run_fixed(self.script, cancel_event=event)

        self.assertEqual(result, {"ok": True})
        self.assertEqual(process.communicate_calls, [0])

    def test_successful_process_output_is_parsed(self):
        process = _FakeProcess(stdout=b'noise\n{"ok":true,"value":7}')

        with mock.patch(
            "kira.tools.winrunner.subprocess.Popen", return_value=process
        ):
            result = run_fixed(self.script)

        self.assertEqual(result, {"ok": True, "value": 7})
        self.assertEqual(process.communicate_calls, [mock.ANY])

    def test_timeout_terminates_and_reaps_the_running_process(self):
        process = _FakeProcess(stdout=b"", returncode=None)

        with (
            mock.patch("kira.tools.winrunner.subprocess.Popen", return_value=process),
            mock.patch("kira.tools.winrunner.time.monotonic", side_effect=[0.0, 1.0]),
        ):
            result = run_fixed(self.script, timeout=0.2)

        self.assertTrue(result["fatal"])
        self.assertNotIn("cancelled", result)
        self.assertTrue(process.terminated)
        self.assertGreaterEqual(len(process.communicate_calls), 1)


class AudioCancellationTests(unittest.TestCase):
    def test_audio_tool_surfaces_process_stop_as_a_cancellation(self):
        from kira.tools.audio import AudioTools
        from kira.tools.registry import DENIED, ToolError

        with (
            mock.patch("kira.tools.audio.IS_WIN", True),
            mock.patch(
                "kira.tools.audio.run_fixed",
                return_value={
                    "ok": False,
                    "fatal": True,
                    "cancelled": True,
                    "error": "stopped",
                },
            ),
        ):
            with self.assertRaises(ToolError) as raised:
                AudioTools().get_volume({})

        self.assertEqual(raised.exception.status, DENIED)
        self.assertIn("Stop", str(raised.exception))


class BluetoothCancellationTests(unittest.TestCase):
    def test_bluetooth_runner_surfaces_process_stop_as_a_cancellation(self):
        from kira.tools.bluetooth import _run
        from kira.tools.registry import DENIED, ToolError

        with mock.patch(
            "kira.tools.bluetooth.run_fixed",
            return_value={
                "ok": False,
                "fatal": True,
                "cancelled": True,
                "error": "stopped",
            },
        ):
            with self.assertRaises(ToolError) as raised:
                _run("read")

        self.assertEqual(raised.exception.status, DENIED)
        self.assertIn("Stop", str(raised.exception))


class AudioScriptExtractionTests(unittest.TestCase):
    def test_audio_handlers_import_the_separate_immutable_script(self):
        from kira.tools.audio import _SCRIPT
        from kira.tools.audio_script import AUDIO_SCRIPT
        from kira.tools.winrunner import FixedScript

        self.assertIs(_SCRIPT, AUDIO_SCRIPT)
        self.assertIsInstance(AUDIO_SCRIPT, FixedScript)
        self.assertIn("namespace KiraAudio", AUDIO_SCRIPT.text)
        self.assertIn("KIRA_AUDIO_REQ", AUDIO_SCRIPT.text)


if __name__ == "__main__":
    unittest.main()
