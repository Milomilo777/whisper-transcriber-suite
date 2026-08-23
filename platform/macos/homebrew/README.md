# Homebrew install (macOS / Linuxbrew)

The cleanest install **once the repo is public**: Homebrew installs are not
quarantined (no Gatekeeper prompt), it pulls a native `python`, `python-tk`
and `ffmpeg` (which includes `ffplay`, so **Video Tiling works out of the
box**), and updates are just `brew upgrade`.

> This repo is currently private, so the tap below can't be reached by
> others yet. The formula is kept ready for when/if it's made public.

## Publishing the tap (maintainer, one-time)

1. Create a public repo named **`homebrew-tap`** under the account, e.g.
   `github.com/translation-robot/homebrew-tap`.
2. Copy `whisper-transcriber-suite.rb` into `Formula/whisper-transcriber-suite.rb` there.
3. At each release, point `url` at the new tag's source tarball and refresh
   the checksum:
   ```bash
   curl -fsSL https://github.com/<owner>/<repo>/archive/refs/tags/vX.Y.Z.tar.gz | shasum -a 256
   ```
   Put that hash in `sha256` and bump `url`.

## Installing (users)

```bash
brew install translation-robot/tap/whisper-transcriber-suite
whisper-transcriber-suite            # GUI
whisper-transcribe in.mp4 --formats srt json   # headless
```

`brew upgrade whisper-transcriber-suite` updates it later.

## Notes

- This is a **personal-tap** formula: it builds a venv and pip-installs the
  dependencies at install time. homebrew-core would instead require every
  Python dependency vendored as a pinned `resource` — heavier to maintain.
- The other supported macOS path (no Homebrew needed) is the source +
  `bash platform/macos/install.command` flow in `../README.md`. **Both are
  kept**; pick whichever fits.
