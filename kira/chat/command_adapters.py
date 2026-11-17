"""Adapters that register the chat commands already present in Kira.

The registry itself stays generic. This factory wires existing feature owners
into it without reimplementing their parsing, confirmation, or execution rules.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from .commands import (
    CommandDefinition,
    CommandOutcome,
    CommandRegistry,
    NO_MATCH,
    PermissionChecker,
)


def create_default_command_registry(
    *,
    permission_checker: PermissionChecker | None,
    usage_parser: Callable[[str], int | None],
    usage_report: Callable[[int], str],
    body_parser: Callable[[str], list[str]],
    body_is_active: Callable[[], bool],
    body_handler: Callable[[list[str]], Any],
    web_parser: Callable[[str], tuple[str | None, bool]],
    image_parser: Callable[[str], tuple[str, bool]],
    task_control_parser: Callable[[str], tuple[str | None, str]],
    task_running_checker: Callable[[str], bool],
    tool_agent: Any,
    desktop_action_matcher: Callable[[str], str | None],
    desktop_action_handler: Callable[[str], Any],
) -> CommandRegistry:
    """Build the compatibility adapter set from injected existing command owners."""
    registry = CommandRegistry(permission_checker=permission_checker)
    empty_object = {"type": "object", "properties": {}, "additionalProperties": False}

    def parse_usage(text, context):
        if context.metadata.get("has_attachments"):
            return None
        days = usage_parser(text)
        return {"days": days} if days is not None else None

    def parse_web(text, _context):
        query, forced = web_parser(text)
        return {"query": query} if forced and query else None

    def parse_image(text, context):
        if not context.metadata.get("has_image"):
            return None
        query, forced = image_parser(text)
        return {"query": query} if forced else None

    def match_body(text, _context):
        if not body_is_active():
            return None
        names = body_parser(text)
        return {"names": names} if names else None

    def _tool_session(context):
        return str(context.metadata.get("character_id") or context.session_id)

    def match_tool_confirmation(_text, context):
        if context.metadata.get("has_attachments") or not tool_agent.enabled():
            return None
        return {} if tool_agent.has_pending(_tool_session(context)) else None

    def match_tool_running_control(text, context):
        if context.metadata.get("has_attachments"):
            return None
        if not task_running_checker(_tool_session(context)):
            return None
        kind, payload = task_control_parser(text)
        if kind not in ("status", "pause", "cancel", "add_step", "change"):
            return None
        return {"kind": kind, "payload": payload}

    def execute_tool_running_control(context, _arguments):
        result = tool_agent.control_running(
            context.request.raw_input, session_id=_tool_session(context),
        )
        return result if result is not None else NO_MATCH

    def match_tool_task(text, context):
        if context.metadata.get("has_attachments") or not tool_agent.enabled():
            return None
        if not tool_agent.planning_enabled() or tool_agent.tasks.active(_tool_session(context)) is None:
            return None
        kind, payload = task_control_parser(text)
        return {"kind": kind, "payload": payload} if kind else None

    def match_desktop_action(text, context):
        if context.metadata.get("has_attachments") or tool_agent.enabled():
            return None
        action = desktop_action_matcher(text)
        return {"action": action} if action else None

    def execute_body(_context, arguments):
        body_handler(list(arguments["names"] or []))
        return CommandOutcome(
            metadata={"continue_chat": True, "continue_dispatch": True}
        )

    def execute_tool_confirmation(context, _arguments):
        result = tool_agent.handle_confirmation_reply(
            context.request.raw_input, session_id=context.request.session_id,
        )
        return result if result is not None else NO_MATCH

    def execute_tool_task(context, arguments):
        result = tool_agent.handle_task_command(
            context.request.raw_input, session_id=_tool_session(context),
        )
        if result is not None:
            return result
        if arguments.get("kind") in ("resume", "change"):
            return CommandOutcome(
                metadata={"continue_chat": True, "continue_dispatch": True}
            )
        return NO_MATCH

    registry.register(CommandDefinition(
        command_id="chat.body_control",
        name="body_control",
        description="Apply an existing avatar pose or gesture requested in the user's message.",
        parameters={
            "type": "object",
            "properties": {"names": {"type": "array"}},
            "required": ["names"],
            "additionalProperties": False,
        },
        required_permissions=(),
        matcher=match_body,
        handler=execute_body,
    ))
    registry.register(CommandDefinition(
        command_id="chat.usage_report",
        name="usage",
        description="Show the local usage ledger for the requested number of days.",
        aliases=("مصرف",),
        parameters={
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 365}},
            "required": ["days"],
            "additionalProperties": False,
        },
        required_permissions=(),
        parser=parse_usage,
        handler=lambda _context, arguments: usage_report(arguments["days"]),
    ))
    registry.register(CommandDefinition(
        command_id="chat.web_search",
        name="web",
        description="Force the existing web-search flow for the supplied query.",
        aliases=("search", "سرچ"),
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 300}},
            "required": ["query"],
            "additionalProperties": False,
        },
        required_permissions=(),
        parser=parse_web,
        handler=lambda _context, arguments: CommandOutcome(
            metadata={
                "continue_chat": True,
                "rewrite_text": arguments["query"],
                "force_web_search": True,
            }
        ),
    ))
    registry.register(CommandDefinition(
        command_id="chat.image_search",
        name="img",
        description="Force the existing image-search flow for an attached image.",
        aliases=("عکس",),
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string", "maxLength": 300}},
            "required": ["query"],
            "additionalProperties": False,
        },
        required_permissions=(),
        parser=parse_image,
        handler=lambda _context, arguments: CommandOutcome(
            metadata={
                "continue_chat": True,
                "rewrite_text": arguments["query"],
                "force_image_search": True,
            }
        ),
    ))
    registry.register(CommandDefinition(
        command_id="chat.tool_confirmation",
        name="tool_confirmation",
        description="Delegate confirmation/cancellation of a pending sensitive operation to ToolAgent.",
        parameters=empty_object,
        required_permissions=(),
        matcher=match_tool_confirmation,
        handler=execute_tool_confirmation,
    ))
    registry.register(CommandDefinition(
        command_id="chat.tool_running_control",
        name="tool_running_control",
        description="Control a running task between steps without queueing another chat turn.",
        parameters={
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["status", "pause", "cancel", "add_step", "change"],
                },
                "payload": {"type": "string"},
            },
            "required": ["kind", "payload"],
            "additionalProperties": False,
        },
        required_permissions=(),
        matcher=match_tool_running_control,
        handler=execute_tool_running_control,
    ))
    registry.register(CommandDefinition(
        command_id="chat.tool_task_control",
        name="tool_task_control",
        description="Delegate existing task status, pause, cancel, resume and editing controls to ToolAgent.",
        parameters={
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["status", "pause", "cancel", "resume", "add_step", "change"],
                },
                "payload": {"type": "string"},
            },
            "required": ["kind", "payload"],
            "additionalProperties": False,
        },
        required_permissions=(),
        matcher=match_tool_task,
        handler=execute_tool_task,
    ))
    registry.register(CommandDefinition(
        command_id="chat.desktop_shortcut",
        name="desktop_shortcut",
        description="Open one of the existing fixed desktop shortcuts through the safe-action adapter.",
        parameters={
            "type": "object",
            "properties": {"action": {"type": "string", "minLength": 1}},
            "required": ["action"],
            "additionalProperties": False,
        },
        required_permissions=("desktop.launch",),
        matcher=match_desktop_action,
        handler=lambda context, _arguments: desktop_action_handler(context.request.raw_input),
    ))
    return registry
