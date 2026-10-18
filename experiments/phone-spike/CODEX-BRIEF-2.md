# BRIEF 2 for Codex: integrate and debug the Persian on-device ASR benchmark (phone spike)

Same worktree and rules as before (see `experiments/whisper-lite-android/CODEX-BRIEF-1.md`, "Hard rules"):
relative paths only, nothing outside this worktree, no secrets, git is not writable here (leave your files; the
supervisor commits), Windows PowerShell quoting care. Work ONLY in `experiments/phone-spike/` plus REVIEW.md at the
worktree root.

## Context
Another agent (Jules, on a Linux VM) wrote `experiments/phone-spike/`: a benchmark harness that compares small
speech-to-text engines for PERSIAN on a CPU (Vosk small fa, whisper.cpp tiny/base/small q5_1/q8_0, sherpa-onnx
Whisper tiny/base int8), on FLEURS fa_ir, reporting WER/CER/RTF/RAM. Its delivery came through chat replies, so
files may be incomplete or inconsistent. The requirements are `SPEC.md` (R1-R8) and `SPEC-amendment-1.md` (A1-A7,
wins where they differ); `inputs-critique-kimi-k3.md` explains why. The harness must later run on this Windows PC
too (on private recordings that never leave it), and on a phone via Termux.

## Do NOT
Download models, datasets or packages, build whisper.cpp, or run the real benchmark (no network, low RAM here).
Unit tests and a fake engine only.

## Tasks
1. Read every file; list what is missing or broken against R1-R8 and A1-A7 (imports that do not resolve, functions
   named in one file and absent in another, Linux-only code such as /proc paths or `resource` without a Windows
   fallback, shell scripts without a Python equivalent where Windows needs one).
2. Fix them so that `python -m pytest experiments/phone-spike/tests -q` passes on this Windows machine with only the
   standard library + pytest (engines that need vosk/sherpa_onnx/whisper.cpp must import lazily and be skipped or
   reported as unavailable, never crash the bench).
3. Tests (each must fail on a broken implementation; the supervisor runs mutants): `normalize_fa` (every R1 rule),
   Persian number words -> digits (A2), ZWNJ delete vs space variants, `wer`/`cer` hand-computed cases and empty
   reference, aggregate WER = sum edits / sum words (A1), bootstrap CI with a fixed seed is reproducible and brackets
   the point estimate, `summarize.py` builds SUMMARY.md from a small JSON fixture (every number traceable),
   `bench.py` + `runner.py` with the fake engine end to end on two tiny generated WAV files (child process per
   engine, warm-up skipped, failed engine recorded with its error, empty/identical hypotheses marked FAILED per A5).
4. Make `README.md` accurate for Windows and Linux (exact commands), keep the caveats (VM is not a phone).
5. Write `REVIEW.md` at the worktree root: per requirement R1-R8, A1-A7 DONE / NOT DONE / NOT VERIFIABLE HERE (+ why),
   the bugs you fixed, test count and the pytest summary line, and the list of files you changed or added.
