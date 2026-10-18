# Whisper Transcriber Suite, installed from source on Linux the way CI does it (.github/workflows/ci.yml, ubuntu job):
# requirements.txt plus the test tools from AGENTS.md. Everything the audit may need is fetched here, because the scan
# has no network.
#
# What is deliberately NOT installed, to keep the image small and the build fast:
#  - torch / transformers / stable-ts (optional features "alignment" and "nvidia_asr"; the app installs them on demand
#    into a user folder, and requirements.txt no longer pulls them: the CUDA wheels alone are several GB);
#  - any Whisper model (the app downloads models from the Hugging Face Hub on first use; the hermetic tests use stubs);
#  - the PyInstaller / Inno Setup / macOS packaging tools (Windows and macOS only).
# The desktop GUI needs a display; xvfb-run provides a virtual one, so Tk code can be exercised headless.
FROM python:3.12-bookworm
ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUTF8=1 \
    WHISPER_OFFLINE_TESTS=1

# The official python image is built with Tk, so tkinter imports without python3-tk (which would add Debian's own
# Python 3.11). xvfb + xauth: virtual display for the Tk code. ffmpeg + ffprobe: the app finds them on PATH on Linux
# when bin/ has none. libportaudio2: sounddevice (Live tab, core/recorder.py) loads it. libgl1 + libglib2.0-0: loaded by
# image and media wheels. cmake: pywhispercpp builds from source when no wheel matches.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates git xvfb xauth ffmpeg libportaudio2 libgl1 libglib2.0-0 cmake pkg-config \
    && rm -rf /var/lib/apt/lists/*

# scanner contract: the checkout lives inside the image, at /src
COPY . /src
WORKDIR /src

# Runtime dependencies (no CUDA torch is pulled; see above), then the test tools named in AGENTS.md, then yt-dlp: the
# release builds bundle it in bin/, which is not in the repository, so a source install uses the one on PATH.
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install pyright pytest pytest-timeout responses hypothesis \
    && pip install yt-dlp

# pyright downloads its Node.js runtime on first use; do it now because the scan has no network.
RUN pyright --version

# Run the hermetic suite so you know the image works, but do not let a failing test abort the build. tests/smoke needs
# a real model and network and skips itself. The per-test timeout comes from pyproject.toml (120 s); the outer timeout
# keeps the build bounded. Tk tests run under a virtual display.
RUN (timeout 2400 xvfb-run -a python -m pytest tests/ --ignore=tests/smoke -q -p no:cacheprovider \
      || echo "WARNING: pytest reported failures or hit the build time limit")
