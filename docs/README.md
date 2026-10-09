# Documentation index

A short reading order for new contributors. Every doc in this folder
fits into one of five buckets.

## Start here

1. [INSTALL.md](INSTALL.md) — end-user install instructions
2. [BUILD.md](BUILD.md) — how to produce the EXE / installer locally
3. [ARCHITECTURE.md](ARCHITECTURE.md) — how the app is wired together
4. [CONFIG.md](CONFIG.md) — every config key, what it does, default value; usage statistics and the table of every network connection the app makes

## Reference

- [CHANGELOG.md](CHANGELOG.md) — version history
- [COMPARISON.md](COMPARISON.md) — compared with Subtitle Edit, Vibe, Buzz, noScribe and aTrain, with a source for every fact
- [DECISIONS.md](DECISIONS.md) — why non-obvious design choices were made
- [MANUAL_STEPS.md](MANUAL_STEPS.md) — release-time human checklist
- [RELEASE_PROCESS.md](RELEASE_PROCESS.md) — how to ship a new version
- [TESTING.md](TESTING.md) — how to run the tests (hermetic suite vs. smoke) and the app
- [architecture-diagrams.md](architecture-diagrams.md) — Mermaid + SVG diagrams, a visual companion to ARCHITECTURE.md

## Per-feature

- [auto-subtitles-feature.md](auto-subtitles-feature.md) — the auto-subtitles feature
- [CLOUD_STT.md](CLOUD_STT.md) — optional Gemini-API cloud backend (paste a key)
- [CLOUD_STT_GOOGLE.md](CLOUD_STT_GOOGLE.md) — optional Google Cloud Speech-to-Text backend (service-account JSON, batch mode)
- [SERVER.md](SERVER.md) — optional local-network / web server mode (`gui.py serve`)
- [LIVE.md](LIVE.md) — the Live tab: microphone / system-audio transcription as it happens
- [SUBTITLED_VIDEO.md](SUBTITLED_VIDEO.md) — "Make subtitled video": a link to `<title>-subbed.mp4` in one queued job (download, transcribe, burn)
- [DENOISE.md](DENOISE.md) — optional adaptive audio denoise pre-process (ffmpeg-only, measures before it filters)
- [WORK_OFFLINE.md](WORK_OFFLINE.md) — Work offline: the status line, the Network log, Verify offline now, and how to check the app yourself
- [SAMPLE_CLIP.md](SAMPLE_CLIP.md) — the bundled "Try it now" sample clip: source, licence, speaker credit
- [COMPARISON.md](COMPARISON.md) — sourced comparison with similar apps
- [integrations/](integrations/) — third-party service integrations (SMTV, oTranscribe)
- [evaluations/](evaluations/) — model / backend evaluation writeups
- [tutorial/](tutorial/) — end-user install-and-use walkthrough

## Release notes

Release notes for every version are on the
[GitHub Releases page](https://github.com/Milomilo777/whisper-transcriber-suite/releases);
the one-line-per-change history is [CHANGELOG.md](CHANGELOG.md).

## Development state

- [ROADMAP.md](ROADMAP.md) — high-level direction
