"""Boundary tests for the central tool argument validator."""
import unittest

from kira.tools.registry import Param, Tool, ToolError, ToolRegistry


class ToolArgumentValidationTests(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.tool = Tool(
            "numeric_probe",
            "test numeric coercion",
            lambda args: "ok",
            (
                Param("count", "integer", required=True),
                Param("ratio", "number"),
            ),
        )

    def test_integer_accepts_integral_decimal_and_rejects_fractional_values(self):
        self.assertEqual(self.registry.clean_args(self.tool, {"count": "2.0"})["count"], 2)
        with self.assertRaises(ToolError):
            self.registry.clean_args(self.tool, {"count": "2.9"})
        with self.assertRaises(ToolError):
            self.registry.clean_args(self.tool, {"count": "NaN"})
        with self.assertRaises(ToolError):
            self.registry.clean_args(self.tool, {"count": "Infinity"})
        with self.assertRaises(ToolError):
            self.registry.clean_args(self.tool, {"count": "1e1000000"})
        with self.assertRaises(ToolError):
            self.registry.clean_args(self.tool, {"count": str(2**63)})
        with self.assertRaises(ToolError):
            self.registry.clean_args(self.tool, {"count": "9" * 10000})

    def test_number_rejects_non_finite_values(self):
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(value=value), self.assertRaises(ToolError):
                self.registry.clean_args(self.tool, {"count": 1, "ratio": value})

    def test_array_and_object_arguments_keep_their_declared_json_types(self):
        tool = Tool(
            "structured_probe",
            "test structured coercion",
            lambda args: "ok",
            (Param("items", "array", required=True), Param("options", "object")),
        )
        self.assertEqual(
            self.registry.clean_args(tool, {"items": [1, "two"], "options": {"enabled": True}}),
            {"items": [1, "two"], "options": {"enabled": True}},
        )
        with self.assertRaises(ToolError):
            self.registry.clean_args(tool, {"items": "not-an-array"})
        with self.assertRaises(ToolError):
            self.registry.clean_args(tool, {"items": [], "options": []})

    def test_integer_boolean_is_not_coerced_to_one_or_zero(self):
        with self.assertRaises(ToolError):
            self.registry.clean_args(self.tool, {"count": True})


if __name__ == "__main__":
    unittest.main()
