# Homebrew formula for Whisper Project (macOS, and Linuxbrew).
#
# This is a PERSONAL-TAP formula (not homebrew-core): it builds a venv and
# pip-installs the deps at install time rather than vendoring every Python
# dependency as a pinned `resource` block. That keeps it maintainable for a
# small project; homebrew-core would require the full vendored-resource
# treatment.
#
# Requires the repo (or a release source tarball) to be PUBLIC — a Homebrew
# tap can't reach a private repo. Publish it to a tap, e.g.
#   github.com/translation-robot/homebrew-tap  →  Formula/whisper-project.rb
# then users run:
#   brew install translation-robot/tap/whisper-project
#
# At each release, update `url` to the new tag and refresh `sha256`:
#   curl -fsSL <url> | shasum -a 256
class WhisperProject < Formula
  include Language::Python::Virtualenv

  desc "Offline Whisper transcription + yt-dlp/ffmpeg downloader & video tiling"
  homepage "https://github.com/Milomilo777/whisper-transcriber-suite"
  url "https://github.com/Milomilo777/whisper-transcriber-suite/archive/refs/tags/v1.3.6.tar.gz"
  sha256 "PUT_SHA256_OF_THE_TARBALL_HERE"
  license "BSD-3-Clause"

  depends_on "ffmpeg" # provides ffmpeg, ffprobe AND ffplay (Video Tiling)
  depends_on "python@3.12"
  depends_on "python-tk@3.12" # Tk 8.6 for the desktop GUI

  def install
    # virtualenv_create (not a raw `python -m venv`) builds the venv against
    # python@3.12's stable opt-path AND registers it for Homebrew's relink
    # on a python revision bump — so `brew upgrade python@3.12` doesn't orphan
    # the interpreter / dangle the native wheels (faster-whisper, ctranslate2,
    # sherpa-onnx). We still pip-install from PyPI (fine for a tap; not core).
    venv = virtualenv_create(libexec/"venv", "python3.12")
    system venv.root/"bin/pip", "install", "--upgrade", "pip", "wheel"
    system venv.root/"bin/pip", "install", "-r", "requirements.txt"
    system venv.root/"bin/pip", "install", "yt-dlp"

    # Install the app source under libexec and expose two entry points.
    libexec.install Dir["*"]
    (bin/"whisper-project").write <<~SH
      #!/bin/bash
      exec "#{libexec}/venv/bin/python" "#{libexec}/gui.py" "$@"
    SH
    (bin/"whisper-transcribe").write <<~SH
      #!/bin/bash
      exec "#{libexec}/venv/bin/python" "#{libexec}/gui.py" transcribe "$@"
    SH
  end

  test do
    # The CLI prints usage and exits cleanly with --help.
    assert_match "transcribe", shell_output("#{bin}/whisper-project --help")
    # ffmpeg brings ffplay, which the Video Tiling tab needs.
    assert_path_exists Formula["ffmpeg"].opt_bin/"ffplay"
  end
end
