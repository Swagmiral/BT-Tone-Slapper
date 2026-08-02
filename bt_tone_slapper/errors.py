from __future__ import annotations


FALLBACK_MESSAGES = {
    "scan": "Device scan failed. Check that Bluetooth is turned on and try again.",
    "build": "Build failed. Check the selected audio files and save location, then try again.",
    "open": "The selected file could not be opened as a supported prompt container.",
    "upload": "Upload failed. Reconnect the headphones and try again.",
    "recovery": "OEM restore failed. Reconnect the headphones and try again.",
}


class UserFacingError(ValueError):
    pass


def user_error_message(operation: str, error: Exception) -> str:
    if operation == "startup":
        return (
            "BT Tone Slapper could not start because a required app file is missing "
            "or damaged. Reinstall or extract a fresh copy of the app."
        )
    if isinstance(error, FileNotFoundError):
        if operation == "open":
            return "The selected file no longer exists. Choose it again."
        if operation in {"upload", "recovery"}:
            return (
                "The loaded file no longer exists. Open it again or rebuild before "
                "uploading."
            )
        return (
            "A selected file could not be found. Choose it again or reset that prompt "
            "to OEM."
        )
    if isinstance(error, PermissionError):
        return "The app could not access that file. Check its permissions or choose another location."
    if isinstance(error, UserFacingError):
        message = str(error).strip()
        if message:
            return message
    return FALLBACK_MESSAGES.get(operation, "The operation failed. Please try again.")
