"""Live preview HTTP and WebSocket server for Project Memory Cortex."""

import asyncio
import http.server
import json
from pathlib import Path
import socketserver
import threading
import time
from typing import Any, Dict, List, Set

import websockets

from ..core.storage import MemoryStorage
from .markdown_exporter import MarkdownExporter
from .templates import HTML_PREVIEW_TEMPLATE


class MarkdownPreviewServer:
    """Real-time markdown preview server with WebSocket live-reload."""

    def __init__(self, storage: MemoryStorage, export_dir: Path, port: int = 8080):
        self.storage = storage
        self.export_dir = Path(export_dir)
        self.port = port
        self.ws_port = port + 1
        self.clients: Set[Any] = set()
        self.html_content = HTML_PREVIEW_TEMPLATE
        self.exporter = MarkdownExporter(storage)
        self.running = False
        self._httpd: socketserver.TCPServer | None = None
        self._ws_loop: asyncio.AbstractEventLoop | None = None

    def _get_all_memories_payload(self) -> List[Dict[str, Any]]:
        """Fetch all memories and render markdown for frontend display."""
        nodes = self.storage.get_all(limit=500)
        payload = []
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
                "markdown": self.exporter.format_node_markdown(node),
            })
        return payload

    def _create_http_handler(self):
        server_self = self

        class Handler(http.server.SimpleHTTPRequestHandler):
            def do_GET(self):
                if self.path in ("/", "/index.html"):
                    self.send_response(200)
                    self.send_header("Content-type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(server_self.html_content.encode("utf-8"))
                elif self.path == "/memories":
                    memories = server_self._get_all_memories_payload()
                    self.send_response(200)
                    self.send_header("Content-type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps(memories).encode("utf-8"))
                elif self.path == "/health":
                    self.send_response(200)
                    self.send_header("Content-type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"OK")
                elif self.path.startswith("/api/memories/"):
                    node_id = self.path.split("/api/memories/")[-1]
                    deleted = server_self.storage.delete_memory(node_id)
                    self.send_response(200 if deleted else 404)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": deleted, "node_id": node_id}).encode())
                    if deleted:
                        server_self._broadcast_update()
                else:
                    self.send_error(404, "Not Found")

            def do_DELETE(self):
                if self.path.startswith("/api/memories/"):
                    node_id = self.path.split("/api/memories/")[-1]
                    deleted = server_self.storage.delete_memory(node_id)
                    self.send_response(200 if deleted else 404)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": deleted, "node_id": node_id}).encode())
                    if deleted:
                        server_self._broadcast_update()
                elif self.path == "/api/memories":
                    count = server_self.storage.clear_all_memories()
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
        """Helper to broadcast memory update to all WebSocket clients."""
        if not self.clients or not self._ws_loop:
            return
        payload = json.dumps({
            "type": "update",
            "memories": self._get_all_memories_payload(),
        })

        async def broadcast():
            dead = set()
            for c in list(self.clients):
                try:
                    await c.send(payload)
                except Exception:
                    dead.add(c)
            self.clients.difference_update(dead)

        if self._ws_loop.is_running():
            asyncio.run_coroutine_threadsafe(broadcast(), self._ws_loop)

    async def _websocket_handler(self, websocket):
        """Handle incoming WebSocket connections from preview clients."""
        self.clients.add(websocket)
        try:
            # Send initial state
            initial_data = json.dumps({
                "type": "memories",
                "memories": self._get_all_memories_payload(),
            })
            await websocket.send(initial_data)

            # Listen for client actions (e.g. delete)
            async for raw_msg in websocket:
                try:
                    data = json.loads(raw_msg)
                    if data.get("action") == "delete":
                        node_id = data.get("node_id")
                        if node_id:
                            self.storage.delete_memory(node_id)
                            self._broadcast_update()
                    elif data.get("action") == "clear":
                        self.storage.clear_all_memories()
                        self._broadcast_update()
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            self.clients.discard(websocket)

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
        """Thread worker to monitor database changes and broadcast updates to clients."""
        last_count = self.storage.get_count()

        while self.running:
            time.sleep(1.5)
            current_count = self.storage.get_count()
            if current_count != last_count and self.clients and self._ws_loop:
                last_count = current_count
                payload = json.dumps({
                    "type": "update",
                    "memories": self._get_all_memories_payload(),
                })

                # Broadcast update to all connected clients
                async def broadcast():
                    dead_clients = set()
                    for client in list(self.clients):
                        try:
                            await client.send(payload)
                        except Exception:
                            dead_clients.add(client)
                    self.clients.difference_update(dead_clients)

                if self._ws_loop.is_running():
                    asyncio.run_coroutine_threadsafe(broadcast(), self._ws_loop)

    def start(self, block: bool = True) -> None:
        """Start both HTTP and WebSocket preview servers."""
        self.running = True

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

        print(f"🚀 Project Memory Live Preview running at: http://localhost:{self.port}")
        print(f"📡 WebSocket live-reload active on port: {self.ws_port}")

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
