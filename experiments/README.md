# experiments/

Early prototypes for a possible phone companion app. Nothing here is part of the desktop app: it is not
imported by `app/` or `core/`, not packaged by any build spec, and not covered by the gate in `AGENTS.md`.
Each folder carries its own README with what was checked and what is still unverified.

| Folder | What | State |
|---|---|---|
| [phone-spike/](phone-spike/) | Offline benchmark harness for Persian speech recognition engines that could run on a phone | Tested with generated audio and fake engines only; no real measurements yet |
| [whisper-lite-android/](whisper-lite-android/) | Android audio module (decode and resample to 16 kHz mono) | Pure-JVM logic tested; the Android decoder part has not been compiled |

Run the harness tests with `python -m pytest experiments/phone-spike/tests -q`.
