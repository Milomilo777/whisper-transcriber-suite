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

## Models

- The **Whisper** speech-to-text model weights (e.g.
  `Systran/faster-whisper-large-v3`) are distributed under the model's own
  license (Whisper is MIT from OpenAI). The model is downloaded at first
  run, not bundled in the installer.

## In short

- **Our code:** BSD-3-Clause (permissive — attribution only).
- **Bundled components:** keep their own licenses; ship their license texts
  with any redistribution. The pip packages already include theirs inside
  `site-packages`; for FFmpeg in particular, verify the bundled build's
  LGPL/GPL terms when distributing.
