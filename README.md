# BT Tone Slapper

Portable Windows application for replacing event sounds on supported Bluetooth audio devices. The current release supports JBL Tune 720BT.

## For Normal Users

You do **not** need to build this project to flash your headphones.

Download the ready-to-use app here:

[dist/BTToneSlapper.exe](dist/BTToneSlapper.exe)

Then use it with a complete sound pack:

[Custom Sound Packs](Custom%20Sound%20Packs)

OEM recovery sound packs are also included in case you want to restore the original sounds and the official JBL download is unavailable:

[OEM Backups](OEM%20Backups)

## What Is What?

- **BT Tone Slapper** is the app. It runs on Windows and flashes sound packs to the headphones.
- **A sound pack** is a complete `.bin` file made for a specific headphone model.
- **A single sound file** is only source material, such as one `.wav` or `.mp3`. You do not flash a single sound file directly.
- **Build instructions** are only for developers who want to modify or rebuild the app.

Normal user flow:
Download EXE → connect headphones → choose sound pack → flash

## Features

- Converts WAV, MP3, FLAC, OGG, Opus, M4A, AAC, WMA, AIFF, AIF, and CAF audio automatically.
- Rebuilds the indexed mSBC prompt bank and all known integrity fields.
- Opens and validates existing compatible `.bin` containers.
- Uploads through the verified JBL BLE service after explicit user confirmation.
- Downloads and verifies the OEM English recovery container before every restore.
- Falls back to the pinned OEM copy in this GitHub repository when the manufacturer download fails.
- Produces a single portable EXE with no dependencies on the destination PC.

The OEM file is saved beside the EXE after successful verification. Build reuses that
copy when valid; Restore OEM always attempts a fresh manufacturer download first.
Unknown file sizes or hashes are rejected and are never trusted automatically.

## Build (for developers)

> [!NOTE]
> Use the pre-built .exe in the [dist](dist) folder if you just want to use the program.



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

## Author and License

BT Tone Slapper was originally created by Yaroslav Tselovanskyi.
Original project: <https://github.com/Tselovanskyi/BT-Tone-Slapper>

The original project source is licensed under the GNU General Public License
version 3 only, supplemented by the attribution requirements in
[`ATTRIBUTION.md`](ATTRIBUTION.md). Public forks must preserve the original
author notice in their primary README, and distributed interactive builds must
keep the attribution accessible in the application interface.

OEM files and other third-party components are excluded from the project
license and remain under their respective terms described in
[`THIRD_PARTY.md`](THIRD_PARTY.md).

## Source Layout

- `app.py` — application entry point and packaged-runtime self-test
- `bt_tone_slapper/` — application source
- `tests/` — development test suite
- `assets/` — required runtime binaries and icons
- `OEM Backups/` — pinned OEM recovery containers organized by device model
- `Custom Sound Packs/` — user-created prompt containers with compatibility notes
- `requirements-build.txt` — pinned build dependencies
- `build_portable.cmd` and `build_portable.ps1` — reproducible Windows build scripts

Virtual environments, caches, temporary files, and runtime logs are not included in this repository.
