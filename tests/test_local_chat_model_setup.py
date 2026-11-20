"""Offline checks for the exact pinned local model selected by the installer."""
import unittest

from scripts import setup_local_chat_model as setup


class LocalChatModelSetupTests(unittest.TestCase):
    def test_installer_is_pinned_to_the_abliterated_q4_k_m_artifact(self):
        self.assertIn("Qwen3.5-9B-abliterated-GGUF", setup.HF_URL)
        self.assertIn("Qwen3.5-9B-abliterated.Q4_K_M.gguf", setup.HF_URL)
        self.assertEqual(len(setup.MODEL_SHA256), 64)
        self.assertRegex(setup.MODEL_SHA256, r"^[0-9a-f]{64}$")
        self.assertTrue(setup.MODEL_FILE.endswith(setup.MODEL_SHA256[:12] + ".gguf"))
        self.assertIn("abliterated", setup.OLLAMA_MODEL)
        self.assertEqual(setup.OLLAMA_MIN_VERSION, (0, 17, 1))


if __name__ == "__main__":
    unittest.main()
