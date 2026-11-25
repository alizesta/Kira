"""Regression tests for runtime state and detected capability ownership."""

import unittest

from kira.app.detected_capabilities import DetectedCapabilities
from kira.app.runtime_state import RuntimeState
from kira.ui.window_presentation_context import WindowPresentationContext
from kira import api_manager


class _ControllerRegistry:
    def name_for(self, _controller):
        return "runtime"

    def require(self, _feature):
        raise AssertionError("peer lookup is not part of this test")

    def get_if_materialized(self, _feature):
        return None


class RuntimeStateTests(unittest.TestCase):
    def test_runtime_state_is_strict_and_process_local(self):
        self.assertFalse(hasattr(api_manager, "_DEFAULT_CAPABILITIES"))
        with self.assertRaises(TypeError):
            api_manager.registry()
        state = RuntimeState({"worker", "closing"})
        worker = object()
        state.set("worker", worker)
        state.set("closing", False)

        self.assertIs(state.get("worker"), worker)
        self.assertFalse(state.get("closing"))
        self.assertIn("worker", state.snapshot())
        with self.assertRaises(KeyError):
            state.set("api_registry", {})

        state.clear("worker")
        self.assertFalse(state.contains("worker"))
        self.assertTrue(state.contains("closing"))

    def test_presentation_context_routes_state_through_runtime_store(self):
        context = WindowPresentationContext(object(), _ControllerRegistry())
        controller_context = context.for_controller(object())

        context.state._closing = False
        self.assertIn("_closing", context.state)
        self.assertFalse(context.runtime_state.get("_closing"))
        self.assertFalse(controller_context.state._closing)

        controller_context.state._closing = True
        self.assertTrue(context.state._closing)
        self.assertTrue(context.runtime_state.get("_closing"))

    def test_detected_capabilities_are_separate_and_snapshot_is_detached(self):
        first, second = DetectedCapabilities(), DetectedCapabilities()
        first.set("api_registry", {"groq": {"status": "valid"}})
        first.set("ollama_models", ("model-a",))

        snapshot = first.snapshot()
        snapshot["api_registry"]["groq"]["status"] = "tampered"
        self.assertEqual(first.get("api_registry")["groq"]["status"], "valid")
        self.assertEqual(second.snapshot(), {})
        with self.assertRaises(KeyError):
            first.set("runtime_state", {})


if __name__ == "__main__":
    unittest.main()
