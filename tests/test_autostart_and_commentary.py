import unittest
from types import SimpleNamespace

from kira import autostart
from kira.vision_pipeline import HighlightGate, extract_highlight


class FakeReg:
    HKEY_CURRENT_USER, KEY_READ, KEY_SET_VALUE, REG_SZ = "HKCU", 1, 2, 1

    def __init__(self):
        self.values = {}

    def OpenKey(self, *a):
        outer = self
        class K:
            def __enter__(s): return s
            def __exit__(s, *e): return False
        return K()

    def SetValueEx(self, key, name, _r, _t, value): self.values[name] = value
    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return (self.values[name], 1)
    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


class AutostartTests(unittest.TestCase):
    def test_enable_disable_roundtrip(self):
        reg = FakeReg()
        self.assertFalse(autostart.is_enabled(reg))
        self.assertTrue(autostart.set_enabled(True, command="wscript.exe x autostart", winreg_module=reg))
        self.assertTrue(autostart.is_enabled(reg))
        self.assertTrue(autostart.set_enabled(False, winreg_module=reg))
        self.assertFalse(autostart.is_enabled(reg))
        self.assertTrue(autostart.set_enabled(False, winreg_module=reg))        # removing twice is fine

    def test_command_uses_vbs_with_autostart_arg(self):
        cmd = autostart.launcher_command("C:/Kira")
        self.assertTrue(cmd.startswith("wscript.exe") and cmd.endswith(" autostart") and "start_kira.vbs" in cmd)


class HighlightTests(unittest.TestCase):
    def test_extract(self):
        self.assertEqual(extract_highlight("وضعیت عادی\n[HIGHLIGHT] وای باس رو زدی!"), "وای باس رو زدی!")
        self.assertIsNone(extract_highlight("فقط توضیح"))
        self.assertIsNone(extract_highlight("x\n[HIGHLIGHT]   "))

    def test_gate_limits_rate_and_repeats(self):
        t = [0.0]
        gate = HighlightGate(min_interval=60, per_hour=2, clock=lambda: t[0])
        self.assertTrue(gate.allow("الف"))
        self.assertFalse(gate.allow("ب"))            # too soon
        t[0] = 61
        self.assertFalse(gate.allow("الف"))          # repeat
        self.assertTrue(gate.allow("ب"))
        t[0] = 200
        self.assertFalse(gate.allow("ج"))            # hourly cap


if __name__ == "__main__":
    unittest.main()
