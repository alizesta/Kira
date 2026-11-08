"""Minimal MCP client (JSON-RPC 2.0) over stdio or plain HTTP. Standard library only, no shell, provider independent.

Security rules kept here:
  * the child process gets ONLY the variables written in kira_mcp.json plus a short list of system variables; nothing from settings.json
    or from Kira's own environment (API keys) is passed on;
  * every request the SERVER sends to us (sampling, roots, elicitation ...) is refused, so a server can never reach a model or the disk through us;
  * a server's text is data: the caller treats it as untrusted.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

PROTOCOL = "2025-03-26"
MAX_LINE = 4_000_000
MAX_TOOLS = 200
SYSTEM_ENV = ("PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR", "USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA",
              "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "SYSTEMDRIVE", "LANG", "LC_ALL", "USERNAME")


class McpError(Exception):
    """A failure with a message that is safe to show."""


def child_env(extra: dict) -> dict:
    env = {k: os.environ[k] for k in SYSTEM_ENV if k in os.environ}
    env.update({str(k): str(v) for k, v in (extra or {}).items()})
    return env


class _Base:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.server_info: dict = {}
        self._id = 0
        self._id_lock = threading.Lock()

    def _next_id(self) -> int:
        with self._id_lock:
            self._id += 1
            return self._id

    def initialize(self, timeout: float) -> None:
        result = self.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": "kira", "version": "1"}}, timeout)
        self.server_info = result.get("serverInfo") if isinstance(result, dict) and isinstance(result.get("serverInfo"), dict) else {}
        self.notify("notifications/initialized", {})

    def list_tools(self, timeout: float) -> list:
        tools, cursor = [], None
        for _ in range(10):
            result = self.request("tools/list", {"cursor": cursor} if cursor else {}, timeout)
            if not isinstance(result, dict):
                break
            tools.extend(t for t in result.get("tools", []) if isinstance(t, dict) and isinstance(t.get("name"), str))
            cursor = result.get("nextCursor")
            if not cursor or len(tools) >= MAX_TOOLS:
                break
        return tools[:MAX_TOOLS]

    def call_tool(self, name: str, arguments: dict, timeout: float) -> dict:
        result = self.request("tools/call", {"name": name, "arguments": arguments or {}}, timeout)
        return result if isinstance(result, dict) else {}

    def request(self, method, params, timeout):                         # pragma: no cover - implemented by subclasses
        raise NotImplementedError

    def notify(self, method, params):                                    # pragma: no cover
        raise NotImplementedError

    def close(self):
        pass


class StdioClient(_Base):
    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.proc: subprocess.Popen | None = None
        self._pending: dict[int, dict] = {}
        self._plock = threading.Lock()
        self._wlock = threading.Lock()
        self._stderr = ""
        self.started_at = 0.0

    # ---- process ----
    def start(self) -> None:
        env = child_env(self.cfg.get("env"))
        exe = shutil.which(self.cfg["command"], path=env.get("PATH")) or self.cfg["command"]
        cwd = self.cfg.get("cwd") or None
        if cwd and not os.path.isdir(cwd):
            raise McpError("cwd does not exist")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        try:
            self.proc = subprocess.Popen([exe, *self.cfg.get("args", [])], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         env=env, cwd=cwd, shell=False, creationflags=flags)
        except (OSError, ValueError) as exc:
            raise McpError(f"cannot start '{self.cfg['command']}': {exc}") from exc
        self.started_at = time.monotonic()
        threading.Thread(target=self._read_loop, daemon=True, name=f"mcp-out-{self.cfg['name']}").start()
        threading.Thread(target=self._err_loop, daemon=True, name=f"mcp-err-{self.cfg['name']}").start()

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stderr_tail(self) -> str:
        return self._stderr[-600:]

    def _err_loop(self):
        try:
            for line in iter(self.proc.stderr.readline, b""):
                self._stderr = (self._stderr + line.decode("utf-8", "replace"))[-2000:]
        except (OSError, ValueError):
            pass

    def _read_loop(self):
        try:
            for line in iter(lambda: self.proc.stdout.readline(MAX_LINE), b""):
                try:
                    msg = json.loads(line.decode("utf-8", "replace"))
                except ValueError:
                    continue                                              # a server may log on stdout: not JSON = ignored
                if isinstance(msg, dict):
                    self._on_message(msg)
        except (OSError, ValueError):
            pass
        finally:
            with self._plock:                                             # the process ended: wake every waiter with a failure
                for slot in self._pending.values():
                    slot.setdefault("error", {"message": "server process ended"})
                    slot["event"].set()

    def _on_message(self, msg: dict):
        if "method" in msg:                                               # a request or notification FROM the server
            if "id" in msg:
                if msg["method"] == "ping":
                    self._send({"jsonrpc": "2.0", "id": msg["id"], "result": {}})
                else:
                    self._send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "not supported by this client"}})
            return
        with self._plock:
            slot = self._pending.get(msg.get("id"))
        if slot is not None:
            if "error" in msg:
                slot["error"] = msg["error"] if isinstance(msg["error"], dict) else {"message": str(msg["error"])}
            else:
                slot["result"] = msg.get("result")
            slot["event"].set()

    def _send(self, obj: dict):
        data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        with self._wlock:
            try:
                self.proc.stdin.write(data)
                self.proc.stdin.flush()
            except (OSError, ValueError, AttributeError) as exc:
                raise McpError("server process is not reachable") from exc

    # ---- rpc ----
    def request(self, method, params, timeout):
        rid = self._next_id()
        slot = {"event": threading.Event()}
        with self._plock:
            self._pending[rid] = slot
        try:
            self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            if not slot["event"].wait(timeout):
                try:
                    self._send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": rid, "reason": "timeout"}})
                except McpError:
                    pass
                raise McpError(f"no answer within {int(timeout)} s")
            if "error" in slot:
                raise McpError(str(slot["error"].get("message", "error"))[:300])
            return slot.get("result")
        finally:
            with self._plock:
                self._pending.pop(rid, None)

    def notify(self, method, params):
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def close(self):
        proc = self.proc
        if proc is None:
            return
        try:
            proc.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            try:
                proc.kill()
            except OSError:
                pass
        for pipe in (proc.stdout, proc.stderr):                          # release the handles (the reader threads end on EOF)
            try:
                pipe.close()
            except (OSError, ValueError, AttributeError):
                pass


class HttpClient(_Base):
    """MCP over HTTP POST (JSON or a single SSE answer). Header values are read from the environment variables the user named."""

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.session_id = ""

    def start(self) -> None:
        pass

    def alive(self) -> bool:
        return True

    def stderr_tail(self) -> str:
        return ""

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        for header, env_name in (self.cfg.get("headers_env") or {}).items():
            value = os.environ.get(env_name, "")
            if value:
                h[header] = value
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        return h

    def _post(self, payload: dict, timeout: float, want_id=None):
        req = urllib.request.Request(self.cfg["url"], data=json.dumps(payload).encode("utf-8"), headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self.session_id = sid
                if want_id is None:
                    return None
                ctype = (resp.headers.get("Content-Type") or "").lower()
                if "text/event-stream" in ctype:
                    for raw in resp:
                        line = raw.decode("utf-8", "replace").strip()
                        if line.startswith("data:"):
                            try:
                                msg = json.loads(line[5:].strip())
                            except ValueError:
                                continue
                            if isinstance(msg, dict) and msg.get("id") == want_id and "method" not in msg:
                                return msg
                    raise McpError("the server ended the stream without an answer")
                return json.loads(resp.read(MAX_LINE).decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            raise McpError(f"HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise McpError(f"connection failed: {exc}") from exc

    def request(self, method, params, timeout):
        rid = self._next_id()
        msg = self._post({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}, timeout, rid)
        if not isinstance(msg, dict):
            raise McpError("invalid answer")
        if "error" in msg:
            err = msg["error"]
            raise McpError(str(err.get("message", "error") if isinstance(err, dict) else err)[:300])
        return msg.get("result")

    def notify(self, method, params):
        try:
            self._post({"jsonrpc": "2.0", "method": method, "params": params}, 10)
        except McpError:
            pass


def make_client(cfg: dict):
    return HttpClient(cfg) if cfg.get("url") else StdioClient(cfg)
