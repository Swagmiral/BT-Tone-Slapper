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

- Reset, Help, and Support icon assets are stored under `assets/icons/`.
- Upstream project: <https://github.com/google/material-design-icons>
- License: `assets/icons/MATERIAL_ICONS_LICENSE.txt`

## OEM recovery container

- Repository fallback: `assets/English_prompt_v0.0.5.bin`
- Original source: <https://storage.harman.com/MyJBLHeadphones/ota/release/20b4/tone/English_prompt_v0.0.5.bin>
- SHA-256: `91afbf099c9160fc251cf858c43b4d4df5bd9392cab5a6ab3b51ee0541d0ab9f`
- The fallback file is not bundled into the portable EXE.
