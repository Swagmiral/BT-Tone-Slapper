"""Bluetooth LE discovery, GATT inspection, and notification observation."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import asdict, dataclass
from typing import Any, Awaitable, Callable

from .protocol import NOTIFY_UUID, SERVICE_UUID, WRITE_UUID, parse_status


@dataclass(frozen=True)
class DiscoveredDevice:
    address: str
    name: str | None
    rssi: int
    service_uuids: tuple[str, ...]
    remembered: bool = False
    last_seen: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CharacteristicInfo:
    uuid: str
    properties: tuple[str, ...]


@dataclass(frozen=True)
class ServiceInspection:
    identifier: str
    connected: bool
    service_uuids: tuple[str, ...]
    service_present: bool
    notify_characteristic: CharacteristicInfo | None
    write_characteristic: CharacteristicInfo | None
    notify_capable: bool
    write_capable: bool

    @property
    def protocol_ready(self) -> bool:
        return self.service_present and self.notify_capable and self.write_capable

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["protocol_ready"] = self.protocol_ready
        return result


@dataclass(frozen=True)
class NotificationEvent:
    sender: str
    raw_hex: str
    kind: str
    status: str | None
    value: int | None
    error: str | None


@dataclass(frozen=True)
class NotificationObservation:
    identifier: str
    duration: float
    disconnected: bool
    events: tuple[NotificationEvent, ...]
    cleanup_error: str | None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["notification_count"] = len(self.events)
        result["hmota_status_count"] = sum(event.kind == "hmota_status" for event in self.events)
        result["other_count"] = sum(event.kind == "other" for event in self.events)
        result["wrote_command_characteristic"] = False
        return result


class NotificationCollector:
    def __init__(self) -> None:
        self.events: list[NotificationEvent] = []

    def __call__(self, sender: Any, data: bytearray) -> None:
        raw = bytes(data)
        try:
            notification = parse_status(raw)
            event = NotificationEvent(
                sender=str(getattr(sender, "uuid", sender)),
                raw_hex=raw.hex(" "),
                kind="hmota_status",
                status=notification.status.name,
                value=notification.value,
                error=None,
            )
        except ValueError as error:
            event = NotificationEvent(
                sender=str(getattr(sender, "uuid", sender)),
                raw_hex=raw.hex(" "),
                kind="other",
                status=None,
                value=None,
                error=str(error),
            )
        self.events.append(event)


def _normalized_uuid(value: Any) -> str:
    return str(value).lower()


def _device_identity(name: str | None) -> str:
    return "".join(character for character in (name or "").casefold() if character.isalnum())


def _decode_registry_name(value: Any) -> str | None:
    if isinstance(value, str):
        return value.rstrip("\0") or None
    if not isinstance(value, bytes):
        return None
    payload = value.rstrip(b"\0")
    if not payload:
        return None
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return payload.decode("utf-16-le")
        except UnicodeDecodeError:
            return None


def _windows_cached_ble_devices() -> list[DiscoveredDevice]:
    if sys.platform != "win32":
        return []
    try:
        import winreg

        root_path = r"SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Devices"
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root_path)
    except OSError:
        return []

    results: dict[str, DiscoveredDevice] = {}
    with root:
        index = 0
        while True:
            try:
                key_name = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            if len(key_name) != 12:
                continue
            try:
                int(key_name, 16)
                with winreg.OpenKey(root, key_name) as device_key:
                    raw_name = winreg.QueryValueEx(device_key, "LEName")[0]
                    try:
                        last_seen = int(winreg.QueryValueEx(device_key, "LastSeen")[0])
                    except OSError:
                        last_seen = 0
            except (OSError, ValueError):
                continue
            name = _decode_registry_name(raw_name)
            if not name:
                continue
            address = ":".join(key_name[position : position + 2] for position in range(0, 12, 2))
            candidate = DiscoveredDevice(
                address=address.upper(),
                name=name,
                rssi=-127,
                service_uuids=(),
                remembered=True,
                last_seen=last_seen,
            )
            identity = _device_identity(name)
            previous = results.get(identity)
            if previous is None or candidate.last_seen > previous.last_seen:
                results[identity] = candidate
    return list(results.values())


async def _windows_connected_bluetooth_identities() -> set[str]:
    if sys.platform != "win32":
        return set()
    try:
        from winrt.windows.devices.bluetooth import BluetoothConnectionStatus, BluetoothDevice
        from winrt.windows.devices.enumeration import DeviceInformation

        selector = BluetoothDevice.get_device_selector()
        devices = await DeviceInformation.find_all_async_aqs_filter(selector)
    except Exception:
        return set()

    connected = set()
    for information in devices:
        device = None
        try:
            device = await BluetoothDevice.from_id_async(information.id)
            if device is None or device.connection_status != BluetoothConnectionStatus.CONNECTED:
                continue
            identity = _device_identity(device.name or information.name)
            if identity:
                connected.add(identity)
        except Exception:
            continue
        finally:
            if device is not None:
                device.close()
    return connected


def inspect_service_collection(identifier: str, services: Any) -> ServiceInspection:
    service_list = list(services)
    target_service = None
    for service in service_list:
        if _normalized_uuid(service.uuid) == SERVICE_UUID:
            target_service = service
            break

    notify_info = None
    write_info = None
    if target_service is not None:
        for characteristic in target_service.characteristics:
            info = CharacteristicInfo(
                uuid=_normalized_uuid(characteristic.uuid),
                properties=tuple(sorted(str(prop).lower() for prop in characteristic.properties)),
            )
            if info.uuid == NOTIFY_UUID:
                notify_info = info
            elif info.uuid == WRITE_UUID:
                write_info = info

    notify_capable = notify_info is not None and bool(
        {"notify", "indicate"}.intersection(notify_info.properties)
    )
    write_capable = write_info is not None and bool(
        {"write", "write-without-response"}.intersection(write_info.properties)
    )
    return ServiceInspection(
        identifier=identifier,
        connected=True,
        service_uuids=tuple(sorted(_normalized_uuid(service.uuid) for service in service_list)),
        service_present=target_service is not None,
        notify_characteristic=notify_info,
        write_characteristic=write_info,
        notify_capable=notify_capable,
        write_capable=write_capable,
    )


async def scan_devices(
    *,
    timeout: float = 5.0,
    name_contains: str | None = None,
    scanner: Any = None,
    cached_provider: Callable[[], list[DiscoveredDevice]] | None = None,
    connected_provider: Callable[[], Awaitable[set[str]]] | None = None,
) -> list[DiscoveredDevice]:
    if scanner is None:
        from bleak import BleakScanner

        scanner = BleakScanner

    if cached_provider is None:
        cached_provider = _windows_cached_ble_devices
    if connected_provider is None:
        connected_provider = _windows_connected_bluetooth_identities

    connected_identities = await connected_provider()
    normalized_filter = _device_identity(name_contains)
    if normalized_filter:
        connected_identities = {
            identity for identity in connected_identities if normalized_filter in identity
        }
    if not connected_identities:
        return []

    discovered = await scanner.discover(
        timeout=timeout,
        return_adv=True,
        scanning_mode="active",
    )
    name_filter = name_contains.casefold() if name_contains else None
    results: dict[str, DiscoveredDevice] = {}
    for device, advertisement in discovered.values():
        name = advertisement.local_name or device.name
        if name_filter and name_filter not in (name or "").casefold():
            continue
        if _device_identity(name) not in connected_identities:
            continue
        result = DiscoveredDevice(
            address=device.address,
            name=name,
            rssi=advertisement.rssi,
            service_uuids=tuple(sorted(_normalized_uuid(uuid) for uuid in advertisement.service_uuids)),
        )
        results[result.address.casefold()] = result
    live_identities = {_device_identity(device.name) for device in results.values() if device.name}
    for cached in cached_provider():
        if name_filter and name_filter not in (cached.name or "").casefold():
            continue
        if _device_identity(cached.name) not in connected_identities:
            continue
        if _device_identity(cached.name) in live_identities:
            continue
        results.setdefault(cached.address.casefold(), cached)
    return sorted(
        results.values(),
        key=lambda device: (
            device.remembered,
            -device.last_seen if device.remembered else -device.rssi,
            device.name or "",
            device.address,
        ),
    )


async def inspect_device(
    identifier: str,
    *,
    timeout: float = 20.0,
    client_factory: Callable[..., Any] | None = None,
) -> ServiceInspection:
    if client_factory is None:
        from bleak import BleakClient

        client_factory = BleakClient

    client = client_factory(identifier, timeout=timeout, pair=False)
    async with client:
        return inspect_service_collection(identifier, client.services)


async def observe_notifications(
    identifier: str,
    *,
    duration: float = 5.0,
    timeout: float = 20.0,
    client_factory: Callable[..., Any] | None = None,
) -> NotificationObservation:
    if duration <= 0:
        raise ValueError("notification duration must be positive")
    if client_factory is None:
        from bleak import BleakClient

        client_factory = BleakClient

    disconnected_event = asyncio.Event()

    def on_disconnected(_: Any) -> None:
        disconnected_event.set()

    client = client_factory(
        identifier,
        timeout=timeout,
        pair=False,
        disconnected_callback=on_disconnected,
    )
    collector = NotificationCollector()
    subscribed = False
    disconnected = False
    cleanup_error = None
    async with client:
        inspection = inspect_service_collection(identifier, client.services)
        if not inspection.notify_capable:
            raise RuntimeError("known JBL notification characteristic is unavailable")
        await client.start_notify(NOTIFY_UUID, collector)
        subscribed = True
        try:
            await asyncio.wait_for(disconnected_event.wait(), timeout=duration)
            disconnected = True
        except TimeoutError:
            pass
        finally:
            if subscribed and not disconnected:
                try:
                    await client.stop_notify(NOTIFY_UUID)
                except Exception as error:
                    cleanup_error = f"{type(error).__name__}: {error}"

    return NotificationObservation(
        identifier=identifier,
        duration=duration,
        disconnected=disconnected,
        events=tuple(collector.events),
        cleanup_error=cleanup_error,
    )
