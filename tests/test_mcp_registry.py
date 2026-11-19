import json
import tempfile
import unittest
from pathlib import Path

from kira.mcp.registry import server_config
from kira.mcp.config import load


class McpRegistryConfigTests(unittest.TestCase):
    def test_npm_package_becomes_safe_npx_server(self):
        record = {
            "server": {
                "name": "io.github.example/filesystem",
                "description": "Local file access",
                "packages": [{
                    "registryType": "npm",
                    "identifier": "@modelcontextprotocol/server-filesystem",
                    "version": "1.2.3",
                    "transport": {"type": "stdio"},
                    "environmentVariables": [{"name": "ROOT_DIR", "default": "C:/Data"}],
                }],
            }
        }
        name, cfg = server_config(record)
        self.assertEqual(name, "io-github-example-filesystem")
        self.assertEqual(cfg["command"], "npx")
        self.assertEqual(cfg["args"], ["-y", "@modelcontextprotocol/server-filesystem@1.2.3"])
        self.assertEqual(cfg["env"]["ROOT_DIR"], "C:/Data")
        self.assertEqual(cfg["default_level"], "sensitive")

    def test_named_package_arguments_keep_the_flag(self):
        record = {"server": {"name": "server-with-args", "packages": [{
            "registryType": "npm", "identifier": "example-mcp-server",
            "packageArguments": [{"type": "named", "name": "--root", "value": "C:/Data"}],
            "transport": {"type": "stdio"},
        }]}}
        _, cfg = server_config(record)
        self.assertEqual(cfg["args"], ["-y", "example-mcp-server", "--root", "C:/Data"])

    def test_https_remote_is_supported(self):
        name, cfg = server_config({"server": {"name": "remote-search", "remotes": [{"url": "https://mcp.example.com/mcp"}]}})
        self.assertEqual(name, "remote-search")
        self.assertEqual(cfg["url"], "https://mcp.example.com/mcp")

    def test_unsafe_package_identifier_is_rejected(self):
        record = {"server": {"name": "bad", "packages": [{"registryType": "npm", "identifier": "pkg;del-data", "transport": {"type": "stdio"}}]}}
        with self.assertRaises(ValueError):
            server_config(record)

    def test_config_rejects_server_and_agent_name_normalization_collisions(self):
        data = {
            "servers": {
                "Notes Server": {"command": "notes-server"},
                "notes-server": {"command": "other-server"},
            },
            "agents": {
                "Helper Agent": {"url": "https://helper.example"},
                "helper-agent": {"url": "https://other.example"},
            },
        }
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, "kira_mcp.json").write_text(json.dumps(data), encoding="utf-8")
            result = load(temp)

        self.assertEqual(list(result["servers"]), ["notes-server"])
        self.assertEqual(result["servers"]["notes-server"]["command"], "notes-server")
        self.assertEqual(list(result["agents"]), ["helper-agent"])
        self.assertEqual(result["agents"]["helper-agent"]["url"], "https://helper.example")
        self.assertIn("duplicate server name", result["error"])
        self.assertIn("duplicate agent name", result["error"])

    def test_unsupported_oci_package_is_not_launched(self):
        record = {"server": {"name": "container", "packages": [{"registryType": "oci", "identifier": "example/server:latest", "transport": {"type": "stdio"}}]}}
        with self.assertRaises(ValueError):
            server_config(record)


if __name__ == "__main__":
    unittest.main()
