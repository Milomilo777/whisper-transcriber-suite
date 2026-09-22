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

* **Real microphone: originally reported as NOT verified end-to-end,
  based on a claim that was wrong.** This section originally stated
  `mic_available() == False` (`sounddevice not installed`) on this
  machine. That claim was false — the original author almost certainly
  checked a different Python interpreter than the one this app actually
  runs under. See the "Double-checked (mimo-v2.5)" section below for
  the correction and the real end-to-end mic verification that was run
  once the mistake was caught.
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

### Double-checked (mimo-v2.5):

- **Mic-availability correction confirmed independently**: `mic_available()`
  is `True` on this machine (also `loopback_available() == True`); the
  original handoff's claim was wrong. Root-caused: the original session
  almost certainly checked a different Python interpreter than the one
  this app runs under.
- **Real end-to-end mic capture now actually run** (not just claimed):
  a real `LiveSession(mode="mic", on_meter=...)` was started against the
  real microphone for 3 seconds. Result: 45 real `on_meter` calls,
  92160 bytes of real PCM at 16 kHz, a real WAV file written, and
  `pcm_to_rms` on the tail returned a small non-zero value (~0.0005,
  consistent with quiet room ambient noise) — proof the meter tap
  receives genuine captured audio, not synthetic data, all the way from
  the recorder's capture thread through to the pure helper functions the
  widget itself uses.
- **License judgment**: sound. FFT band grouping (16 log-spaced bands),
  peak-hold caps, RMS strip, idle-baseline behavior, and the
  teal-to-amber color scheme are all genuinely different from
  TranscriptionSuite's GPL-3.0 `AudioVisualizer.tsx` (linear bins,
  no peak-hold, waveform overlay, 3-layer sine idle, cyan-to-magenta).
  No line-for-line porting found.
- **Threading/gating**: sound. Capture-thread tap swallows/logs
  exceptions and never touches the widget; `push_frames`/`_take_pending`
  share one lock; all canvas work runs on the Tk thread via a gated
  `after()` tick; the redraw loop starts once on session start and stops
  on every exit path (`_started`/`_start_failed`/`_stopped`/
  `stop_live_session`).
- **One real bug found and fixed**: `_on_destroy` set `_after_id = None`
  directly instead of calling `self._cancel()`, leaving a pending Tk
  `after()` callback uncancelled when the widget's frame is destroyed
  mid-tick. The originally suggested failure scenario (a `TclError` from
  `winfo_width()` propagating into a logged error) does not actually
  happen — `_tick()` checks `self._active` and returns before reaching
  `_draw()`, so the stray callback is a harmless no-op, not a crash or a
  spurious log line. The underlying hygiene issue was still real and
  worth fixing for consistency with the existing `_cancel()` helper;
  fixed as a one-line change. pyright `app core`: 0/0/0 after the fix;
  `tests/app/test_audio_visualizer.py`: 13/13 passed; full hermetic
  suite re-run after the fix (see commit for result).

Result: one minor real defect found and fixed (dangling `after()`
callback on destroy); the mic-availability gap this handoff originally
left open is now closed with a real hardware run.
