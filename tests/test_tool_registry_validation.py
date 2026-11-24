"""Boundary tests for the central tool argument validator."""
import threading
import unittest

from kira.tools.wincontrol import Capability, WindowsControlLayer
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

    def test_registry_get_obeys_the_registry_lock(self):
        self.registry.register(self.tool)
        started = threading.Event()
        finished = threading.Event()
        found = []

        def read_tool():
            started.set()
            found.append(self.registry.get("numeric_probe"))
            finished.set()

        with self.registry._tools_lock:
            worker = threading.Thread(target=read_tool)
            worker.start()
            self.assertTrue(started.wait(1))
            self.assertFalse(finished.wait(0.05))

        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertTrue(finished.is_set())
        self.assertIs(found[0], self.tool)

    def test_json_schema_rejects_undeclared_arguments(self):
        schema = self.tool.json_schema()
        self.assertIs(schema["parameters"]["additionalProperties"], False)
        self.assertEqual(schema["parameters"]["required"], ["count"])
        self.assertEqual(set(schema["parameters"]["properties"]), {"count", "ratio"})

    def test_duplicate_capability_does_not_replace_the_registered_module_entry(self):
        registry = ToolRegistry()
        layer = WindowsControlLayer(registry)
        original = Capability(
            "duplicate_probe", "desktop", "original capability",
            lambda _args: "original", categories=("desktop",),
        )
        replacement = Capability(
            "duplicate_probe", "desktop", "replacement capability",
            lambda _args: "replacement", categories=("desktop",),
        )

        layer.register(original)
        with self.assertRaises(ValueError):
            layer.register(replacement)

        self.assertEqual(layer.capabilities(), [original])
        self.assertEqual(registry.get("duplicate_probe").description, "original capability")

    def test_always_visible_introspection_tool_is_available_for_every_category(self):
        introspection = Tool(
            "windows_control_info",
            "live tool inventory",
            lambda args: "inventory",
            (),
            categories=("system",),
            always_visible=True,
        )
        hidden = Tool("file_probe", "file probe", lambda args: "ok", (), categories=("files",))
        self.registry.register(introspection)
        self.registry.register(hidden)

        selected = self.registry.for_selected_categories({"apps"})
        self.assertEqual([tool.name for tool in selected], ["windows_control_info"])
        self.assertEqual([tool.name for tool in self.registry.for_categories({"apps"})], ["windows_control_info"])
        self.assertEqual([tool.name for tool in self.registry.for_selected_categories(set())], ["windows_control_info"])
        self.assertIn("windows_control_info()", self.registry.catalog_for_selected_categories({"apps"}))
        self.assertNotIn("file_probe", self.registry.catalog_for_selected_categories({"apps"}))

    def test_capability_report_is_compact_by_default_and_named_lookup_has_contract(self):
        tool = Tool(
            "report_probe",
            "read a report by its exact path",
            lambda args: "ok",
            (Param("path", "string", "absolute report path", True), Param("limit", "integer", "maximum rows")),
            categories=("files",),
        )
        self.registry.register(tool)

        summary = self.registry.access.info_text(recent=0)
        self.assertIn("read a report by its exact path", summary)
        self.assertIn("- report_probe [files] — read a report by its exact path", summary)
        self.assertNotIn("ورودی‌ها:", summary)
        self.assertIn("تعداد ابزارهای منطبق: 1", summary)

        details = self.registry.access.info_text(recent=0, name="report_probe")
        self.assertIn("path (string، اجباری): absolute report path", details)
        self.assertIn("limit (integer، اختیاری): maximum rows", details)
        self.assertIn("ورودی‌ها:", details)

    def test_capability_report_paginates_compact_inventory_without_hiding_tools(self):
        for name in ("alpha_probe", "beta_probe"):
            self.registry.register(Tool(name, name + " description", lambda args: "ok", (), categories=("files",)))

        first = self.registry.access.info_text(recent=0, category="files", offset=0, limit=1)
        second = self.registry.access.info_text(recent=0, category="files", offset=1, limit=1)

        self.assertIn("تعداد ابزارهای منطبق: 2", first)
        self.assertIn("ادامه دارد: True", first)
        self.assertIn("offset بعدی: 1", first)
        self.assertIn("alpha_probe", first)
        self.assertNotIn("ورودی‌ها:", first)
        self.assertIn("beta_probe", second)
        self.assertIn("ادامه دارد: False", second)


if __name__ == "__main__":
    unittest.main()
