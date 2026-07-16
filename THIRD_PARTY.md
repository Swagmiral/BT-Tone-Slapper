# Third-Party Components

## FFmpeg

- Bundled executable: `assets/ffmpeg.exe`
- Upstream version: FFmpeg 7.1, distributed by `imageio-ffmpeg` 0.6.0
- Project: <https://ffmpeg.org/>
- SHA-256: `2ce797a0f88d7f067180338fb227f7b1928ea727bd9a4d7a1d022f7c52af71a3`

## LZMA SDK

- Bundled executable: `assets/LzmaAlone.exe`
- Purpose: emits the known-size/no-EOS LZMA-alone streams accepted by the headset.
- Source implementation: public-domain LZMA SDK encoder.
- SHA-256: `e2d96d96f7c0eb3c6ac13fdcf8ddd664d7bc18916156ffaff09c285327d93ee0`

## Bleak and WinRT

- Installed from `requirements-build.txt` into an isolated build environment.
- Bundled into the portable EXE by PyInstaller.
- Used for Windows Bluetooth LE discovery, GATT verification, and acknowledged characteristic writes.

## Material Symbols

- Reset icon variants are stored under `assets/icons/`.
- License: `assets/icons/MATERIAL_ICONS_LICENSE.txt`
