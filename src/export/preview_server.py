"""Live preview HTTP and WebSocket server for Project Memory Cortex with Multi-Project Support."""

import asyncio
import http.server
import json
from pathlib import Path
import socketserver
import threading
import time
from typing import Any, Dict, List, Optional, Set
import urllib.parse

import websockets

from ..core.storage import MemoryStorage
from ..utils.config import Config
from .markdown_exporter import MarkdownExporter
from .templates import HTML_PREVIEW_TEMPLATE


class MarkdownPreviewServer:
    """Real-time markdown preview and dashboard server with multi-project & WebSocket live-reload."""

    def __init__(self, storage: MemoryStorage, export_dir: Path, port: int = 4000, ws_port: Optional[int] = None):
        self.storage = storage
        self.export_dir = Path(export_dir)
        self.port = port
        self.ws_port = ws_port if ws_port is not None else (port + 1)
        self.clients: Set[Any] = set()
        self.html_content = HTML_PREVIEW_TEMPLATE
        self.exporter = MarkdownExporter(storage)
        self.running = False
        self._httpd: socketserver.TCPServer | None = None
        self._ws_loop: asyncio.AbstractEventLoop | None = None
        self._storage_cache: Dict[str, MemoryStorage] = {}
        # Client selected project map: ws_client -> project_str
        self._client_projects: Dict[Any, str] = {}

    def _get_projects_list(self) -> List[Dict[str, Any]]:
        """Return list of all registered projects with counts and active state."""
        registered = Config.list_registered_projects()
        current_root = Config.find_project_root()
        registered[current_root.name] = str(current_root.resolve())

        projects = []
        for name, path_str in sorted(registered.items()):
            root = Path(path_str)
            db_path = Config.get_db_path(root)
            count = 0
            if db_path.exists():
                try:
                    s = self._resolve_storage(name)
                    count = s.get_count()
                except Exception:
                    count = 0
            projects.append({
                "name": name,
                "path": path_str,
                "count": count,
                "active": (root == current_root),
            })
        return projects

    def _resolve_storage(self, project: Optional[str] = None) -> MemoryStorage:
        """Resolve storage for a specific project name or directory."""
        if not project or project in ("current", "active"):
            return self.storage

        registered = Config.list_registered_projects()
        target_path_str = registered.get(project, project)
        target_root = Config.find_project_root(target_path_str)
        key = str(target_root.resolve())

        if key not in self._storage_cache:
            db_path = Config.get_db_path(target_root)
            self._storage_cache[key] = MemoryStorage(db_path)

        return self._storage_cache[key]

    def _get_memories_payload(self, project: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch memories for single project or all projects and format for frontend display."""
        payload = []

        if project == "all":
            registered = Config.list_registered_projects()
            current_root = Config.find_project_root()
            registered[current_root.name] = str(current_root.resolve())

            seen_ids = set()
            for proj_name, path_str in registered.items():
                root = Path(path_str)
                db_path = Config.get_db_path(root)
                if not db_path.exists():
                    continue
                try:
                    s = self._resolve_storage(proj_name)
                    exporter = MarkdownExporter(s)
                    nodes = s.get_all(limit=200)
                    for node in nodes:
                        if node.id in seen_ids:
                            continue
                        seen_ids.add(node.id)
                        payload.append({
                            "id": node.id,
                            "timestamp": node.timestamp,
                            "type": node.type,
                            "title": node.title or node.summary,
                            "summary": node.summary,
                            "content": node.content,
                            "tags": node.tags,
                            "impact": node.impact,
                            "project": proj_name,
                            "markdown": exporter.format_node_markdown(node),
                        })
                except Exception:
                    continue

            payload.sort(key=lambda m: m["timestamp"], reverse=True)
            return payload

        # Single project
        target_storage = self._resolve_storage(project)
        current_root = Config.find_project_root()
        proj_label = project if (project and project != "current") else current_root.name
        exporter = MarkdownExporter(target_storage)
        nodes = target_storage.get_all(limit=500)

        for node in nodes:
            payload.append({
                "id": node.id,
                "timestamp": node.timestamp,
                "type": node.type,
                "title": node.title or node.summary,
                "summary": node.summary,
                "content": node.content,
                "tags": node.tags,
                "impact": node.impact,
                "project": proj_label,
                "markdown": exporter.format_node_markdown(node),
            })
        return payload

    def _create_http_handler(self):
        server_self = self

        class Handler(http.server.SimpleHTTPRequestHandler):
            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed.query)
                selected_project = params.get("project", [None])[0]

                if parsed.path in ("/", "/index.html"):
                    self.send_response(200)
                    self.send_header("Content-type", "text/html; charset=utf-8")
                    self.end_headers()
                    rendered_html = server_self.html_content.replace("__WS_PORT__", str(server_self.ws_port))
                    self.wfile.write(rendered_html.encode("utf-8"))
                elif parsed.path == "/api/projects":
                    projects = server_self._get_projects_list()
                    current_root = Config.find_project_root()
                    self.send_response(200)
                    self.send_header("Content-type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "projects": projects,
                        "current_project": current_root.name
                    }).encode("utf-8"))
                elif parsed.path in ("/memories", "/api/memories"):
                    memories = server_self._get_memories_payload(selected_project)
                    self.send_response(200)
                    self.send_header("Content-type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps(memories).encode("utf-8"))
                elif parsed.path == "/health":
                    self.send_response(200)
                    self.send_header("Content-type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"OK")
                elif parsed.path.startswith("/api/memories/"):
                    node_id = parsed.path.split("/api/memories/")[-1]
                    storage = server_self._resolve_storage(selected_project)
                    deleted = storage.delete_memory(node_id)
                    self.send_response(200 if deleted else 404)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": deleted, "node_id": node_id}).encode())
                    if deleted:
                        server_self._broadcast_update()
                else:
                    self.send_error(404, "Not Found")

            def do_DELETE(self):
                parsed = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed.query)
                selected_project = params.get("project", [None])[0]

                if parsed.path.startswith("/api/memories/"):
                    node_id = parsed.path.split("/api/memories/")[-1]
                    storage = server_self._resolve_storage(selected_project)
                    deleted = storage.delete_memory(node_id)
                    self.send_response(200 if deleted else 404)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": deleted, "node_id": node_id}).encode())
                    if deleted:
                        server_self._broadcast_update()
                elif parsed.path == "/api/memories":
                    storage = server_self._resolve_storage(selected_project)
                    count = storage.clear_all_memories()
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True, "count": count}).encode())
                    server_self._broadcast_update()
                else:
                    self.send_error(404, "Not Found")

            def log_message(self, format, *args):
                pass  # Suppress default request logging

        return Handler

    def _broadcast_update(self):
        """Helper to broadcast memory & project updates to all WebSocket clients."""
        if not self.clients or not self._ws_loop:
            return

        projects = self._get_projects_list()
        current_root = Config.find_project_root()

        async def broadcast():
            dead = set()
            for client in list(self.clients):
                try:
                    selected_proj = self._client_projects.get(client, "current")
                    payload = json.dumps({
                        "type": "update",
                        "projects": projects,
                        "current_project": current_root.name,
                        "selected_project": selected_proj,
                        "memories": self._get_memories_payload(selected_proj),
                    })
                    await client.send(payload)
                except Exception:
                    dead.add(client)
            self.clients.difference_update(dead)
            for d in dead:
                self._client_projects.pop(d, None)

        if self._ws_loop.is_running():
            asyncio.run_coroutine_threadsafe(broadcast(), self._ws_loop)

    async def _websocket_handler(self, websocket):
        """Handle incoming WebSocket connections from preview clients."""
        self.clients.add(websocket)
        self._client_projects[websocket] = "current"
        try:
            projects = self._get_projects_list()
            current_root = Config.find_project_root()

            # Send initial state
            initial_data = json.dumps({
                "type": "memories",
                "projects": projects,
                "current_project": current_root.name,
                "selected_project": "current",
                "memories": self._get_memories_payload("current"),
            })
            await websocket.send(initial_data)

            # Listen for client actions
            async for raw_msg in websocket:
                try:
                    data = json.loads(raw_msg)
                    action = data.get("action")
                    if action == "switch_project":
                        proj = data.get("project", "current")
                        self._client_projects[websocket] = proj
                        resp = json.dumps({
                            "type": "memories",
                            "projects": self._get_projects_list(),
                            "current_project": current_root.name,
                            "selected_project": proj,
                            "memories": self._get_memories_payload(proj),
                        })
                        await websocket.send(resp)
                    elif action == "refresh":
                        proj = self._client_projects.get(websocket, "current")
                        resp = json.dumps({
                            "type": "memories",
                            "projects": self._get_projects_list(),
                            "current_project": current_root.name,
                            "selected_project": proj,
                            "memories": self._get_memories_payload(proj),
                        })
                        await websocket.send(resp)
                    elif action == "delete":
                        node_id = data.get("node_id")
                        proj = data.get("project") or self._client_projects.get(websocket)
                        if node_id:
                            storage = self._resolve_storage(proj)
                            storage.delete_memory(node_id)
                            self._broadcast_update()
                    elif action == "clear":
                        proj = data.get("project") or self._client_projects.get(websocket)
                        storage = self._resolve_storage(proj)
                        storage.clear_all_memories()
                        self._broadcast_update()
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            self.clients.discard(websocket)
            self._client_projects.pop(websocket, None)

    def _run_websocket_server(self):
        """Thread worker to run asyncio WebSocket server."""
        self._ws_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._ws_loop)

        async def serve_ws():
            async with websockets.serve(self._websocket_handler, "0.0.0.0", self.ws_port):
                while self.running:
                    await asyncio.sleep(1)

        try:
            self._ws_loop.run_until_complete(serve_ws())
        except Exception:
            pass

    def _monitor_changes(self):
        """Thread worker to monitor database changes across all registered projects and broadcast updates."""
        project_counts: Dict[str, int] = {}

        while self.running:
            time.sleep(1.5)
            registered = Config.list_registered_projects()
            current_root = Config.find_project_root()
            registered[current_root.name] = str(current_root.resolve())

            changed = False
            for proj_name, path_str in registered.items():
                root = Path(path_str)
                db_path = Config.get_db_path(root)
                if not db_path.exists():
                    continue
                try:
                    s = self._resolve_storage(proj_name)
                    c = s.get_count()
                    if project_counts.get(proj_name) != c:
                        project_counts[proj_name] = c
                        changed = True
                except Exception:
                    pass

            if changed and self.clients and self._ws_loop:
                self._broadcast_update()

    def _find_available_port(self, start_port: int, max_attempts: int = 50) -> int:
        """Find an available TCP port starting from start_port."""
        import socket
        for p in range(start_port, start_port + max_attempts):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("", p))
                    return p
                except OSError:
                    continue
        return start_port

    def start(self, block: bool = True) -> None:
        """Start both HTTP and WebSocket preview servers with automatic port conflict resolution."""
        self.running = True

        # Check and resolve port conflicts automatically
        initial_port = self.port
        initial_ws_port = self.ws_port
        self.port = self._find_available_port(self.port)
        self.ws_port = self._find_available_port(self.ws_port)

        if self.port != initial_port or self.ws_port != initial_ws_port:
            print(f"Notice: Port conflict resolved. HTTP running on {self.port}, WebSocket running on {self.ws_port}.")

        # Start HTTP server
        handler = self._create_http_handler()
        self._httpd = socketserver.TCPServer(("", self.port), handler)
        http_thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        http_thread.start()

        # Start WebSocket server
        ws_thread = threading.Thread(target=self._run_websocket_server, daemon=True)
        ws_thread.start()

        # Start DB change monitor
        monitor_thread = threading.Thread(target=self._monitor_changes, daemon=True)
        monitor_thread.start()

        try:
            from rich.console import Console
            console = Console()
            console.print("\n[bold cyan]🐙 Project Memory Cortex (PMC) Server[/bold cyan]")
            console.print("[dim]Persistent, immutable, timestamped institutional memory[/dim]\n")
        except Exception:
            pass

        print(f"Project Memory Live Preview running at: http://localhost:{self.port}")
        print(f"WebSocket live-reload active on port: {self.ws_port}")

        if block:
            try:
                while self.running:
                    time.sleep(1)
            except KeyboardInterrupt:
                self.stop()

    def stop(self) -> None:
        """Stop all running servers."""
        self.running = False
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
