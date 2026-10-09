# Third-Party Notices

Whisper Transcriber Suite's own source code is licensed under the **BSD 3-Clause
License** (see [LICENSE](LICENSE)).

The distributed application (the Setup-Standard installer and the Portable
ZIP) **bundles third-party software**, each under its own license. Those
licenses are NOT changed by this project's BSD license, and when you
redistribute the bundled application you must comply with each component's
terms. This file is an informational summary — the authoritative text for
every Python package ships inside the distribution under
`Lib\site-packages\<package>\` (a `LICENSE` / `COPYING` file per package).

## Bundled runtime + binaries

| Component | Typical license | Notes |
|---|---|---|
| **CPython** (embeddable runtime) | PSF License Agreement | The `python\` folder in the distribution. |
| **FFmpeg** (`ffmpeg.exe`, `ffprobe.exe`) | GPL-3.0-or-later (the bundled builds are configured with `--enable-gpl --enable-version3` and include libx264/libx265) | Used for audio/video decode, slicing, subtitle burn-in. Windows: the gyan.dev "essentials" build pinned in `platform/windows/build-deps.json`; macOS: the evermeet.cx (Intel) and martin-riedl.de (Apple Silicon) static builds pinned in `platform/macos/pyinstaller/fetch_mac_binaries.sh`. GPL obligations (license text + source availability) apply; see "FFmpeg corresponding source" below. |
| **yt-dlp** (`yt-dlp.exe`) | Unlicense (public domain) | Video downloads. |
| **Deno** (`deno.exe`) | MIT | JavaScript runtime that yt-dlp uses for YouTube. |

### FFmpeg corresponding source

A copy of the corresponding source of each bundled FFmpeg build, byte for byte the files
below, is attached to each GitHub release of this app that ships that build
(file names `WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*`), so the links cannot go
stale. The pins (URL, size, SHA-256) are in `platform/ffmpeg-source.json`.

| Bundled build | FFmpeg source | SHA-256 |
|---|---|---|
| Windows: gyan.dev essentials build `9.0.2` | FFmpeg 9.0.2 release: https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz (signature: https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz.asc). The build names commit `946fcce07b` (https://github.com/GyanD/codexffmpeg/releases/tag/9.0.2), which is the commit of the release tag `n9.0.2`. | `8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e` |
| macOS Intel: evermeet.cx FFmpeg 9.0.2 | FFmpeg 9.0.2 release: https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz (signature: https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz.asc) | `8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e` |
| macOS Apple silicon: ffmpeg.martin-riedl.de build `1789931890_9.0.2` | the same FFmpeg 9.0.2 release tarball; build script: https://git.martin-riedl.de/ffmpeg/build-script | (as above) |

The FFmpeg tarball is the source of FFmpeg itself. The static builds also link third-party
libraries (for example x264 and x265); their projects publish those sources, and the
builders list the libraries and versions: https://www.gyan.dev/ffmpeg/builds/ (Windows),
https://evermeet.cx/ffmpeg/ (macOS Intel) and the `versions.txt` next to each build at
https://ffmpeg.martin-riedl.de/ (macOS Apple silicon).

## Bundled Python packages (selected)

Each ships its full license text in its `site-packages` folder.

- **faster-whisper** — MIT
- **openai-whisper** — MIT
- **stable-ts** — MIT
- **ctranslate2** — MIT
- **PyTorch / torchaudio** — BSD-3-Clause
- **numpy** — BSD-3-Clause
- **tokenizers / huggingface-hub** — Apache-2.0
- **sherpa-onnx / onnxruntime** — Apache-2.0
- **pywhispercpp** (whisper.cpp bindings) — MIT
- **arabic-reshaper** — MIT (joins Arabic-script letters in PDF output)
- **python-bidi** — LGPL-3.0-or-later, shipped unmodified as its own package and
  imported at runtime (right-to-left line order in PDF output); its compiled
  extension wraps the `unicode-bidi` Rust crate (MIT / Apache-2.0). Source:
  https://github.com/MeirKriheli/python-bidi (also on PyPI). To use another
  build, replace the `bidi` folder in the app's `site-packages`
  (`python\Lib\site-packages\bidi` in the Windows installer and Portable ZIP).
- **sv-ttk**, **tkinterdnd2**, **pystray**, **Pillow**, **requests**,
  **rich**, **typer**, **reportlab**, **python-docx**, **watchdog**,
  **python-vlc** — see each package's bundled LICENSE (MIT / BSD / Apache /
  LGPL variants).

## On-demand optional packages (not bundled)

Some features install their packages from PyPI on first use instead of
shipping in the base installer, keeping the default install small. Each
installs only if you opt into that specific feature.

- **OmniVoice** (k2-fsa) — Apache-2.0, on both code and pretrained weights.
  Powers the optional Clone Your Voice / Text to Voice tab; installs
  together with `torch` (BSD-3-Clause) and `soundfile` (BSD-3-Clause) on
  first generation. Version is unpinned in `core/optional_deps.py` (always
  the latest PyPI release at install time). Its ~2GB model weights
  (`k2-fsa/OmniVoice` on Hugging Face) are fetched separately by the
  package itself, also on first use.

## Models

- The **Whisper** speech-to-text model weights (e.g.
  `Systran/faster-whisper-large-v3`) are distributed under the model's own
  license (Whisper is MIT from OpenAI). The model is downloaded at first
  run, not bundled in the installer.

## Website (`site/`)

The landing page bundles these third-party files under `site/assets/` so the
page makes no third-party network requests:

| Component | License | Notes |
|---|---|---|
| **three.js** r186 (`assets/vendor/three/`) | MIT | WebGL hero scene. Full text in `assets/vendor/three/LICENSE`. |
| **Sora** (`assets/fonts/sora-*.woff2`) | SIL Open Font License 1.1 | Display typeface. |
| **Geist** (`assets/fonts/geist-*.woff2`) | SIL Open Font License 1.1 | Body typeface. |
| **Geist Mono** (`assets/fonts/geist-mono-*.woff2`) | SIL Open Font License 1.1 | Chips / timestamps. |

Full OFL text for all three font families is in `assets/fonts/OFL.txt`.

## Adapted source code

| Component | License | Where |
|---|---|---|
| **SiriWave** ([kopiro/siriwave](https://github.com/kopiro/siriwave)) — iOS 9-style curve maths, spawn/despawn behaviour, colours and animation defaults | MIT | `app/widgets/audio_visualizer.py` (Live tab wave display), ported from TypeScript to numpy + Pillow. |

SiriWave license:

```
MIT License

Copyright (c) 2020 Flavio Maria De Stefano

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## In short

- **Our code:** BSD-3-Clause (permissive — attribution only).
- **Bundled components:** keep their own licenses; ship their license texts
  with any redistribution. The pip packages already include theirs inside
  `site-packages`; for FFmpeg in particular, verify the bundled build's
  LGPL/GPL terms when distributing.
