"""Bleak transport for guarded physical HmOtaMgr uploads."""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from .bluetooth import inspect_service_collection
from .protocol import NOTIFY_UUID, WRITE_UUID
from .uploader import UploadConnectionError


class BleakUploadTransport:
    def __init__(
        self,
        identifier: str,
        *,
        connect_timeout: float = 20.0,
        captured_mtu: int = 220,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.identifier = identifier
        self.connect_timeout = connect_timeout
        self.mtu = captured_mtu
        self.client_factory = client_factory
        self.disconnected_event = asyncio.Event()
        self.client: Any = None
        self.subscribed = False

    def _on_disconnected(self, _: Any) -> None:
        self.disconnected_event.set()

    async def __aenter__(self) -> "BleakUploadTransport":
        if self.client_factory is None:
            from bleak import BleakClient

            self.client_factory = BleakClient
        self.client = self.client_factory(
            self.identifier,
            timeout=self.connect_timeout,
            pair=False,
            disconnected_callback=self._on_disconnected,
        )
        try:
            await self.client.connect()
        except Exception as error:
            raise UploadConnectionError(
                "Could not connect to the headphones. Make sure they are powered on and connected to this PC."
            ) from error
        inspection = inspect_service_collection(self.identifier, self.client.services)
        if not inspection.protocol_ready:
            await self.client.disconnect()
            raise UploadConnectionError(
                "The selected device does not support JBL Tone Studio uploads."
            )
        negotiated_mtu = int(self.client.mtu_size)
        if negotiated_mtu < self.mtu:
            await self.client.disconnect()
            raise UploadConnectionError(
                "The Bluetooth connection does not support the required upload packet size. "
                "Reconnect the headphones and try again."
            )
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        if self.client is not None:
            if self.subscribed and not self.disconnected_event.is_set():
                try:
                    await self.unsubscribe()
                except Exception:
                    pass
            if not self.disconnected_event.is_set():
                await self.client.disconnect()
        return False

    async def subscribe(self, callback: Callable[[Any, bytearray], None]) -> None:
        if self.client is None:
            raise UploadConnectionError(
                "The headphones are not connected. Reconnect them and try again."
            )
        try:
            await self.client.start_notify(NOTIFY_UUID, callback)
        except Exception as error:
            raise UploadConnectionError(
                "Could not start the upload. Reconnect the headphones and try again."
            ) from error
        self.subscribed = True

    async def unsubscribe(self) -> None:
        if self.client is not None and self.subscribed and not self.disconnected_event.is_set():
            await self.client.stop_notify(NOTIFY_UUID)
        self.subscribed = False

    async def write(self, frame: bytes) -> None:
        if self.client is None or self.disconnected_event.is_set():
            raise UploadConnectionError(
                "The headphones disconnected during upload. Reconnect them and try again."
            )
        try:
            await self.client.write_gatt_char(WRITE_UUID, frame, response=True)
        except Exception as error:
            raise UploadConnectionError(
                "Bluetooth communication failed. Reconnect the headphones and try again."
            ) from error
