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
import queue
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
        if not isinstance(result, dict):
            raise McpError("initialize returned a malformed result")
        if result.get("protocolVersion") != PROTOCOL:
            raise McpError("server selected an unsupported MCP protocol version")
        if not isinstance(result.get("capabilities"), dict) or not isinstance(result.get("serverInfo"), dict):
            raise McpError("initialize returned malformed capabilities or serverInfo")
        self.server_info = result["serverInfo"]
        self.notify("notifications/initialized", {}, required=True)

    def list_tools(self, timeout: float) -> list:
        tools, cursor = [], None
        seen_cursors = set()
        for _ in range(10):
            result = self.request("tools/list", {"cursor": cursor} if cursor else {}, timeout)
            if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
                raise McpError("tools/list returned a malformed tools collection")
            page = result["tools"]
            if any(not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip() for item in page):
                raise McpError("tools/list returned a malformed tool definition")
            tools.extend(page)
            next_cursor = result.get("nextCursor")
            if next_cursor is not None and (not isinstance(next_cursor, str) or not next_cursor.strip()):
                raise McpError("tools/list returned an invalid pagination cursor")
            if not next_cursor or len(tools) >= MAX_TOOLS:
                break
            if next_cursor in seen_cursors:
                raise McpError("tools/list repeated a pagination cursor")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        else:
            if cursor:
                raise McpError("tools/list exceeded the pagination limit")
        return tools[:MAX_TOOLS]

    def call_tool(self, name: str, arguments: dict, timeout: float) -> dict:
        result = self.request("tools/call", {"name": name, "arguments": arguments or {}}, timeout)
        if not isinstance(result, dict):
            raise McpError("tools/call returned a malformed result")
        content = result.get("content", [])
        if not isinstance(content, list) or any(not isinstance(item, dict) for item in content):
            raise McpError("tools/call returned malformed content")
        return result

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
        if msg.get("jsonrpc") != "2.0":
            with self._plock:
                slot = self._pending.get(msg.get("id"))
            if slot is not None:
                slot["error"] = {"message": "invalid JSON-RPC version"}
                slot["event"].set()
            return
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
            has_error, has_result = "error" in msg, "result" in msg
            if has_error == has_result:
                slot["error"] = {"message": "malformed JSON-RPC response"}
            elif has_error:
                slot["error"] = msg["error"] if isinstance(msg["error"], dict) else {"message": str(msg["error"])}
            else:
                slot["result"] = msg["result"]
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
            try:
                proc.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
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
        req = urllib.request.Request(
            self.cfg["url"],
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        timeout = max(0.01, float(timeout))
        started = time.monotonic()
        stop = threading.Event()
        result_queue: queue.Queue = queue.Queue(maxsize=1)
        response_lock = threading.Lock()
        active = {"response": None}

        def perform_request():
            outcome = None
            try:
                with open_no_redirect(req, timeout=timeout) as resp:
                    with response_lock:
                        active["response"] = resp
                    if stop.is_set():
                        return
                    sid = resp.headers.get("Mcp-Session-Id")
                    if sid:
                        self.session_id = sid
                    if want_id is None:
                        outcome = (True, None)
                    else:
                        ctype = (resp.headers.get("Content-Type") or "").lower()
                        if "text/event-stream" in ctype:
                            consumed = 0
                            for raw in iter(lambda: resp.readline(MAX_LINE + 1), b""):
                                if stop.is_set():
                                    raise McpError("request exceeded its total deadline")
                                consumed += len(raw)
                                if consumed > MAX_LINE:
                                    raise McpError("event stream exceeded the response size limit")
                                line = raw.decode("utf-8", "replace").strip()
                                if not line.startswith("data:"):
                                    continue
                                try:
                                    msg = json.loads(line[5:].strip())
                                except ValueError:
                                    continue
                                if isinstance(msg, dict) and msg.get("id") == want_id and "method" not in msg:
                                    outcome = (True, msg)
                                    break
                            if outcome is None:
                                outcome = (False, McpError("the server ended the stream without an answer"))
                        else:
                            raw = resp.read(MAX_LINE + 1)
                            if len(raw) > MAX_LINE:
                                raise McpError("response exceeded the size limit")
                            outcome = (True, json.loads(raw.decode("utf-8", "replace")))
            except urllib.error.HTTPError as exc:
                outcome = (False, McpError(f"HTTP {exc.code}"))
            except urllib.error.URLError as exc:
                outcome = (False, McpError(f"connection failed: {exc}"))
            except McpError as exc:
                outcome = (False, exc)
            except (OSError, ValueError, TypeError) as exc:
                outcome = (False, McpError(f"connection or response failed: {type(exc).__name__}"))
            except Exception as exc:                              # noqa: BLE001 - malformed transports must not strand the caller
                outcome = (False, McpError(f"unexpected transport failure: {type(exc).__name__}"))
            finally:
                with response_lock:
                    active["response"] = None
                if outcome is not None:
                    try:
                        result_queue.put_nowait(outcome)
                    except queue.Full:
                        pass

        worker = threading.Thread(
            target=perform_request,
            daemon=True,
            name="kira-mcp-http-request",
        )
        worker.start()
        remaining = max(0.0, timeout - (time.monotonic() - started))
        try:
            ok, value = result_queue.get(timeout=remaining)
        except queue.Empty as exc:
            stop.set()
            with response_lock:
                resp = active["response"]
            if resp is not None:
                try:
                    resp.close()
                except Exception:
                    pass
            raise McpError(f"request exceeded its total deadline of {timeout:g} s") from exc
        if not ok:
            raise value
        return value

    def request(self, method, params, timeout):
        rid = self._next_id()
        msg = self._post({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}, timeout, rid)
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or msg.get("id") != rid:
            raise McpError("invalid JSON-RPC response envelope")
        if "error" in msg:
            err = msg["error"]
            raise McpError(str(err.get("message", "error") if isinstance(err, dict) else err)[:300])
        if "result" not in msg:
            raise McpError("JSON-RPC response has neither result nor error")
        return msg["result"]

    def notify(self, method, params, *, required=False):
        try:
            self._post({"jsonrpc": "2.0", "method": method, "params": params}, 10)
        except McpError:
            if required:
                raise


def make_client(cfg: dict):
    return HttpClient(cfg) if cfg.get("url") else StdioClient(cfg)
