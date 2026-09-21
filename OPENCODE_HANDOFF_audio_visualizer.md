# Handoff — Live-tab audio visualizer

## What was found in TranscriptionSuite

* Shallow-cloned `https://github.com/homelab-00/TranscriptionSuite` into
  `./.scratch-transcriptionsuite/` (deleted before commit, never committed).
* The live-audio graphic is `dashboard/components/AudioVisualizer.tsx`
  (React/Electron, Web Audio API — a different toolkit from this app's
  Tkinter/ttk, so this was always an adaptation, never a copy-paste).
* Real mode: frequency bars from `AnalyserNode.getByteFrequencyData`
  (bar count `min(bins, floor(width/6))` — a hundred-plus thin bars on
  desktop, linear bins, cyan→magenta gradient) plus a time-domain
  waveform overlay (`getByteTimeDomainData`, cyan stroke).
* Idle: 3-layer sine simulation (cyan/magenta/orange) gated by an
  `isActive` prop that stops the `requestAnimationFrame` loop when idle
  (issue #87); static 3-wave SVG when idle with no analyser.
* Used in `AudioNoteModal`, `FullscreenVisualizer`, `SessionView`.
* **`LICENSE` is GPL-3.0 (copyleft, restrictive). This repo is
  BSD-3-Clause.** Per the task instructions the TranscriptionSuite code
  was treated as inspiration only: no code was copied line-for-line.
  The inspiration source is noted in a comment in the new file.

## What was built here (and what changed)

New independent Tk widget: `app/widgets/audio_visualizer.py`
(`AudioVisualizer` + pure helpers `pcm_to_rms`, `compute_spectrum`,
`heights_for_levels`, `band_color`).

Real visible differences from their version:

* **16 log-spaced FFT bands** instead of ~width/6 linear bins.
* **Per-bar peak-hold caps** (slow-falling white ticks) — theirs has none.
* **Bottom RMS level strip** instead of their waveform overlay.
* **Idle is a single flat baseline** with the redraw loop stopped — not
  their 3-layer cyan/magenta/orange sine waves.
* Teal-to-amber bar gradient on a fixed dark slate strip (reads under
  both sv_ttk light/dark themes); theirs is cyan→magenta.

Wiring:

* `core/live.py`: added additive `LiveSession.on_meter`
  `(pcm_bytes, rate)` tap, called on the recorder's capture thread from
  `_on_frames`. Exceptions swallowed/logged so a broken meter can never
  kill a session. Transcription path untouched.
* `app/widgets/live_tab.py`: new "Input level" section between the
  controls and the transcript (transcript row moved 2→3, actions 3→4);
  `LiveSession(..., on_meter=_meter)` forwards capture-thread blocks to
  `viz.push_frames` (lock-only, Tk-safe); `_started` activates the
  redraw loop, `_start_failed`/`_stopped`/`stop_live_session` deactivate
  it. `push_frames` never touches widgets; all canvas work runs on the
  Tk thread via a gated `after(100ms)` tick (same gating idea as their
  `isActive`, reimplemented for Tk).
* Both PyInstaller specs gained `app.widgets.audio_visualizer` in
  hiddenimports (per repo rule for new `app/` modules).

## Verification

* **Real microphone: NOT verified end-to-end — stated plainly.**
  This machine reports `mic_available() == False`
  (`sounddevice not installed`) and `loopback_available() == False`, so
  no live capture path can start here and there was no real audio for
  the meter to chew on. I did not install audio backends or download a
  ~GB speech model in this session to force it. The tab degrades
  correctly (only "Microphone" offered; Start shows the "Cannot listen
  yet" error path, covered by existing tests).
* **Real Tk rendering: verified.** Built the actual `build_live_tab` on
  a real `Tk()` instance: visualizer present, active tick with synthetic
  220 Hz tone produced 36 canvas items (16 bars + 16 caps + grid/strip)
  with max level ≈ 0.7, idle state drew the flat baseline (2 items).
* **Unit tests:** new `tests/app/test_audio_visualizer.py` (13 tests:
  RMS/spectrum/heights/colors, `on_meter` forwarding + exception-safety,
  widget build/push/idle, tab embed + start/stop toggle). Widget tests
  share one module-scoped Tk root on purpose — one root per test tipped
  the full Windows suite into `TclError: tcl_findLibrary` late in the
  run while every file passed alone.
* **pyright `app core`: 0 errors, 0 warnings, 0 informations.**
* **Hermetic suite `tests/ --ignore=tests/smoke`: 2546 passed,
  1 skipped.** (One transient full-run-only Tk `TclError` in
  `test_search_dialog.py` appeared before the test-consolidation fix;
  after it the full suite is green.)

## Files changed

* `app/widgets/audio_visualizer.py` (new)
* `core/live.py` (`on_meter` hook)
* `app/widgets/live_tab.py` (Input-level section + wiring)
* `tests/app/test_audio_visualizer.py` (new)
* `whisper_project_onefile.spec`, `whisper_project_onedir.spec`
  (hiddenimports)
* `OPENCODE_HANDOFF_audio_visualizer.md` (this file)
