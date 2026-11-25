"""ASR manager discovery, selection, error and lifecycle regression tests."""
import unittest
from kira.asr_manager import ASRError, ASRManager


class FakeAdapter:
    def __init__(self, engine_id="fixture", fail=None):
        self.engine_id = engine_id
        self.display_name = f"{engine_id} engine"
        self.default_model = "fixture-model"
        self.capabilities = frozenset({"offline", "test"})
        self.fail = fail
        self.fail_shutdown = False
        self.calls = []

    def catalog_entry(self):
        return {"id": self.engine_id, "name": self.display_name,
                "default_model": self.default_model, "models": [],
                "capabilities": sorted(self.capabilities)}
    def inspect(self, model_id):
        return {"engine_id": self.engine_id, "engine_name": self.display_name,
                "model_id": model_id, "runtime_installed": True,
                "model_ready": True, "ready": True,
                "capabilities": sorted(self.capabilities)}
    def validate(self, model_id):
        self.calls.append(("validate", model_id))
        if self.fail == "validation":
            raise RuntimeError("dependency missing")
    def initialize(self, model_id):
        self.calls.append(("initialize", model_id))
        if self.fail == "initialization":
            raise RuntimeError("model load failed")
    def transcribe(self, audio, sample_rate, model_id):
        self.calls.append(("inference", sample_rate, model_id))
        if self.fail == "inference":
            raise RuntimeError("decoder failed")
        return " transcript "
    def transcribe_file(self, path, model_id):
        self.calls.append(("file", path, model_id))
        return "file transcript"
    def install(self, model_id, cancel_event=None):
        self.calls.append(("install", model_id))
        return "/models/fixture"
    def shutdown(self):
        self.calls.append(("shutdown",))
        if self.fail == "shutdown" or self.fail_shutdown:
            raise RuntimeError("release failed")


