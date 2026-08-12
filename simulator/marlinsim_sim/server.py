"""Web UI server — HTTP + WebSocket for live display, controls, and G-code terminal."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from pathlib import Path
from typing import Optional

from aiohttp import web

from .core import SimulatorCore

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "web"


class WebServer:
    """Async web server providing:

    - HTTP: Serves the single-page Web UI (HTML/JS/CSS)
    - WebSocket /ws: Bidirectional real-time communication
        - Server → Client: LCD framebuffer, printer state, G-code responses
        - Client → Server: Encoder events, G-code commands, control actions
    """

    def __init__(
        self,
        simulator: SimulatorCore,
        host: str = "0.0.0.0",
        port: int = 8080,
    ):
        self.simulator = simulator
        self.host = host
        self.port = port

        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._ws_clients: set[web.WebSocketResponse] = set()
        self._last_lcd_data: bytes = b""
        self._state_interval = 0.1  # 100ms state push

    async def start(self) -> None:
        """Start the web server."""
        self._app = web.Application()
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/ws", self._handle_ws)
        self._app.router.add_static("/static", STATIC_DIR, show_index=False)

        # API endpoints
        self._app.router.add_post("/api/gcode", self._handle_gcode)
        self._app.router.add_get("/api/state", self._handle_state)
        self._app.router.add_get("/api/models", self._handle_models)

        # Register callbacks on simulator
        self.simulator.on_lcd_update(self._on_lcd_update)
        self.simulator.on_state_update(self._on_state_update)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()

        logger.info("Web UI available at http://%s:%d", self.host, self.port)

    async def stop(self) -> None:
        """Stop the web server."""
        # Close all WebSocket connections
        for ws in list(self._ws_clients):
            await ws.close()
        self._ws_clients.clear()

        if self._runner:
            await self._runner.cleanup()

    # ------------------------------------------------------------------
    # HTTP handlers
    # ------------------------------------------------------------------

    async def _handle_index(self, request: web.Request) -> web.Response:
        """Serve the main HTML page."""
        index_path = STATIC_DIR / "index.html"
        if index_path.exists():
            return web.FileResponse(index_path)
        return web.Response(
            text="<h1>MarlinSIM</h1><p>Web UI files not found.</p>",
            content_type="text/html",
        )

    async def _handle_gcode(self, request: web.Request) -> web.Response:
        """Send G-code command via REST API."""
        data = await request.json()
        cmd = data.get("command", "").strip()
        if not cmd:
            return web.json_response({"error": "Empty command"}, status=400)

        self.simulator.send_gcode(cmd)
        response = await self.simulator.read_response(timeout=3.0)
        return web.json_response({"command": cmd, "response": response})

    async def _handle_state(self, request: web.Request) -> web.Response:
        """Get current simulator state."""
        return web.json_response(self.simulator.get_state())

    async def _handle_models(self, request: web.Request) -> web.Response:
        """List available printer models."""
        from .models import list_models
        return web.json_response({"models": list_models()})

    # ------------------------------------------------------------------
    # WebSocket handler
    # ------------------------------------------------------------------

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        """WebSocket endpoint for real-time communication."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._ws_clients.add(ws)
        logger.info("WebSocket client connected (%d total)", len(self._ws_clients))

        # Send initial state
        await ws.send_json({
            "type": "init",
            "printer": self.simulator.printer.name,
            "display": {
                "width": self.simulator.printer.display.width,
                "height": self.simulator.printer.display.height,
                "type": self.simulator.printer.display.type,
            },
            "state": self.simulator.get_state(),
        })

        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    await self._handle_ws_message(ws, json.loads(msg.data))
                elif msg.type == web.WSMsgType.ERROR:
                    logger.warning("WebSocket error: %s", ws.exception())
        finally:
            self._ws_clients.discard(ws)
            logger.info("WebSocket client disconnected (%d remaining)",
                        len(self._ws_clients))

        return ws

    async def _handle_ws_message(
        self, ws: web.WebSocketResponse, msg: dict
    ) -> None:
        """Handle incoming WebSocket message from client."""
        msg_type = msg.get("type", "")

        if msg_type == "gcode":
            # Send G-code command
            cmd = msg.get("command", "").strip()
            if cmd:
                self.simulator.send_gcode(cmd)
                response = await self.simulator.read_response(timeout=2.0)
                await ws.send_json({
                    "type": "gcode_response",
                    "command": cmd,
                    "response": response,
                })

        elif msg_type == "encoder_rotate":
            clicks = msg.get("clicks", 0)
            self.simulator.encoder_rotate(clicks)

        elif msg_type == "encoder_click":
            pressed = msg.get("pressed", True)
            self.simulator.encoder_click(pressed)

        elif msg_type == "get_lcd":
            # Force LCD framebuffer send
            lcd_data = self.simulator.get_lcd_framebuffer()
            await ws.send_json({
                "type": "lcd",
                "data": base64.b64encode(lcd_data).decode("ascii"),
                "width": self.simulator.printer.display.width,
                "height": self.simulator.printer.display.height,
            })

        elif msg_type == "get_state":
            await ws.send_json({
                "type": "state",
                "data": self.simulator.get_state(),
            })

        elif msg_type == "get_log":
            n = msg.get("count", 50)
            await ws.send_json({
                "type": "gcode_log",
                "lines": self.simulator.get_gcode_log(n),
            })

    # ------------------------------------------------------------------
    # Simulator callbacks — broadcast to all WebSocket clients
    # ------------------------------------------------------------------

    def _on_lcd_update(self, lcd_data: bytes) -> None:
        """Called when LCD framebuffer is updated."""
        self._last_lcd_data = lcd_data
        msg = {
            "type": "lcd",
            "data": base64.b64encode(lcd_data).decode("ascii"),
            "width": self.simulator.printer.display.width,
            "height": self.simulator.printer.display.height,
        }
        asyncio.ensure_future(self._broadcast(msg))

    def _on_state_update(self, state: dict) -> None:
        """Called when physics state updates."""
        msg = {"type": "state", "data": state}
        asyncio.ensure_future(self._broadcast(msg))

    async def _broadcast(self, msg: dict) -> None:
        """Send message to all connected WebSocket clients."""
        dead = set()
        for ws in self._ws_clients:
            try:
                await ws.send_json(msg)
            except (ConnectionResetError, RuntimeError):
                dead.add(ws)
        self._ws_clients -= dead
