# Contributing to Whisper Project

Thanks for considering a contribution. This is a Windows desktop app
(Python + Tkinter) that transcribes audio/video locally with Whisper
and downloads videos via `yt-dlp` — see [README.md](README.md) for
what it does and [PROJECT_INDEX.md](PROJECT_INDEX.md) for a fast,
generated map of the codebase.

## Before you start

- **Questions / ideas / "is this worth doing"** → open a
  [Discussion](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
  first. It's cheaper for everyone than a PR that turns out to be the
  wrong direction.
- **Bugs** → open an [issue](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
  with repro steps. The bug report template asks for the info that's
  actually needed to reproduce it.
- **New to the repo?** Look for issues labeled
  [`good first issue`](https://github.com/Milomilo777/whisper-transcriber-suite/labels/good%20first%20issue)
  or [`help wanted`](https://github.com/Milomilo777/whisper-transcriber-suite/labels/help%20wanted).

## Development setup

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Python 3.11+ on Windows. The app also runs on Linux (headless `gui.py
serve`) and there's early macOS support (`platform/macos/`) — see
[docs/CROSS_PLATFORM_ROADMAP.md](docs/history/CROSS_PLATFORM_ROADMAP.md)
history for what's shipped.

## Quality bar (checked on every push by CI)

```cmd
python -m pyright app core
python -m pytest tests/ --ignore=tests/smoke
```

Both must be clean before opening a PR:

- **pyright**: 0 errors, 0 warnings, 0 informations on `app/` and `core/`.
- **pytest**: the hermetic unit + integration suite (`tests/` minus
  `tests/smoke/`) must pass. `tests/smoke/` needs a real Whisper model
  + a real video file and isn't part of CI — see
  [docs/TESTING.md](docs/TESTING.md) if you want to run it locally.

New code needs new tests in the same style as its neighbors (every
`core/writers/*.py` and `core/integrations/*.py` module has a matching
`tests/` file — follow that pattern rather than inventing a new one).

## Code conventions

- **English only** in code, comments, docs, and commit messages — this
  keeps the codebase equally readable for every contributor and every
  AI coding assistant.
- Comments explain **why**, not what — the code should already say what
  it does. See [docs/DECISIONS.md](docs/DECISIONS.md) for the reasoning
  behind existing non-obvious choices before assuming something is an
  oversight.
- Match the existing module's style (docstring conventions, error
  handling patterns, logging) rather than introducing a new one.

## Pull requests

- Keep PRs small and focused — one logical change per PR is much
  easier to review than "also cleaned up X while I was in there."
- Describe **why**, not just what, in the PR description; link the
  issue it closes if there is one.
- Draft PRs are welcome if you want early feedback before finishing.

## Where things live

- [docs/BUILD.md](docs/BUILD.md) — how the two shipped Windows
  binaries (Setup-Standard, Portable) are built.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — process model,
  threading, the worker-subprocess protocol.
- [docs/CONFIG.md](docs/CONFIG.md) — every user-facing config key.
- [docs/README.md](docs/README.md) — full documentation index.

## Code of Conduct

This project follows the
[Contributor Covenant](.github/CODE_OF_CONDUCT.md).

## License

Contributions are accepted under the project's
[BSD 3-Clause License](LICENSE).
