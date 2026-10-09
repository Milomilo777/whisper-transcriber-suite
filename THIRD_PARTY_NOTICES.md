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
| **Microsoft Visual C++ runtime** (`msvcp140.dll`, `msvcp140_1.dll`, `vcruntime140.dll`, `vcruntime140_1.dll` in `python\`) | Microsoft Software License Terms (Visual Studio "Distributable Code"); not covered by this project's BSD licence | Unmodified Microsoft files, deployed app-local so the app starts on a PC without the Visual C++ Redistributable. See "Microsoft Visual C++ runtime" below. |
| **yt-dlp** (`yt-dlp.exe`) | Unlicense (public domain) | Video downloads. |
| **Deno** (`deno.exe`) | MIT | JavaScript runtime that yt-dlp uses for YouTube. |

### Microsoft Visual C++ runtime

The Windows installer and the Portable ZIP include `msvcp140.dll` and `msvcp140_1.dll` from the
Microsoft Visual C++ 2015-2022 runtime (version 14.44.35211, x64), next to the
`vcruntime140.dll` and `vcruntime140_1.dll` that come with the bundled Python. They are Microsoft's
files, unmodified (each carries a valid Microsoft Authenticode signature), copied app-local into
`python\` as Microsoft's documentation allows:

- "It's also possible to directly install the Redistributable DLLs in the application local
  folder": https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files
- the Visual Studio 2022 redistribution list, "Visual C++ Runtime Files": you may copy and
  distribute these files, unmodified, as a part of the installation package of your program,
  subject to the Visual Studio licence terms:
  https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution

Microsoft's page also says that distributing these files is limited to licensed Visual Studio
users; whoever publishes a release is responsible for holding that licence. The files are taken
from the `msvc-runtime` 14.44.35112 wheel on PyPI (a repackaging of Microsoft's files), pinned by
URL, size and SHA-256 in `platform/windows/build-deps.json`. They are only used by the Windows
builds that ship the bundled Python; the Microsoft licence terms apply to them, not the BSD
licence of this project.

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

Each ships its full license text in its `site-packages` folder. Packages marked LGPL or
MPL-2.0 are shipped unmodified, as their own packages, with their source linked below.

- **faster-whisper** — MIT
- **ctranslate2** — MIT
- **numpy** — BSD-3-Clause (its wheels also carry parts under 0BSD, MIT, Zlib and CC0-1.0; the texts
  are in the package)
- **tokenizers / huggingface-hub** — Apache-2.0
- **sherpa-onnx** — Apache-2.0 (speaker diarization runtime)
- **onnxruntime** — MIT (Microsoft; runs the sherpa-onnx and Silero VAD models)
- **pywhispercpp** (whisper.cpp bindings) — MIT
- **arabic-reshaper** — MIT (joins Arabic-script letters in PDF output)
- **python-bidi** — LGPL-3.0-or-later, shipped unmodified as its own package and
  imported at runtime (right-to-left line order in PDF output); its compiled
  extension wraps the `unicode-bidi` Rust crate (MIT / Apache-2.0). Source:
  https://github.com/MeirKriheli/python-bidi (also on PyPI). To use another
  build, replace the `bidi` folder in the app's `site-packages`
  (`python\Lib\site-packages\bidi` in the Windows installer and Portable ZIP).
- **pystray** — LGPL-3.0-or-later, shipped unmodified as its own package and imported at runtime
  (the system-tray icon, `app/widgets/tray.py`). Source: https://github.com/moses-palmer/pystray
  (also on PyPI). To use another build, replace the `pystray` folder in the app's `site-packages`
  (`python\Lib\site-packages\pystray` in the Windows installer and Portable ZIP). The macOS app is
  built from this repository (`platform/macos/build_mac.sh`), so a modified copy can be built in.
- **python-vlc** — LGPL-2.1-or-later, shipped unmodified as the single module `vlc.py` and imported
  at runtime (the media preview in the transcript viewer, `app/dialogs/transcript_viewer.py`). It is
  only a binding: VLC itself is not bundled, the app uses a VLC the user has installed. Source:
  https://github.com/oaubert/python-vlc (also on PyPI). To use another build, replace `vlc.py` in the
  app's `site-packages` (`python\Lib\site-packages\vlc.py` in the Windows installer and Portable ZIP);
  the macOS app is rebuilt as described above.
- **PyAV (`av`)** — BSD-3-Clause for the binding itself. Its wheels bundle their own shared FFmpeg
  libraries (libavcodec, libavformat, libavutil, libavfilter, libswscale, libswresample), in
  `site-packages\av.libs` on Windows and inside the package on macOS; the library reports its license as
  LGPL version 3 or later. The wheels also carry the codec libraries FFmpeg is linked against,
  among them libx264 and libx265 (GPL-2.0-or-later), libvpx, libwebp, libopus and dav1d (BSD-style),
  SVT-AV1 (BSD-3-Clause-Clear with the AOMedia patent license), LAME (LGPL-2.0-or-later),
  opencore-amr (Apache-2.0), oneVPL (MIT) and libiconv (LGPL-2.1-or-later), and the MinGW runtime
  (GPL-3.0 with the GCC Runtime Library Exception; winpthreads is MIT). This is a second FFmpeg copy,
  separate from the `ffmpeg.exe` above, used to decode audio for faster-whisper; the app as a whole is
  distributed under GPL terms because of the `ffmpeg.exe` build (see above). Source and build recipe:
  https://github.com/PyAV-Org/PyAV and https://github.com/PyAV-Org/pyav-ffmpeg. To use another build,
  replace the `av` and `av.libs` folders in the app's `site-packages`.
- **certifi** — MPL-2.0 (the CA certificate bundle `requests` uses for HTTPS, derived from Mozilla's
  root list). Shipped unmodified; source: https://github.com/certifi/python-certifi.
- **tqdm** — MPL-2.0 and MIT (progress bars of model downloads, a dependency of faster-whisper and
  pywhispercpp). Shipped unmodified; source: https://github.com/tqdm/tqdm.
- **Pillow** — MIT-CMU (HPND-style); **requests**, **watchdog** — Apache-2.0; **reportlab** —
  BSD; **sv-ttk**, **tkinterdnd2**, **python-docx** — MIT. See each package's bundled
  LICENSE for the exact text.

## On-demand optional packages (not bundled)

Some features install their packages from PyPI on first use instead of
shipping in the base installer, keeping the default install small. Each
installs only if you opt into that specific feature.

- **stable-ts** (word-timing refinement, MIT) and **openai-whisper** (the original Whisper backend,
  MIT) with **PyTorch / torchaudio** (BSD-3-Clause), which they pull in. The Windows build
  deletes any copy of them from the installer tree (`build_embed_installer.bat`), none of them is in
  `requirements.txt`, and `core/optional_deps.py` downloads them when the feature is first used.
  (PyTorch is also what the optional NVIDIA ASR and voice-cloning features download.)
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
- The two **speaker-diarization models** in `bin/diarization/` are bundled in the Windows
  installer, the Portable ZIP and the macOS app (`platform/windows/build-deps.json` pins them):
  - `segmentation.onnx`: **pyannote segmentation 3.0**, MIT. The license is declared in the model
    card of the original, https://huggingface.co/pyannote/segmentation-3.0 (that page is gated: access
    asks for contact details); the app ships the ONNX conversion made by the
    sherpa-onnx project, https://huggingface.co/csukuangfj/sherpa-onnx-pyannote-segmentation-3-0,
    a derivative that stays under the same MIT license.
  - `embedding.onnx`: **3D-Speaker CAM++ (English, VoxCeleb, 16 kHz)**, Apache-2.0. The 3D-Speaker
    project (https://github.com/modelscope/3D-Speaker) is Apache-2.0 and the ModelScope page of the
    model, `iic/speech_campplus_sv_en_voxceleb_16k`, states "Apache License 2.0"; the app ships the
    ONNX conversion from https://huggingface.co/csukuangfj/speaker-embedding-models. The license
    covers the weights; the VoxCeleb data they were trained on is licensed separately by its authors.
  Both run through the sherpa-onnx runtime (Apache-2.0), fully offline.

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
