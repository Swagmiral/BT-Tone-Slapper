from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceProfile:
    profile_id: str
    display_name: str
    pid: str
    name_marker: str
    prompt_labels: tuple[str, ...]


TUNE_720BT_PROMPT_LABELS = (
    "Power on",
    "Power off",
    "Connected",
    "Pairing",
    "Battery is low",
    "Mute on",
    "Mute off",
    "Incoming call",
    "Voice prompt off",
    "Voice prompt on",
    "Maximum volume",
)


TUNE_720BT_PROFILE = DeviceProfile(
    profile_id="jbl-tune-720bt-20b4",
    display_name="JBL Tune 720BT",
    pid="20b4",
    name_marker="jbltune720bt",
    prompt_labels=TUNE_720BT_PROMPT_LABELS,
)
SUPPORTED_PROFILES = (TUNE_720BT_PROFILE,)


def normalize_device_name(name: str | None) -> str:
    return "".join(character for character in (name or "").casefold() if character.isalnum())


def resolve_device_profile(name: str | None) -> DeviceProfile | None:
    normalized = normalize_device_name(name)
    for profile in SUPPORTED_PROFILES:
        if profile.name_marker in normalized:
            return profile
    return None


def get_device_profile(profile_id: str | None) -> DeviceProfile | None:
    return next(
        (profile for profile in SUPPORTED_PROFILES if profile.profile_id == profile_id),
        None,
    )
