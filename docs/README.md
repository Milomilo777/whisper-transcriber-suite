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
- [DENOISE.md](DENOISE.md) — optional adaptive audio denoise pre-process (ffmpeg-only, measures before it filters)
- [COMPETITIVE_ANALYSIS_2026.md](COMPETITIVE_ANALYSIS_2026.md) — ecosystem survey (ASR models, cloud APIs, CJK specifics)
- [GAPS_AGAINST_PEERS_2026.md](GAPS_AGAINST_PEERS_2026.md) — companion product gap-analysis vs. peer apps
- [GAPS_VS_VOICE_PRO_2026.md](GAPS_VS_VOICE_PRO_2026.md) — gap-analysis vs. Voice-Pro (TTS / translation / dubbing)
- [integrations/](integrations/) — third-party service integrations (SMTV, oTranscribe)
- [evaluations/](evaluations/) — model / backend evaluation writeups
- [tutorial/](tutorial/) — end-user install-and-use walkthrough + video script

## Release notes

Newest first:

- [release-notes/RELEASE_NOTES_v1.7.0.md](release-notes/RELEASE_NOTES_v1.7.0.md)
- [release-notes/RELEASE_NOTES_v1.6.0.md](release-notes/RELEASE_NOTES_v1.6.0.md)
- [release-notes/RELEASE_NOTES_v1.5.0.md](release-notes/RELEASE_NOTES_v1.5.0.md)
- [release-notes/RELEASE_NOTES_v1.4.0.md](release-notes/RELEASE_NOTES_v1.4.0.md)
- see [release-notes/](release-notes/) for the full history (v0.7.0 through v1.7.0, 21 releases)

## Development state

- [SESSION_HANDOFF_NEXT.md](SESSION_HANDOFF_NEXT.md) — what to pick up next
- [SESSION_LOG.md](SESSION_LOG.md) — chronological session log
- [ROADMAP.md](ROADMAP.md) — high-level direction
- [roadmap/](roadmap/) — future feature research (one file per planned release)
- [history/](history/) — archived audits, freeze reviews, phase-acceptance plans, and superseded planning docs from earlier development cycles (see its own README for the index)
