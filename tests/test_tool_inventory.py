"""Regression tests for safe, compact ToolAgent capability discovery."""
import unittest

from kira.tools.registry import ToolRegistry, Tool, Param, READ


class ToolInventoryTests(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.registry.register(Tool(
            "read_alpha", "Read one alpha resource and return its contents",
            lambda args: "ok",
            (Param("path", "string", "resource path", True),),
            READ, ("system",),
        ))

    def test_malformed_pagination_arguments_fall_back_without_raising(self):
        report = self.registry.access.info_text(offset="not-a-number", limit={"bad": "value"}, recent=object())
        self.assertIn("نمایش: 1 تا 1", report)

    def test_default_inventory_is_compact(self):
        report = self.registry.access.info_text()
        self.assertIn("- read_alpha [system] — Read one alpha resource", report)
        self.assertNotIn("ورودی‌ها:", report)

    def test_exact_name_returns_full_tool_details(self):
        report = self.registry.access.info_text(name="READ_ALPHA")
        self.assertIn("ورودی‌ها: path (string، اجباری): resource path", report)
        self.assertIn("سطح ابزار/مجوز:", report)

    def test_unknown_name_is_reported_without_error(self):
        report = self.registry.access.info_text(name="missing_tool")
        self.assertIn("در رجیستری فعلی پیدا نشد", report)


if __name__ == "__main__":
    unittest.main()
