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

    def test_structured_arguments_reject_nested_non_finite_values(self):
        tool = Tool("nested_probe", "test nested JSON", lambda args: "ok", (Param("payload", "object", required=True),))
        for payload in (
            {"values": [float("nan")]},
            {"values": [float("inf")]},
            {1: "non-string key"},
        ):
            with self.subTest(payload=payload), self.assertRaises(ToolError):
                self.registry.clean_args(tool, {"payload": payload})

    def test_structured_arguments_enforce_depth_and_size_limits(self):
        tool = Tool("nested_probe", "test nested JSON", lambda args: "ok", (Param("payload", "array", required=True),))
        too_deep = []
        cursor = too_deep
        for _ in range(34):
            child = []
            cursor.append(child)
            cursor = child
        with self.assertRaises(ToolError):
            self.registry.clean_args(tool, {"payload": too_deep})
        with self.assertRaises(ToolError):
            self.registry.clean_args(tool, {"payload": list(range(10001))})

    def test_integer_boolean_is_not_coerced_to_one_or_zero(self):
        with self.assertRaises(ToolError):
            self.registry.clean_args(self.tool, {"count": True})


if __name__ == "__main__":
    unittest.main()
