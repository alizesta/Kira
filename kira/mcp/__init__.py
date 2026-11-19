"""External tool servers (MCP) and independent agents, plugged into the normal ToolRegistry. See docs/MCP_AGENTS_FA.md."""
from __future__ import annotations

import logging

from ..tools.registry import Tool, READ
from .agents import AgentHub, register_agent_tools
from .hub import McpHub

_LOGGER = logging.getLogger(__name__)
_OPTIONAL_TOOL_NAMES = frozenset({
    "agent_ask", "agent_status", "agent_answer", "agent_stop", "agent_health", "mcp_info",
})


def install(registry, data_dir, settings_fn):
    """Register the MCP + agent tools and start connecting in the background. Never raises; returns the McpHub (or None)."""
    existing_names = set(registry.names())
    existing_mcp_names = {
        tool.name for tool in registry.all() if getattr(tool, "mcp_server", "")
    }
    hub = None
    try:
        hub = McpHub(registry, data_dir, settings_fn)
        # mcp_mode=off disables the complete external integration, including
        # independent agents, while keeping local job history readable.
        agents = AgentHub(registry, data_dir, lambda: hub.config().get("agents", {}) if hub.enabled() else {})
        register_agent_tools(registry, agents)
        registry.register(Tool("mcp_info", "state of the configured external tool servers (MCP) and any error", lambda a: hub.info_text(), (), READ, ("mcp", "agents")))
        hub.agents = agents
        hub.refresh_async()
        return hub
    except Exception:                                                 # noqa: BLE001 - the chat works without this feature
        _LOGGER.exception("Could not initialize the optional MCP and agent integrations")
        try:
            if hub is not None:
                hub.shutdown()
        except Exception:
            _LOGGER.exception("Could not clean up a partially initialized MCP hub")
        try:
            registry.unregister_where(
                lambda tool: (
                    tool.name in _OPTIONAL_TOOL_NAMES and tool.name not in existing_names
                ) or (
                    bool(getattr(tool, "mcp_server", ""))
                    and tool.name not in existing_mcp_names
                )
            )
        except Exception:
            _LOGGER.exception("Could not roll back partially registered optional tools")
        return None
