# Work board and RESUME

2.4.0 shipped on 2026-11-15. 2.4.1 is the next patch release.

## Changes on `master`

- CUDA transcription adapts batch size to available VRAM and can reduce load as the GPU approaches its temperature limit. Mixed-language transcription recovers dropped speech and preserves cue languages in JSON.
- Transcript exports can finish when decoded cues exceed the audio duration. The Download tab shows active downloads, and Kokoro retains unknown words and applies number rules by voice language.
- Assistants can use a local stdio MCP server with explicitly allowed media. Windows CI runs in parallel shards, and packaging checks handle Unicode paths and temporary-directory aliases.

See [Unreleased in the changelog](CHANGELOG.md#unreleased) for the full list.
