import unittest
from unittest.mock import patch

import server


class DedupeToolsTest(unittest.TestCase):
    def make_tool(self, **overrides):
        tool = {
            "id": "old-id",
            "name": "Portal :8017",
            "url": "http://localhost:8017",
            "port": "8017",
            "projectPath": "/tmp/example-project",
            "startCommand": "python -m uvicorn app:app --port 8017",
            "tags": ["detected"],
            "status": "configured",
            "managed": True,
            "source": "detected",
            "lastSeen": 100,
            "createdAt": 10,
            "updatedAt": 100,
        }
        tool.update(overrides)
        return tool

    def test_same_project_and_command_dedupes_across_ports(self):
        current = self.make_tool(
            id="new-id",
            name="Portal :8018",
            url="http://localhost:8018",
            port="8018",
            startCommand="python -m uvicorn app:app --port=8018",
            status="running",
            managed=False,
            lastSeen=200,
            createdAt=20,
            updatedAt=200,
        )

        result = server.dedupe_tools([self.make_tool(), current])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "old-id")
        self.assertEqual(result[0]["port"], "8018")
        self.assertEqual(result[0]["url"], "http://localhost:8018")
        self.assertEqual(result[0]["status"], "running")
        self.assertTrue(result[0]["managed"])
        self.assertEqual(result[0]["createdAt"], 10)

    def test_query_link_is_recognized_and_keeps_its_query(self):
        url = "http://127.0.0.1:5173/?status=active&sort=updated_desc"

        tool = server.normalize_tool({"url": url})

        self.assertEqual(tool["url"], url)
        self.assertEqual(tool["port"], "5173")

    def test_markdown_link_is_recognized_and_normalized(self):
        tool = server.normalize_tool(
            {"url": "[Active tasks](http://127.0.0.1:5173/?status=active\\&sort=updated_desc)"}
        )

        self.assertEqual(
            tool["url"], "http://127.0.0.1:5173/?status=active&sort=updated_desc"
        )
        self.assertEqual(tool["port"], "5173")

    def test_different_commands_in_one_project_remain_distinct(self):
        api = self.make_tool(id="api", startCommand="npm run api -- --port 8017")
        web = self.make_tool(id="web", port="8018", startCommand="npm run web -- --port 8018")

        self.assertEqual(len(server.dedupe_tools([api, web])), 2)

    def test_detected_root_process_dedupes_across_ports(self):
        first = self.make_tool(
            projectPath="/",
            name="Antigravity :5001",
            port="5001",
            url="http://localhost:5001",
            processName="language_",
            startCommand="/Applications/Antigravity.app/bin/language_server --port 5001",
        )
        second = self.make_tool(
            projectPath="/",
            name="Antigravity :5002",
            port="5002",
            url="http://localhost:5002",
            processName="language_",
            startCommand="/Applications/Antigravity.app/bin/language_server --port 5002",
            status="running",
            lastSeen=200,
        )

        result = server.dedupe_tools([first, second])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["port"], "5002")

    def test_different_root_services_remain_distinct(self):
        first = self.make_tool(
            projectPath="/",
            name="Antigravity :5001",
            port="5001",
            url="http://localhost:5001",
            processName="language_",
            startCommand="/Applications/Antigravity.app/bin/language_server --port 5001",
        )
        second = self.make_tool(
            projectPath="/",
            name="Other Service :5002",
            port="5002",
            url="http://localhost:5002",
            processName="language_",
            startCommand="/Applications/Other.app/bin/server --port 5002",
        )

        self.assertEqual(len(server.dedupe_tools([first, second])), 2)

    def test_manual_root_records_remain_port_specific(self):
        first = self.make_tool(projectPath="/", source="manual", port="5001")
        second = self.make_tool(projectPath="/", source="manual", port="5002")

        self.assertEqual(len(server.dedupe_tools([first, second])), 2)

    def test_packaged_desktop_service_ignores_dynamic_paths_and_config(self):
        first = self.make_tool(
            name="CodeBuddy Code Remote Control :56906",
            port="56906",
            url="http://localhost:56906",
            projectPath="/Users/example/.workbuddy",
            processName="Electron",
            startCommand=(
                "/Applications/WorkBuddy.app/Contents/MacOS/Electron "
                "codebuddy --serve --port 56906 --mcp-config first"
            ),
        )
        second = self.make_tool(
            name="CodeBuddy Code Remote Control :62746",
            port="62746",
            url="http://localhost:62746",
            projectPath="/private/tmp/workbuddy-host-cli/session-2",
            processName="Electron",
            startCommand=(
                "/Applications/WorkBuddy.app/Contents/MacOS/Electron "
                "codebuddy --serve --port 62746 --mcp-config second"
            ),
            status="running",
            lastSeen=300,
        )

        result = server.dedupe_tools([first, second])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["port"], "62746")

    @patch("server.save_workspace")
    @patch("server.refresh_status", side_effect=lambda tools, _port: tools)
    @patch("server.discover_tools")
    @patch("server.load_workspace")
    def test_discovery_replaces_historical_port_without_creating_task(
        self, load_workspace, discover_tools, _refresh_status, save_workspace
    ):
        historical = self.make_tool()
        current = self.make_tool(
            id="discovered-id",
            name="Portal :8018",
            url="http://localhost:8018",
            port="8018",
            startCommand="python -m uvicorn app:app --port 8018",
            status="running",
            managed=False,
            lastSeen=300,
            updatedAt=300,
            pid=123,
            processName="Python",
            source="detected",
        )
        load_workspace.return_value = {"tools": [historical]}
        discover_tools.return_value = [current]

        result = server.merge_discovered(4173)

        self.assertEqual(result["created"], 0)
        self.assertEqual(len(result["tools"]), 1)
        self.assertEqual(result["tools"][0]["id"], "old-id")
        self.assertEqual(result["tools"][0]["port"], "8018")
        self.assertEqual(result["tools"][0]["url"], "http://localhost:8018")
        save_workspace.assert_called_once()


if __name__ == "__main__":
    unittest.main()
