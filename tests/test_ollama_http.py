"""Talks to a tiny *fake Ollama* HTTP server on localhost with real `requests` (no mocks), so the real
HTTP/JSON path is exercised. It is not a real Ollama: model quality, GPU use and VRAM can only be checked on the PC."""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from tests import helpers
from kira.ollama_client import OllamaClient
from kira.hybrid_ai import HybridRouter

STATE = {"loaded": False, "requests": [], "installed": ["qwen3.5:4b"]}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/api/version":
            return self._send(200, {"version": "0.40.0"})
        if self.path == "/api/tags":
            return self._send(200, {"models": [{"name": n} for n in STATE["installed"]]})
        if self.path == "/api/ps":
            models = [{"name": "qwen3.5:4b", "size": 3800000000, "size_vram": 3800000000, "expires_at": "in 2m"}] if STATE["loaded"] else []
            return self._send(200, {"models": models})
        self._send(404, {"error": "nope"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        STATE["requests"].append((self.path, body))
        if body.get("model") not in STATE["installed"]:
            return self._send(404, {"error": f"model '{body.get('model')}' not found"})
        if self.path == "/api/generate":
            STATE["loaded"] = body.get("keep_alive") != 0
            return self._send(200, {"done": True})
        if self.path == "/api/chat":
            STATE["loaded"] = True
            return self._send(200, {"message": {"role": "assistant", "content": "[happy]\nسلام از مدل محلی"}})
        self._send(404, {"error": "nope"})


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_full_cycle_status_chat_unload(self):
        STATE.update(loaded=False, requests=[])
        c = OllamaClient(self.url, "qwen3.5:4b", 4096, "2m")
        ok, text = c.describe()
        self.assertTrue(ok)
        self.assertIn("0.40.0", text)
        self.assertIn("نصب است", text)
        self.assertIn("آزاد", text)                                  # nothing loaded yet
        self.assertIn("سلام از مدل محلی", c.chat([{"role": "user", "content": "سلام"}], "persona"))
        path, body = STATE["requests"][-1]
        self.assertEqual((path, body["options"]["num_ctx"], body["keep_alive"]), ("/api/chat", 4096, "2m"))
        self.assertIn("100٪ روی GPU", c.describe()[1])
        c.unload()
        self.assertFalse(STATE["loaded"])
        self.assertIn("آزاد", c.describe()[1])
        c.preload()
        self.assertTrue(STATE["loaded"])

    def test_model_installed_as_latest_works_over_real_http(self):
        STATE.update(loaded=False, requests=[], installed=["qwen3.5:latest"])
        try:
            c = OllamaClient(self.url, "qwen3.5:4b", 4096, "2m")
            self.assertIn("سلام از مدل محلی", c.chat([{"role": "user", "content": "سلام"}], "persona"))
            self.assertEqual([r[1]["model"] for r in STATE["requests"]], ["qwen3.5:4b", "qwen3.5:latest"])
            self.assertIn("qwen3.5:latest", c.describe()[1])
            c.unload()
            self.assertEqual(STATE["requests"][-1][1]["model"], "qwen3.5:latest")
        finally:
            STATE["installed"] = ["qwen3.5:4b"]

    def test_router_falls_back_to_local_server(self):
        s = helpers.fresh_settings()
        s["ollama_url"] = self.url
        s["model"] = "qwen3.5:4b"
        self.assertIn("سلام از مدل محلی", HybridRouter(s).chat([{"role": "user", "content": "x"}], "p"))
        s["model"] = "does-not-exist:1b"
        with self.assertRaises(RuntimeError) as cm:
            HybridRouter(s).chat([{"role": "user", "content": "x"}], "p")
        self.assertIn("ollama pull does-not-exist:1b", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
