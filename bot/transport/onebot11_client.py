"""OneBot11 WebSocket client with reconnect and action helpers."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any


LOG = logging.getLogger("qwbot.onebot")
EventHandler = Callable[["OneBot11Client", str | bytes], Awaitable[None]]


class OneBot11Client:
    def __init__(
        self,
        ws_url: str,
        access_token: str = "",
        reconnect_seconds: int = 5,
        ping_interval: int = 20,
        ping_timeout: int = 20,
    ) -> None:
        self.ws_url = ws_url
        self.access_token = access_token
        self.reconnect_seconds = max(1, int(reconnect_seconds))
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self._ws: Any = None
        self._send_lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self.account_id: int | None = None
        self.connected_at: float | None = None
        self.last_event_at: float | None = None
        self.last_message_at: float | None = None
        self.connection_count = 0

    async def run(self, handler: EventHandler) -> None:
        """Keep connecting until stop() is called."""
        while not self._stop.is_set():
            try:
                await self._run_once(handler)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOG.warning("OneBot connection stopped: %s", exc)
            if not self._stop.is_set():
                await asyncio.sleep(self.reconnect_seconds)

    async def _run_once(self, handler: EventHandler) -> None:
        # Import lazily so offline tests for parsing/storage do not require websockets.
        try:
            from websockets.asyncio.client import connect
        except ImportError as exc:
            raise RuntimeError(
                "Missing dependency websockets; run python -m pip install -r requirements.txt"
            ) from exc

        headers = {"Authorization": f"Bearer {self.access_token}"} if self.access_token else None
        kwargs: dict[str, Any] = {
            "ping_interval": self.ping_interval,
            "ping_timeout": self.ping_timeout,
        }
        if headers:
            kwargs["additional_headers"] = headers
        LOG.info("connecting to OneBot11: %s", self.ws_url)
        try:
            connection = connect(self.ws_url, **kwargs)
            async with connection as ws:
                self._ws = ws
                self.connected_at = time.time()
                self.connection_count += 1
                LOG.info("OneBot11 connected")
                await self._receive_events(ws, handler)
        except TypeError:
            # Compatibility with older websockets releases using extra_headers.
            if not headers:
                raise
            kwargs.pop("additional_headers", None)
            kwargs["extra_headers"] = headers
            async with connect(self.ws_url, **kwargs) as ws:
                self._ws = ws
                self.connected_at = time.time()
                self.connection_count += 1
                LOG.info("OneBot11 connected")
                await self._receive_events(ws, handler)
        finally:
            self._ws = None

    async def _receive_events(self, ws: Any, handler: EventHandler) -> None:
        """Read every inbound WebSocket frame and expose it to the dispatcher.

        The full frame log is intentionally temporary diagnostic instrumentation. It
        makes it possible to distinguish a NapCat event-source issue from a parser or
        dispatcher filter issue without changing the OneBot connection settings.
        """
        async for raw in ws:
            if isinstance(raw, bytes):
                raw_text = raw.decode("utf-8", errors="replace")
            else:
                raw_text = str(raw)
            self.last_event_at = time.time()
            LOG.info("OneBot11 raw event received: %s", raw_text)
            try:
                event = json.loads(raw_text)
                if isinstance(event, dict):
                    self_id = event.get("self_id")
                    if self_id is not None:
                        self.account_id = int(self_id)
                    if event.get("post_type") == "message":
                        self.last_message_at = self.last_event_at
                    if event.get("meta_event_type") == "heartbeat":
                        LOG.debug("OneBot heartbeat status=%s", event.get("status"))
            except (TypeError, ValueError):
                pass
            await handler(self, raw)

    def health(self) -> dict[str, int | float | bool | None]:
        """Return connection telemetry without exposing credentials."""
        return {
            "connected": self._ws is not None,
            "account_id": self.account_id,
            "connected_at": self.connected_at,
            "last_event_at": self.last_event_at,
            "last_message_at": self.last_message_at,
            "connection_count": self.connection_count,
        }

    async def send_action(
        self,
        action: str,
        params: dict[str, Any],
        echo: str | None = None,
    ) -> None:
        if self._ws is None:
            raise RuntimeError("OneBot11 is not connected")
        payload: dict[str, Any] = {"action": action, "params": params}
        if echo:
            payload["echo"] = echo
        async with self._send_lock:
            await self._ws.send(json.dumps(payload, ensure_ascii=False))

    async def send_group_message(self, group_id: int, message: Any, echo: str | None = None) -> None:
        await self.send_action(
            "send_group_msg",
            {"group_id": int(group_id), "message": message},
            echo=echo,
        )

    async def send_private_message(self, user_id: int, message: Any, echo: str | None = None) -> None:
        await self.send_action(
            "send_private_msg",
            {"user_id": int(user_id), "message": message},
            echo=echo,
        )

    async def set_qq_avatar(self, file: str, echo: str | None = None) -> None:
        """Set the logged-in QQ account avatar through NapCat's extension API."""
        await self.send_action("set_qq_avatar", {"file": str(file)}, echo=echo)

    async def stop(self) -> None:
        self._stop.set()
        if self._ws is not None:
            await self._ws.close()
