from __future__ import annotations

import importlib
import unittest


class ToolAgentImportRegressionTests(unittest.TestCase):
    def test_tool_agent_module_imports(self):
        module = importlib.import_module("kira.tools.agent")
        self.assertTrue(hasattr(module, "ToolAgent"))


if __name__ == "__main__":
    unittest.main()
