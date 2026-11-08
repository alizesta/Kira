"""External tool servers (MCP) and independent agents, plugged into the normal ToolRegistry. See docs/MCP_AGENTS_FA.md."""
from __future__ import annotations

from ..tools.registry import Tool, READ
from .agents import AgentHub, register_agent_tools
from .hub import McpHub


def install(registry, data_dir, settings_fn):
    """Register the MCP + agent tools and start connecting in the background. Never raises; returns the McpHub (or None)."""
    try:
        hub = McpHub(registry, data_dir, settings_fn)
        agents = AgentHub(registry, data_dir, lambda: hub.config().get("agents", {}))
        register_agent_tools(registry, agents)
        registry.register(Tool("mcp_info", "state of the configured external tool servers (MCP) and any error", lambda a: hub.info_text(), (), READ, ("mcp", "agents")))
        hub.agents = agents
        hub.refresh_async()
        return hub
    except Exception:                                                 # noqa: BLE001 - the chat works without this feature
        return None
