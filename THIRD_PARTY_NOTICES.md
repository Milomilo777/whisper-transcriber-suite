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
| **FFmpeg** (`ffmpeg.exe`, `ffprobe.exe`) | LGPL-2.1+ or GPL (depends on the build) | Used for audio/video decode, slicing, subtitle burn-in. Confirm the exact terms of the bundled build before redistributing; LGPL/GPL obligations (license text + source availability) apply. |
| **yt-dlp** (`yt-dlp.exe`) | Unlicense (public domain) | Video downloads. |

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
| **SiriWave** ([kopiro/siriwave](https://github.com/kopiro/siriwave)) — classic-style curve maths, curve set and animation defaults | MIT | `app/widgets/audio_visualizer.py` (Live tab wave display), ported from TypeScript to Tk. |

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
