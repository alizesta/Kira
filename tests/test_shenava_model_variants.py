"""Regression tests for Shenava INT8 and FP32 model selection/downloads."""
import os
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock

from kira import local_voice


class ShenavaModelVariantTests(unittest.TestCase):
    def _snapshot(self, cache, repo_id, filename):
        repo_dir = repo_id.replace("/", "--")
        snapshot = cache / f"models--{repo_dir}" / "snapshots" / "test-revision"
        snapshot.mkdir(parents=True)
        (snapshot / filename).write_bytes(b"model")
        (snapshot / "tokens.txt").write_text("tokens", encoding="utf-8")
        return snapshot

    def test_int8_and_fp32_resolve_only_their_own_cached_model_files(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp)
            int8_snapshot = self._snapshot(
                cache, local_voice.SHENAVA_INT8_REPO_ID, "model.int8.onnx"
            )
            fp32_snapshot = self._snapshot(
                cache, local_voice.SHENAVA_FP32_REPO_ID, "model.onnx"
            )
            with mock.patch.dict(os.environ, {"HF_HUB_CACHE": str(cache)}):
                int8_model, int8_tokens = local_voice._resolve_shenava_model_files(
                    local_voice.SHENAVA_INT8_REPO_ID
                )
                fp32_model, fp32_tokens = local_voice._resolve_shenava_model_files(
                    local_voice.SHENAVA_FP32_REPO_ID
                )

            self.assertEqual(int8_model, int8_snapshot / "model.int8.onnx")
            self.assertEqual(fp32_model, fp32_snapshot / "model.onnx")
            self.assertEqual(int8_tokens, int8_snapshot / "tokens.txt")
            self.assertEqual(fp32_tokens, fp32_snapshot / "tokens.txt")

    def test_fp32_download_requests_onnx_model_and_tokens_only(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp)
            snapshot = self._snapshot(
                cache, local_voice.SHENAVA_FP32_REPO_ID, "model.onnx"
            )
            hub = ModuleType("huggingface_hub")
            hub.snapshot_download = mock.Mock(return_value=str(snapshot))

            with mock.patch.dict(os.environ, {"HF_HUB_CACHE": str(cache)}), \
                 mock.patch.dict("sys.modules", {"huggingface_hub": hub}), \
                 mock.patch.object(local_voice, "shenava_ready", return_value=True):
                result = local_voice.install_and_download_shenava_asr(
                    local_voice.SHENAVA_FP32_REPO_ID
                )

            self.assertEqual(Path(result), snapshot.absolute())
            kwargs = hub.snapshot_download.call_args.kwargs
            self.assertEqual(kwargs["repo_id"], local_voice.SHENAVA_FP32_REPO_ID)
            self.assertIn("model.onnx", kwargs["allow_patterns"])
            self.assertIn("tokens.txt", kwargs["allow_patterns"])
            self.assertTrue(kwargs["local_files_only"])

    def test_unsupported_model_repo_is_rejected_before_install_or_download(self):
        with mock.patch.object(local_voice, "shenava_ready") as ready:
            with self.assertRaises(ValueError):
                local_voice.install_and_download_shenava_asr("someone/other-model")
            ready.assert_not_called()


if __name__ == "__main__":
    unittest.main()