class ASRManagerTests(unittest.TestCase):
    def test_full_lifecycle_discovery_validation_load_inference_shutdown(self):
        adapter = FakeAdapter()
        manager = ASRManager(adapters=[adapter])
        settings = {"local_voice_asr_backend": "fixture", "local_voice_asr_model": "fixture-model"}
        state = manager.initialize(settings)
        self.assertTrue(state["ready"])
        self.assertTrue(state["initialized"])
        self.assertEqual(manager.transcribe([], 16000, settings), "transcript")
        self.assertEqual(manager.transcribe_file("sample.wav", settings), "file transcript")
        manager.shutdown()
        self.assertEqual([call[0] for call in adapter.calls],
                         ["validate", "initialize", "inference", "file", "shutdown"])
        self.assertEqual(manager.state, "idle")

    def test_future_adapter_registers_without_listener_changes(self):
        manager = ASRManager(adapters=[FakeAdapter("first")])
        second = FakeAdapter("second")
        manager.register(second)
        settings = {"local_voice_asr_backend": "second"}
        self.assertEqual(manager.select(settings), ("second", "fixture-model"))
        self.assertTrue(manager.discover(settings)["ready"])

    def test_unsupported_saved_choice_has_specific_error_and_no_fallback(self):
        manager = ASRManager(adapters=[FakeAdapter()])
        settings = {"local_voice_asr_backend": "qwen3", "local_voice_asr_model": "Qwen/model"}
        with self.assertRaises(ASRError) as caught:
            manager.initialize(settings)
        self.assertEqual(caught.exception.code, "unsupported_engine")
        self.assertEqual(manager.active_engine_id, "")
        state = manager.discover(settings)
        self.assertFalse(state["ready"])
        self.assertEqual(state["error_code"], "unsupported_engine")

    def test_failed_inference_is_not_reported_ready_and_can_recover(self):
        adapter = FakeAdapter(fail="inference")
        manager = ASRManager(adapters=[adapter])
        settings = {"local_voice_asr_backend": "fixture"}
        with self.assertRaises(ASRError):
            manager.transcribe([], 16000, settings)
        failed = manager.discover(settings)
        self.assertFalse(failed["ready"])
        self.assertEqual(failed["state"], "failed")
        adapter.fail = None
        self.assertEqual(manager.transcribe([], 16000, settings), "transcript")
        recovered = manager.discover(settings)
        self.assertTrue(recovered["ready"])
        self.assertEqual(recovered["state"], "ready")

    def test_unsupported_switch_releases_previous_engine(self):
        adapter = FakeAdapter()
        manager = ASRManager(adapters=[adapter])
        manager.initialize({"local_voice_asr_backend": "fixture"})
        with self.assertRaises(ASRError):
            manager.initialize({"local_voice_asr_backend": "qwen3"})
        self.assertEqual([c[0] for c in adapter.calls][-1], "shutdown")
        self.assertEqual(manager.active_engine_id, "")

    def test_initialization_and_inference_failures_are_distinct(self):
        with self.subTest(stage="initialization"):
            adapter = FakeAdapter(fail="initialization")
            manager = ASRManager(adapters=[adapter])
            with self.assertRaises(ASRError) as caught:
                manager.initialize({"local_voice_asr_backend": "fixture"})
            self.assertEqual(caught.exception.code, "initialization_failed")
            self.assertEqual([call[0] for call in adapter.calls],
                             ["validate", "initialize", "shutdown"])
        with self.subTest(stage="inference"):
            manager = ASRManager(adapters=[FakeAdapter(fail="inference")])
            with self.assertRaises(ASRError) as caught:
                manager.transcribe([], 16000, {"local_voice_asr_backend": "fixture"})
            self.assertEqual(caught.exception.code, "inference_failed")

    def test_shutdown_failure_retains_adapter_and_blocks_engine_switch_until_retry(self):
        first, second = FakeAdapter("first"), FakeAdapter("second")
        manager = ASRManager(adapters=[first, second])
        first_settings = {"local_voice_asr_backend": "first"}
        second_settings = {"local_voice_asr_backend": "second"}
        manager.initialize(first_settings)

        first.fail_shutdown = True
        with self.assertRaises(ASRError) as caught:
            manager.shutdown()
        self.assertEqual(caught.exception.code, "shutdown_failed")
        self.assertEqual(manager.active_engine_id, "first")

        blocked = manager.discover(second_settings)
        self.assertFalse(blocked["ready"])
        self.assertEqual(blocked["state"], "failed")
        self.assertFalse(blocked["initialized"])
        self.assertEqual(blocked["error_code"], "shutdown_failed")

        first.fail_shutdown = False
        self.assertEqual(manager.transcribe([], 16000, second_settings), "transcript")
        self.assertEqual(manager.active_engine_id, "second")
        self.assertEqual([call[0] for call in first.calls].count("shutdown"), 2)

    def test_initialization_cleanup_failure_retains_adapter_for_retry(self):
        adapter = FakeAdapter(fail="initialization")
        adapter.fail_shutdown = True
        manager = ASRManager(adapters=[adapter])
        settings = {"local_voice_asr_backend": "fixture"}

        with self.assertRaises(ASRError) as caught:
            manager.initialize(settings)
        self.assertEqual(caught.exception.code, "initialization_cleanup_failed")
        self.assertEqual(manager.active_engine_id, "fixture")
        self.assertFalse(manager.discover(settings)["ready"])

        adapter.fail = None
        adapter.fail_shutdown = False
        manager.shutdown()
        self.assertEqual(manager.active_engine_id, "")
        self.assertEqual(manager.state, "idle")
        self.assertEqual([call[0] for call in adapter.calls].count("shutdown"), 2)

    def test_discovery_does_not_leak_another_selection_failure(self):
        first, second = FakeAdapter("first", fail="inference"), FakeAdapter("second")
        manager = ASRManager(adapters=[first, second])
        first_settings = {"local_voice_asr_backend": "first"}
        second_settings = {"local_voice_asr_backend": "second"}

        with self.assertRaises(ASRError):
            manager.transcribe([], 16000, first_settings)

        state = manager.discover(second_settings)
        self.assertTrue(state["ready"])
        self.assertEqual(state["state"], "available")
        self.assertEqual(state["last_error"], "")

    def test_discovery_does_not_leak_failure_to_another_model_on_same_engine(self):
        adapter = FakeAdapter(fail="inference")
        manager = ASRManager(adapters=[adapter])
        failed_settings = {
            "local_voice_asr_backend": "fixture",
            "local_voice_asr_model": "fixture-model",
        }
        other_model_settings = {
            "local_voice_asr_backend": "fixture",
            "local_voice_asr_model": "another-model",
        }

        with self.assertRaises(ASRError):
            manager.transcribe([], 16000, failed_settings)

        state = manager.discover(other_model_settings)
        self.assertTrue(state["ready"])
        self.assertEqual(state["state"], "available")
        self.assertEqual(state["last_error"], "")

    def test_shutdown_clears_error_after_failed_initialization(self):
        adapter = FakeAdapter(fail="initialization")
        manager = ASRManager(adapters=[adapter])
        settings = {"local_voice_asr_backend": "fixture"}

        with self.assertRaises(ASRError):
            manager.initialize(settings)
        self.assertEqual(manager.state, "failed")

        manager.shutdown()
        state = manager.discover(settings)
        self.assertEqual(manager.state, "idle")
        self.assertEqual(state["state"], "available")
        self.assertEqual(state["last_error"], "")

    def test_engine_switch_shuts_down_old_adapter_before_loading_new(self):
        first, second = FakeAdapter("first"), FakeAdapter("second")
        manager = ASRManager(adapters=[first, second])
        manager.initialize({"local_voice_asr_backend": "first"})
        manager.initialize({"local_voice_asr_backend": "second"})
        self.assertEqual([c[0] for c in first.calls], ["validate", "initialize", "shutdown"])
        self.assertEqual([c[0] for c in second.calls], ["validate", "initialize"])
        self.assertEqual(manager.active_engine_id, "second")


if __name__ == "__main__":
    unittest.main()
