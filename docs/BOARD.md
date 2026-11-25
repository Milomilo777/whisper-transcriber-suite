# Work board and RESUME

2.4.0 shipped on 2026-11-15. 2.4.1 is the next patch release.

## Changes on `master`

- CUDA transcription adapts batch size to available VRAM and can reduce load as the GPU approaches its temperature limit. Mixed-language transcription recovers dropped speech and preserves cue languages in JSON.
- Transcript exports can finish when decoded cues exceed the audio duration. The Download tab shows active downloads, and Kokoro retains unknown words and applies number rules by voice language.
- Assistants can use a local stdio MCP server with explicitly allowed media. Windows CI runs in parallel shards, and packaging checks handle Unicode paths and temporary-directory aliases.
- Files with several audio tracks let you choose the track, and damaged media can be salvaged into a repaired audio copy. The transcript viewer gains undo and redo, split and join, a paragraph reading view with paragraph export, and a side-by-side comparison of a re-run.
- Windows model downloads trust both the system certificate store and the bundled certificates. Failed exports are retried in a recovery folder, a slow media probe no longer stops a job, and worker failures report a classified cause.

- Optional installs keep a recovery record, engine checks run outside the window's thread, interrupted jobs resume from the saved decode position, and subtitle cues stay inside their speech chunks after long silences. The new interface text is translated into all supported languages.

## Before 2.4.1

- Done: edge-case tests for interruptions, full disks, hostile inputs, a 6.5-hour file, long subtitles, and the upgrade from 2.4.0.
- Open: a full CPU run with speaker detection, a server memory-growth check, and the macOS disk image on a supported macOS.

See [Unreleased in the changelog](CHANGELOG.md#unreleased) for the full list.
