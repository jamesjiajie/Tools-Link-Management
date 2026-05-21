#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "logs"
WORKSPACE_FILE = DATA_DIR / "workspace.json"
HOST = "127.0.0.1"
DEFAULT_PORT = 4173


def now_ms() -> int:
    return int(time.time() * 1000)


def ensure_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)
    if not WORKSPACE_FILE.exists():
        save_workspace({"tools": []})


def load_workspace() -> dict[str, Any]:
    ensure_dirs()
    try:
        with WORKSPACE_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        data = {"tools": []}

    if not isinstance(data, dict):
        data = {"tools": []}
    if not isinstance(data.get("tools"), list):
        data["tools"] = []
    return data


def save_workspace(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    temp_file = WORKSPACE_FILE.with_suffix(".tmp")
    with temp_file.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    temp_file.replace(WORKSPACE_FILE)


def normalize_tool(payload: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    base = existing or {}
    port = str(payload.get("port") or base.get("port") or "").strip()
    url = str(payload.get("url") or base.get("url") or "").strip()
    if port and not url:
        url = f"http://localhost:{port}"

    return {
        "id": str(payload.get("id") or base.get("id") or uuid.uuid4()),
        "name": str(payload.get("name") or base.get("name") or url or "Untitled Portal").strip(),
        "url": url,
        "port": port,
        "projectPath": str(payload.get("projectPath") or base.get("projectPath") or "").strip(),
        "startCommand": str(payload.get("startCommand") or base.get("startCommand") or "").strip(),
        "tags": payload.get("tags") if isinstance(payload.get("tags"), list) else base.get("tags", []),
        "notes": str(payload.get("notes") or base.get("notes") or "").strip(),
        "status": str(payload.get("status") or base.get("status") or "unknown"),
        "pid": payload.get("pid") or base.get("pid"),
        "managed": bool(payload.get("managed") or base.get("managed") or False),
        "processName": str(payload.get("processName") or base.get("processName") or "").strip(),
        "source": str(payload.get("source") or base.get("source") or "manual"),
        "lastSeen": payload.get("lastSeen") or base.get("lastSeen"),
        "createdAt": payload.get("createdAt") or base.get("createdAt") or now_ms(),
        "updatedAt": now_ms(),
    }


def parse_port_from_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        return str(parsed.port or "")
    except ValueError:
        return ""


def shell_quote(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:-]+", value):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


def read_request_json(handler: SimpleHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        return {}
    raw = handler.rfile.read(length).decode("utf-8")
    return json.loads(raw or "{}")


def list_listening_processes() -> list[dict[str, Any]]:
    try:
        completed = subprocess.run(
            ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.CalledProcessError):
        return []

    rows: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines()[1:]:
        parts = line.split(None, 8)
        if len(parts) < 9:
            continue
        command, pid, user, _, _, _, _, _, name = parts
        match = re.search(r":(\d+)\s+\(LISTEN\)", name)
        if not match:
            continue
        rows.append(
            {
                "processName": command,
                "pid": int(pid),
                "user": user,
                "port": match.group(1),
                "listenName": name,
            }
        )
    return rows


def process_command(pid: int) -> str:
    try:
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return completed.stdout.strip()


def process_cwd(pid: int) -> str:
    try:
        completed = subprocess.run(
            ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.CalledProcessError):
        return ""

    for line in completed.stdout.splitlines():
        if line.startswith("n"):
            return line[1:]
    return ""


def find_project_root(cwd: str) -> Path | None:
    if not cwd:
        return None

    path = Path(cwd).expanduser().resolve()
    candidates = [path, *path.parents]
    for candidate in candidates[:6]:
        if (candidate / "package.json").exists() or (candidate / "pyproject.toml").exists():
            return candidate
    return path if path.exists() else None


def package_manager_command(project_root: Path) -> str:
    package_file = project_root / "package.json"
    if not package_file.exists():
        return ""

    try:
        package = json.loads(package_file.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""

    scripts = package.get("scripts") if isinstance(package, dict) else {}
    if not isinstance(scripts, dict):
        return ""

    script_name = ""
    for candidate in ("dev", "start", "serve"):
        if candidate in scripts:
            script_name = candidate
            break
    if not script_name:
        return ""

    if (project_root / "pnpm-lock.yaml").exists():
        return f"pnpm {script_name}" if script_name == "dev" else f"pnpm run {script_name}"
    if (project_root / "yarn.lock").exists():
        return f"yarn {script_name}"
    if (project_root / "bun.lockb").exists() or (project_root / "bun.lock").exists():
        return f"bun run {script_name}"
    return "npm start" if script_name == "start" else f"npm run {script_name}"


def infer_launch_config(pid: int) -> dict[str, str]:
    command = process_command(pid)
    cwd = process_cwd(pid)
    project_root = find_project_root(cwd)
    project_path = str(project_root) if project_root else cwd
    start_command = package_manager_command(project_root) if project_root else ""
    if not start_command:
        start_command = command
    return {
        "projectPath": project_path,
        "startCommand": start_command,
    }


def fill_missing_launch_config(tool: dict[str, Any], pid: int) -> None:
    if tool.get("projectPath") and tool.get("startCommand"):
        return

    launch_config = infer_launch_config(pid)
    if not tool.get("projectPath") and launch_config.get("projectPath"):
        tool["projectPath"] = launch_config["projectPath"]
    if not tool.get("startCommand") and launch_config.get("startCommand"):
        tool["startCommand"] = launch_config["startCommand"]


def probe_http(port: str) -> dict[str, Any] | None:
    request = (
        f"GET / HTTP/1.1\r\nHost: localhost:{port}\r\n"
        "User-Agent: PortalHub/1.0\r\nConnection: close\r\n\r\n"
    ).encode("utf-8")

    try:
        with socket.create_connection((HOST, int(port)), timeout=0.35) as sock:
            sock.settimeout(0.8)
            sock.sendall(request)
            chunks = []
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
                if sum(len(item) for item in chunks) > 65536:
                    break
    except (OSError, ValueError):
        return None

    text = b"".join(chunks).decode("utf-8", "ignore")
    if not text.startswith("HTTP/"):
        return None

    title_match = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""
    status_match = re.match(r"HTTP/\S+\s+(\d+)", text)
    return {
        "title": title,
        "httpStatus": status_match.group(1) if status_match else "",
        "url": f"http://localhost:{port}",
    }


def discover_tools(server_port: int) -> list[dict[str, Any]]:
    discovered = []
    seen_ports = set()
    for process in list_listening_processes():
        if process["port"] == str(server_port):
            continue
        if process["port"] in seen_ports:
            continue
        probe = probe_http(process["port"])
        if not probe:
            continue
        status = int(probe["httpStatus"] or 0)
        if status < 200 or status >= 400:
            continue
        if not probe["title"] and "\ufffd" in process["processName"]:
            continue
        seen_ports.add(process["port"])
        name = f"{probe['title']} :{process['port']}" if probe["title"] else f"{process['processName']}:{process['port']}"
        launch_config = infer_launch_config(process["pid"])
        discovered.append(
            {
                "id": str(uuid.uuid4()),
                "name": name,
                "url": probe["url"],
                "port": process["port"],
                "projectPath": launch_config["projectPath"],
                "startCommand": launch_config["startCommand"],
                "tags": ["detected"],
                "notes": f"HTTP {probe['httpStatus']}".strip(),
                "status": "running",
                "pid": process["pid"],
                "managed": False,
                "processName": process["processName"],
                "source": "detected",
                "lastSeen": now_ms(),
                "createdAt": now_ms(),
                "updatedAt": now_ms(),
            }
        )
    return discovered


def dedupe_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen = set()
    for tool in tools:
        port = str(tool.get("port") or parse_port_from_url(str(tool.get("url") or "")))
        key = port or str(tool.get("url") or tool.get("id"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(tool)
    return deduped


def refresh_status(tools: list[dict[str, Any]], server_port: int) -> list[dict[str, Any]]:
    processes_by_port = {item["port"]: item for item in list_listening_processes()}
    for tool in tools:
        port = str(tool.get("port") or parse_port_from_url(str(tool.get("url") or "")))
        if not port:
            tool["status"] = "configured" if tool.get("startCommand") else "unknown"
            continue

        process = processes_by_port.get(port)
        if process and port != str(server_port):
            tool["status"] = "running"
            tool["pid"] = process["pid"]
            tool["processName"] = process["processName"]
            tool["lastSeen"] = now_ms()
            fill_missing_launch_config(tool, process["pid"])
        else:
            tool["pid"] = None
            if tool.get("startCommand"):
                tool["status"] = "configured"
            elif tool.get("source") == "detected" or tool.get("url") or port:
                tool["status"] = "stopped"
            else:
                tool["status"] = "unknown"
    return tools


def merge_discovered(server_port: int) -> dict[str, Any]:
    workspace = load_workspace()
    tools = dedupe_tools(workspace["tools"])
    existing_by_port = {str(tool.get("port") or parse_port_from_url(str(tool.get("url") or ""))): tool for tool in tools}
    existing_by_url = {str(tool.get("url") or ""): tool for tool in tools}

    created = 0
    for found in discover_tools(server_port):
        target = existing_by_port.get(found["port"]) or existing_by_url.get(found["url"])
        if target:
            target.update(
                {
                    "name": target.get("name") or found["name"],
                    "url": target.get("url") or found["url"],
                    "port": target.get("port") or found["port"],
                    "status": "running",
                    "pid": found["pid"],
                    "managed": target.get("managed") or False,
                    "projectPath": target.get("projectPath") or found["projectPath"],
                    "startCommand": target.get("startCommand") or found["startCommand"],
                    "processName": found["processName"],
                    "source": target.get("source") or "detected",
                    "lastSeen": found["lastSeen"],
                    "updatedAt": now_ms(),
                }
            )
        else:
            tools.append(found)
            created += 1

    workspace["tools"] = dedupe_tools(refresh_status(tools, server_port))
    save_workspace(workspace)
    return {"tools": workspace["tools"], "created": created}


def find_tool(tool_id: str, tools: list[dict[str, Any]]) -> tuple[int, dict[str, Any]] | tuple[None, None]:
    for index, tool in enumerate(tools):
        if str(tool.get("id")) == tool_id:
            return index, tool
    return None, None


def start_tool(tool: dict[str, Any]) -> dict[str, Any]:
    command = str(tool.get("startCommand") or "").strip()
    if not command:
        raise ValueError("这个工具还没有配置启动命令")

    cwd = str(tool.get("projectPath") or "").strip() or str(ROOT)
    if not Path(cwd).expanduser().exists():
        raise ValueError("项目路径不存在")

    log_path = LOG_DIR / f"{tool['id']}.log"
    log_file = log_path.open("a", encoding="utf-8")
    log_file.write(f"\n\n--- start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    log_file.flush()

    kwargs: dict[str, Any] = {
        "cwd": str(Path(cwd).expanduser()),
        "shell": True,
        "stdout": log_file,
        "stderr": subprocess.STDOUT,
    }
    if os.name == "posix":
        kwargs["preexec_fn"] = os.setsid

    process = subprocess.Popen(command, **kwargs)
    tool["pid"] = process.pid
    tool["managed"] = True
    tool["status"] = "starting"
    tool["updatedAt"] = now_ms()
    return tool


def stop_pid(pid: int, use_process_group: bool = False) -> None:
    if pid == os.getpid():
        raise ValueError("不能停止 Portal Hub 自己")
    if os.name == "posix" and use_process_group:
        try:
            os.killpg(pid, signal.SIGTERM)
            return
        except ProcessLookupError:
            return
        except OSError:
            pass

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return


def is_port_running(port: str, server_port: int) -> bool:
    if not port or port == str(server_port):
        return False
    return any(item["port"] == port for item in list_listening_processes())


def stop_tool(tool: dict[str, Any], server_port: int) -> dict[str, Any]:
    pid = tool.get("pid")
    if not pid:
        port = str(tool.get("port") or parse_port_from_url(str(tool.get("url") or "")))
        process = next((item for item in list_listening_processes() if item["port"] == port), None)
        pid = process["pid"] if process else None

    if not pid:
        tool["status"] = "stopped"
        tool["updatedAt"] = now_ms()
        return tool

    port = str(tool.get("port") or parse_port_from_url(str(tool.get("url") or "")))
    if port == str(server_port):
        raise ValueError("不能停止 Portal Hub 自己")

    stop_pid(int(pid), bool(tool.get("managed")))
    time.sleep(0.6)
    if is_port_running(port, server_port):
        tool["status"] = "running"
        tool["pid"] = pid
        raise ValueError("停止信号已发送，但端口仍在监听。可能该进程忽略 SIGTERM，或被其他管理器自动拉起。")
    else:
        tool["status"] = "stopped"
        tool["pid"] = None
    tool["updatedAt"] = now_ms()
    return tool


def is_link_management_tool(tool: dict[str, Any], server_port: int) -> bool:
    port = str(tool.get("port") or parse_port_from_url(str(tool.get("url") or "")))
    if port == str(server_port):
        return True

    project_path = str(tool.get("projectPath") or "").strip()
    if project_path:
        try:
            if Path(project_path).expanduser().resolve() == ROOT:
                return True
        except OSError:
            pass

    text = " ".join(
        str(value or "")
        for value in (
            tool.get("name"),
            tool.get("url"),
            tool.get("projectPath"),
            tool.get("startCommand"),
        )
    ).lower()
    return "link-management" in text or "portal hub" in text


def stop_other_tools(server_port: int) -> dict[str, Any]:
    workspace = load_workspace()
    tools = dedupe_tools(refresh_status(workspace["tools"], server_port))
    stopped: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for index, tool in enumerate(tools):
        if is_link_management_tool(tool, server_port):
            skipped.append({"id": str(tool.get("id")), "name": str(tool.get("name") or "Link Management")})
            continue
        if tool.get("status") not in {"running", "starting"}:
            continue

        try:
            tools[index] = stop_tool(tool, server_port)
            stopped.append({"id": str(tool.get("id")), "name": str(tool.get("name") or tool.get("url") or "Untitled Portal")})
        except ValueError as error:
            errors.append({"id": str(tool.get("id")), "name": str(tool.get("name") or "Untitled Portal"), "error": str(error)})

    workspace["tools"] = dedupe_tools(refresh_status(tools, server_port))
    save_workspace(workspace)
    return {
        "tools": workspace["tools"],
        "stopped": stopped,
        "skipped": skipped,
        "errors": errors,
    }


class PortalHandler(SimpleHTTPRequestHandler):
    server_version = "PortalHub/1.0"

    def translate_path(self, path: str) -> str:
        clean = unquote(urlparse(path).path).lstrip("/")
        if not clean:
            clean = "index.html"
        return str((ROOT / clean).resolve())

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, payload: Any, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_error_json(self, message: str, status: int = 400) -> None:
        self.send_json({"error": message}, status)

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        if route == "/api/tools":
            workspace = load_workspace()
            workspace["tools"] = dedupe_tools(refresh_status(workspace["tools"], self.server.server_port))
            save_workspace(workspace)
            self.send_json({"tools": workspace["tools"]})
            return
        if route.startswith("/api/logs/"):
            tool_id = route.rsplit("/", 1)[-1]
            log_path = LOG_DIR / f"{tool_id}.log"
            content = log_path.read_text("utf-8")[-8000:] if log_path.exists() else ""
            self.send_json({"log": content})
            return
        super().do_GET()

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        try:
            if route == "/api/discover":
                self.send_json(merge_discovered(self.server.server_port))
                return
            if route == "/api/tools":
                payload = read_request_json(self)
                workspace = load_workspace()
                tool = normalize_tool(payload)
                workspace["tools"].append(tool)
                save_workspace(workspace)
                self.send_json({"tool": tool}, 201)
                return
            if route == "/api/tools/stop-others":
                self.send_json(stop_other_tools(self.server.server_port))
                return

            match = re.fullmatch(r"/api/tools/([^/]+)/(start|stop|restart)", route)
            if match:
                tool_id, action = match.groups()
                workspace = load_workspace()
                index, tool = find_tool(tool_id, workspace["tools"])
                if tool is None:
                    self.send_error_json("工具不存在", 404)
                    return
                if action in {"stop", "restart"}:
                    tool = stop_tool(tool, self.server.server_port)
                    time.sleep(0.4)
                if action in {"start", "restart"}:
                    tool = start_tool(tool)
                workspace["tools"][index] = tool
                save_workspace(workspace)
                self.send_json({"tool": tool})
                return
        except json.JSONDecodeError:
            self.send_error_json("请求 JSON 无效")
            return
        except ValueError as error:
            self.send_error_json(str(error))
            return

        self.send_error_json("未知接口", 404)

    def do_PUT(self) -> None:
        route = urlparse(self.path).path
        match = re.fullmatch(r"/api/tools/([^/]+)", route)
        if not match:
            self.send_error_json("未知接口", 404)
            return
        try:
            payload = read_request_json(self)
        except json.JSONDecodeError:
            self.send_error_json("请求 JSON 无效")
            return

        workspace = load_workspace()
        index, existing = find_tool(match.group(1), workspace["tools"])
        if existing is None:
            self.send_error_json("工具不存在", 404)
            return

        tool = normalize_tool(payload, existing)
        workspace["tools"][index] = tool
        save_workspace(workspace)
        self.send_json({"tool": tool})

    def do_DELETE(self) -> None:
        route = urlparse(self.path).path
        match = re.fullmatch(r"/api/tools/([^/]+)", route)
        if not match:
            self.send_error_json("未知接口", 404)
            return

        workspace = load_workspace()
        before = len(workspace["tools"])
        workspace["tools"] = [tool for tool in workspace["tools"] if str(tool.get("id")) != match.group(1)]
        save_workspace(workspace)
        self.send_json({"deleted": len(workspace["tools"]) != before})


def main() -> None:
    ensure_dirs()
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    server = ThreadingHTTPServer((HOST, port), PortalHandler)
    print(f"Portal Hub running at http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Portal Hub")


if __name__ == "__main__":
    main()
