import unittest

from kira.mcp.registry import server_config


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

    def test_unsupported_oci_package_is_not_launched(self):
        record = {"server": {"name": "container", "packages": [{"registryType": "oci", "identifier": "example/server:latest", "transport": {"type": "stdio"}}]}}
        with self.assertRaises(ValueError):
            server_config(record)


if __name__ == "__main__":
    unittest.main()
