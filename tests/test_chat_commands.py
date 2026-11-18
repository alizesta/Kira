"""Unit tests for the framework-independent Chat Commands registry."""
import threading
import time
import unittest

from kira.chat.commands import (
    CommandDefinition,
    CommandDispatch,
    CommandOutcome,
    CommandRegistry,
    CommandStatus,
    PermissionDecision,
)


class CommandRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = CommandRegistry()

    def tearDown(self):
        self.registry.close()

    def test_register_alias_parse_and_dispatch(self):
        calls = []
        self.registry.register(CommandDefinition(
            command_id="test.greet",
            name="greet",
            description="Return a greeting.",
            aliases=("hello",),
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string", "minLength": 1}},
                "required": ["name"],
                "additionalProperties": False,
            },
            required_permissions=(),
            parser=lambda raw, _ctx: {"name": raw.split(maxsplit=1)[1]},
            handler=lambda context, args: calls.append((context.request.session_id, args["name"])) or f"Hi {args['name']}",
        ))
        result = self.registry.dispatch_text(
            "/hello Kira", session_id="kira", request_id="req-1"
        )
        self.assertTrue(result.handled)
        self.assertEqual(result.reply_text, "Hi Kira")
        self.assertEqual(calls, [("kira", "Kira")])
        self.assertEqual(result.results[0].status, CommandStatus.COMPLETED)

    def test_parameter_validation_rejects_invalid_type_and_unknown_fields(self):
        self.registry.register(CommandDefinition(
            command_id="test.echo",
            name="echo",
            description="Echo one integer.",
            parameters={
                "type": "object",
                "properties": {"count": {"type": "integer", "minimum": 1}},
                "required": ["count"],
                "additionalProperties": False,
            },
            required_permissions=(),
            parser=lambda _raw, _ctx: {"count": True, "extra": "no"},
            handler=lambda _context, _args: "must not run",
        ))
        result = self.registry.dispatch_text(
            "/echo", session_id="kira", request_id="req-2"
        )
        self.assertEqual(result.results[0].status, CommandStatus.REJECTED)
        self.assertIn("invalid type", result.results[0].error)
        self.assertIn("unknown parameter", result.results[0].error)

    def test_permission_denial_prevents_handler_execution(self):
        called = []
        registry = CommandRegistry(
            permission_checker=lambda _command, _request: PermissionDecision(
                False, "explicit permission required"
            )
        )
        try:
            registry.register(CommandDefinition(
                command_id="test.sensitive",
                name="sensitive",
                description="A sensitive operation.",
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
                required_permissions=("system.write",),
                parser=lambda _raw, _ctx: {},
                handler=lambda _context, _args: called.append(True),
            ))
            result = registry.dispatch_text(
                "/sensitive", session_id="kira", request_id="req-3"
            )
            self.assertEqual(result.results[0].status, CommandStatus.REJECTED)
            self.assertEqual(result.reply_text, "explicit permission required")
            self.assertEqual(called, [])
        finally:
            registry.close()

    def test_missing_permission_policy_fails_closed(self):
        self.registry.register(CommandDefinition(
            command_id="test.protected",
            name="protected",
            description="A protected operation.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            required_permissions=("desktop.launch",),
            parser=lambda _raw, _ctx: {},
            handler=lambda _context, _args: "unsafe",
        ))
        result = self.registry.dispatch_text(
            "/protected", session_id="kira", request_id="req-4"
        )
        self.assertEqual(result.results[0].status, CommandStatus.REJECTED)
        self.assertEqual(result.reply_text, "Permission policy is unavailable.")

    def test_handler_exception_is_isolated_as_failed_result(self):
        def fail(_context, _arguments):
            raise RuntimeError("private file path must not escape")

        self.registry.register(CommandDefinition(
            command_id="test.failure",
            name="failure",
            description="A failing handler.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            required_permissions=(),
            parser=lambda _raw, _ctx: {},
            handler=fail,
        ))
        result = self.registry.dispatch_text(
            "/failure", session_id="kira", request_id="req-5"
        )
        self.assertEqual(result.results[0].status, CommandStatus.FAILED)
        self.assertNotIn("private file path", result.reply_text)

    def test_idempotency_prevents_repeated_execution_for_same_request(self):
        calls = []
        self.registry.register(CommandDefinition(
            command_id="test.once",
            name="once",
            description="Run once.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            required_permissions=(),
            parser=lambda _raw, _ctx: {},
            handler=lambda _context, _args: calls.append("run") or "done",
        ))
        first = self.registry.dispatch_text(
            "/once", session_id="kira", request_id="req-6"
        )
        second = self.registry.dispatch_text(
            "/once", session_id="kira", request_id="req-6"
        )
        self.assertEqual(first.results[0], second.results[0])
        self.assertEqual(calls, ["run"])

    def test_session_scoping_keeps_same_request_id_independent(self):
        calls = []
        self.registry.register(CommandDefinition(
            command_id="test.scope",
            name="scope",
            description="A session-scoped command.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            required_permissions=(),
            parser=lambda _raw, _ctx: {},
            handler=lambda context, _args: calls.append(context.request.session_id) or context.request.session_id,
        ))
        a = self.registry.dispatch_text("/scope", session_id="kira", request_id="same")
        b = self.registry.dispatch_text("/scope", session_id="ren", request_id="same")
        self.assertEqual(a.reply_text, "kira")
        self.assertEqual(b.reply_text, "ren")
        self.assertEqual(calls, ["kira", "ren"])

    def test_disable_and_unregister_command(self):
        calls = []
        self.registry.register(CommandDefinition(
            command_id="test.switch",
            name="switch",
            description="An enableable command.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            required_permissions=(),
            parser=lambda _raw, _ctx: {},
            handler=lambda _context, _args: calls.append(True) or "on",
        ))
        self.assertTrue(self.registry.set_enabled("switch", False))
        self.assertFalse(self.registry.dispatch_text(
            "/switch", session_id="kira", request_id="req-7"
        ).handled)
        self.assertEqual(calls, [])
        self.assertTrue(self.registry.set_enabled("test.switch", True))
        self.assertEqual(self.registry.dispatch_text(
            "/switch", session_id="kira", request_id="req-8"
        ).reply_text, "on")
        self.assertTrue(self.registry.unregister("test.switch"))
        self.assertIsNone(self.registry.get("switch"))

    def test_text_matcher_and_continue_dispatch_contract(self):
        calls = []
        self.registry.register(CommandDefinition(
            command_id="test.prefix",
            name="prefix",
            description="A non-terminal command.",
            parameters={
                "type": "object",
                "properties": {"raw": {"type": "string"}},
                "required": ["raw"],
                "additionalProperties": False,
            },
            required_permissions=(),
            matcher=lambda text, _ctx: {"raw": text} if text.startswith("move ") else None,
            handler=lambda _context, args: calls.append(args["raw"]) or CommandOutcome(
                metadata={"continue_chat": True, "continue_dispatch": True}
            ),
        ))
        self.registry.register(CommandDefinition(
            command_id="test.second",
            name="second",
            description="A second matcher.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            required_permissions=(),
            matcher=lambda text, _ctx: {} if text.startswith("move ") else None,
            handler=lambda _context, _args: "second handled",
        ))
        result = self.registry.dispatch_text(
            "move left", session_id="kira", request_id="req-9"
        )
        self.assertEqual(len(result.results), 2)
        self.assertFalse(result.continue_chat)
        self.assertEqual(calls, ["move left"])
        self.assertEqual(result.reply_text, "second handled")

    def test_unknown_slash_command_is_left_unclaimed(self):
        self.registry.register(CommandDefinition(
            command_id="test.known",
            name="known",
            description="Known command.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            required_permissions=(),
            parser=lambda _raw, _ctx: {},
            handler=lambda _context, _args: "handled",
        ))
        result = self.registry.dispatch_text(
            "/web query", session_id="kira", request_id="req-10"
        )
        self.assertFalse(result.handled)

    def test_cooperative_cancellation_of_running_command(self):
        started = threading.Event()
        finished = threading.Event()

        def handler(context, _arguments):
            started.set()
            while not context.cancelled:
                finished.wait(0.01)
            context.raise_if_cancelled()

        self.registry.register(CommandDefinition(
            command_id="test.long",
            name="long",
            description="A cancellable command.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            required_permissions=(),
            parser=lambda _raw, _ctx: {},
            handler=handler,
        ))
        result_holder = []
        worker = threading.Thread(target=lambda: result_holder.append(
            self.registry.dispatch_text("/long", session_id="kira", request_id="req-11")
        ))
        worker.start()
        self.assertTrue(started.wait(2))
        self.assertEqual(self.registry.cancel("kira", "req-11"), 1)
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result_holder[0].results[0].status, CommandStatus.CANCELLED)

    def test_concurrent_duplicate_dispatch_runs_handler_once(self):
        started = threading.Event()
        release = threading.Event()
        calls = []

        def handler(_context, _arguments):
            calls.append("run")
            started.set()
            release.wait(2)
            return "complete"

        self.registry.register(CommandDefinition(
            command_id="test.concurrent",
            name="concurrent",
            description="Idempotent concurrent execution.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            required_permissions=(),
            parser=lambda _raw, _ctx: {},
            handler=handler,
        ))
        first, second = [], []
        one = threading.Thread(target=lambda: first.append(
            self.registry.dispatch_text("/concurrent", session_id="kira", request_id="req-12")
        ))
        two = threading.Thread(target=lambda: second.append(
            self.registry.dispatch_text("/concurrent", session_id="kira", request_id="req-12")
        ))
        one.start()
        self.assertTrue(started.wait(2))
        two.start()
        release.set()
        one.join(2)
        two.join(2)
        self.assertFalse(one.is_alive())
        self.assertFalse(two.is_alive())
        self.assertEqual(calls, ["run"])
        self.assertEqual(first[0].results[0], second[0].results[0])


    def test_cancel_session_cancels_only_commands_owned_by_that_session(self):
        started = {"kira": threading.Event(), "ren": threading.Event()}
        cancelled = []

        def handler(context, _arguments):
            started[context.request.session_id].set()
            while not context.cancelled:
                time.sleep(0.005)
            context.raise_if_cancelled()

        self.registry.register(CommandDefinition(
            command_id="test.session_cancel",
            name="session_cancel",
            description="Session-scoped cancellation.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            required_permissions=(),
            parser=lambda _raw, _ctx: {},
            handler=handler,
        ))

        def dispatch(owner, request_id):
            result = self.registry.dispatch_text(
                "/session_cancel", session_id=owner, request_id=request_id,
            )
            cancelled.append((owner, result.results[0].status))

        workers = [
            threading.Thread(target=dispatch, args=("kira", "kira-1")),
            threading.Thread(target=dispatch, args=("kira", "kira-2")),
            threading.Thread(target=dispatch, args=("ren", "ren-1")),
        ]
        for worker in workers:
            worker.start()
        self.assertTrue(started["kira"].wait(2))
        self.assertTrue(started["ren"].wait(2))
        self.assertEqual(self.registry.cancel_session("kira"), 2)
        workers[0].join(2)
        workers[1].join(2)
        self.assertFalse(workers[0].is_alive())
        self.assertFalse(workers[1].is_alive())
        self.assertTrue(workers[2].is_alive())
        self.assertEqual(self.registry.cancel("ren", "ren-1"), 1)
        workers[2].join(2)
        self.assertFalse(workers[2].is_alive())
        self.assertEqual(sorted(cancelled), [
            ("kira", CommandStatus.CANCELLED),
            ("kira", CommandStatus.CANCELLED),
            ("ren", CommandStatus.CANCELLED),
        ])

    def test_close_cancels_inflight_handler_and_rejects_future_dispatch(self):
        started = threading.Event()
        release = threading.Event()
        result_holder = []

        def handler(_context, _arguments):
            started.set()
            release.wait(2)
            return "late result"

        self.registry.register(CommandDefinition(
            command_id="test.close",
            name="close",
            description="Close during execution.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            required_permissions=(),
            parser=lambda _raw, _ctx: {},
            handler=handler,
        ))
        worker = threading.Thread(target=lambda: result_holder.append(
            self.registry.dispatch_text("/close", session_id="kira", request_id="close-1")
        ))
        worker.start()
        self.assertTrue(started.wait(2))
        self.registry.close()
        release.set()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(
            result_holder[0].results[0].status, CommandStatus.CANCELLED
        )
        self.assertEqual(self.registry._cache, {})
        with self.assertRaises(RuntimeError):
            self.registry.dispatch_text(
                "/close", session_id="kira", request_id="close-2"
            )


if __name__ == "__main__":
    unittest.main()
