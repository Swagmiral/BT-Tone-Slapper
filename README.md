# BT Tone Slapper

Portable Windows application for replacing event sounds on supported Bluetooth audio devices. The current release supports JBL Tune 720BT English voice-prompt containers.

The prebuilt portable application is available at `dist/BTToneSlapper.exe`.

## Features

- Converts WAV, MP3, FLAC, OGG, Opus, M4A, AAC, WMA, AIFF, AIF, and CAF audio automatically.
- Rebuilds the indexed mSBC prompt bank and all known integrity fields.
- Opens and validates existing compatible `.bin` containers.
- Uploads through the verified JBL BLE service after explicit user confirmation.
- Downloads and verifies the OEM English recovery container before every restore.
- Falls back to the pinned OEM copy in this GitHub repository when the manufacturer download fails.
- Restricts device selection and upload to the JBL Tune 720BT profile.
- Produces a single portable EXE with no dependencies on the destination PC.

The OEM file is saved beside the EXE after successful verification. Build reuses that
copy when valid; Restore OEM always attempts a fresh manufacturer download first.
Unknown file sizes or hashes are rejected and are never trusted automatically.

## Build

Requirements on the build PC:

- Windows 10 or Windows 11
- Python 3.14 available as `python`
- Internet access for the first build to install pinned packages into `.venv`

Run:

```powershell
.\build_portable.cmd
```

The script creates an isolated local build environment and writes:

```text
dist\BTToneSlapper.exe
```

Python, Bleak, WinRT bindings, FFmpeg, the LZMA encoder, and icons are bundled into
the EXE. The OEM recovery container is deliberately not bundled. The destination PC
does not need Python or additional packages.

## Verify The EXE

```powershell
.\dist\BTToneSlapper.exe --self-test .\self-test.json
Get-Content .\self-test.json
```

## Tests

```powershell
.\run_tests.cmd
```

The tests automatically locate the project root from their location under `tests/`, so the repository can be moved or cloned to any directory without changing test paths. They are development files and are not imported by the application or bundled into the portable EXE.

## Source Layout

- `app.py` — application entry point and packaged-runtime self-test
- `bt_tone_slapper/` — application source
- `tests/` — development test suite
- `assets/` — runtime binaries, icons, and the pinned GitHub fallback container
- `requirements-build.txt` — pinned build dependencies
- `build_portable.cmd` and `build_portable.ps1` — reproducible Windows build scripts

Virtual environments, caches, temporary files, and runtime logs are not included in this repository.
