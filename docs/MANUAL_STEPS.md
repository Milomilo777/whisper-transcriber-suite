# Manual Steps — what the human still does

This file lists the **specific actions you (the user) may need to take by hand**, separately from anything the implementing sessions can do. It is not a roadmap and not an acceptance plan; it is a short, current, human-facing checklist.

If you complete everything here, the project's current state has nothing pending that requires human judgement. Future work is then a choice (which Phase to ship next), not an obligation.

---

## A. Repository hygiene — done by the orchestrator, no human action needed

You don't have to do these. They're listed so you know what was cleaned up.

- ✅ `claude/determined-hermann-7dcfa7` branch deleted from GitHub
- ✅ Stale local tracking ref removed
- ✅ `origin/HEAD` now points at `master`
- ✅ A tag `archive/phase-0-baseline` was created on `50a4fea` (the historical end-of-life of the deleted branch) and pushed, so the commit stays named for posterity
- ✅ Local has exactly one branch (`master`), one tag (`archive/phase-0-baseline`), one worktree (the repo itself)

If you ever want to inspect the historical branch:

```
git log archive/phase-0-baseline    # see Phase 0 baseline as it was published
git show archive/phase-0-baseline   # see the tag annotation
```

---

## B. Optional: tag the current `master` as `v0.5.0`

The current `master` (`7bda654`) is a coherent release-able snapshot:

- All Phase 0, 1a, 1b, 2-oTranscribe, 2a, 3a code on board
- 137 tests passing, 77% coverage on `core/`
- PyInstaller build pipeline working with `build.bat`
- Full documentation suite

You asked **not to release yet**, so this is parked. If you change your mind later:

```
git tag -a v0.5.0 -m "Foundation snapshot: offline transcription + downloader + integrations"
git push origin v0.5.0
```

That's it. GitHub will surface it under `Releases` on the repo home.

---

## C. None of the original "Known limitations" need human work

When the project was first audited, the README listed:

- `yt-dlp --update` runs unconditionally before every download
- `ffprobe` is called from PATH, not from `bin/`
- No theming, drag-and-drop, folder watcher, model picker
- No tests, no CI

**Every one of those was either fixed (sessions 0-5) or moved into the roadmap with a clear plan.** The README "Known limitations" section was rewritten this session (Session 6) to reflect what's actually remaining. Read it for the current truth.

The current limitations are all design choices or out-of-scope features waiting on a Phase to be picked. None are user-blocking; the app runs and produces good output today.

---

## D. If you want to change the active Whisper model right now (no UI picker yet)

The model picker is Phase 2b (deferred). Until then:

1. Quit the app
2. Open `%LOCALAPPDATA%\WhisperTranscriberSuite\config.json` in a text editor
3. Edit the `model_path` field to point at your preferred model folder (must be a faster-whisper / CTranslate2-format folder; e.g. an extracted `models--Systran--faster-whisper-medium`)
4. Optionally also edit the `model` object's `url` and `md5` fields so `ensure_model` knows where to refetch it from
5. Save and restart the app

If the path is unreachable on startup, the new fallback in Phase 0 will substitute `%LOCALAPPDATA%\WhisperTranscriberSuite\Cache\models\<name>` and log a warning — your edit will be honored once a valid folder is at that path.

---

## E. If you want to switch theme

`View → Theme → Light / Dark / System` from the menubar. The setting persists in `config.json` (`theme` key).

---

## F. If you want to enable `auto_update_yt_dlp` or `auto_transcribe_after_download`

Open `%LOCALAPPDATA%\WhisperTranscriberSuite\config.json` and set:

```json
{
  "auto_update_yt_dlp": true,
  "auto_transcribe_after_download": true
}
```

Restart. The auto-update checks GitHub at most once per 24 hours and never blocks a download (Phase 0 fix). Auto-transcribe-after-download enqueues a transcription job with the detected source language as a hint.

---

## G. If something goes wrong

- App won't start: open `%LOCALAPPDATA%\WhisperTranscriberSuite\logs\app.log` — Phase 1.3 set up rotation; the most recent run is at the bottom
- Config got corrupt: it's been renamed to `config.json.corrupt` next to the live file, defaults restored automatically (Phase 0 C2 fix)
- PyInstaller build broken: run `build.bat verify` from the repo root to see which file is missing; exit codes documented in `docs/BUILD.md`

---

## Summary

Nothing here blocks you. The one open human decision is **which Phase to implement next** (or whether to tag `v0.5.0` first) — see [ROADMAP.md](ROADMAP.md) Progress snapshot for the candidates. Sections D–G above cover the few settings the GUI doesn't yet expose, in case you want to tweak them by hand.
