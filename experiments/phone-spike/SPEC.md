UNATTENDED: never ask questions and never wait for feedback; decide, record your decision in the README, continue.
This is a NEW task in this session; the earlier task is finished, ignore it.

NEW TASK: a 2-day measurement spike for a future phone app. Which small speech-to-text engine transcribes
PERSIAN (fa) best on a phone-class CPU? Measure, do not guess.

WHERE: only a new folder `experiments/phone-spike/` in this repo. Change no other file. Commit on a branch in
this session (no pull request). Do not commit audio or model files (add a `.gitignore` there for `data/`,
`models/`, `build/`). The repo is BSD-3-Clause: no GPL/AGPL code copied in.

ENGINES (all run on CPU in this VM):
E1 Vosk with `vosk-model-small-fa-0.42` (python `vosk`).
E2 whisper.cpp built from source at a pinned release tag, CLI with `-l fa`, models ggml tiny, base, small, each
   as q5_1 and q8_0 (quantize them yourself with the built `quantize` tool if no ready file exists).
E3 sherpa-onnx (python package) with the k2-fsa Whisper tiny and base int8 ONNX exports.
E4 reference only (not a phone candidate, run only if time allows): whisper.cpp large-v3-turbo q5_0.

DATA: the first 40 utterances of the FLEURS `fa_ir` test split from Hugging Face (`google/fleurs`, public).
Write 16 kHz mono WAV files to `data/` and `refs.tsv` (id, duration_s, reference text). If FLEURS cannot be
downloaded, stop and say so in the README; do not substitute data that needs a login.

REQUIREMENTS (the supervisor runs your tests against deliberately broken copies of your code; a test that does
not fail when its requirement breaks counts as missing):
R1 `normalize_fa(text)` in `metrics.py`: Unicode NFC; Arabic yeh/alef maksura -> Persian yeh (U+06CC), Arabic kaf ->
   keheh (U+06A9); remove harakat U+064B-U+065F and U+0670 and tatweel U+0640; ZWNJ U+200C -> one space;
   Persian and Arabic-Indic digits -> ASCII; remove punctuation (ASCII and ، ؛ ؟ « » ! .); lowercase Latin;
   collapse whitespace; strip.
R2 `wer(ref, hyp)` and `cer(ref, hyp)` in `metrics.py`: Levenshtein on words / on characters without spaces, after
   normalize_fa, divided by the reference length; an empty reference raises ValueError. Unit tests with
   hand-computed cases (substitution, insertion, deletion, ZWNJ, digits).
R3 `bench.py`: `python bench.py --audio-dir DIR [--refs refs.tsv] --engines LIST --threads 1,4 --out results.json`.
   Without --refs it still records hypotheses and speed, so the maintainer can rerun it on private recordings
   that never leave his PC. Per file and engine: hypothesis, wer, cer (if refs), audio seconds, wall seconds,
   RTF = wall / audio, peak RSS MB of the engine process, model size MB, and the error text if the engine failed
   (a failed engine is recorded, never silently dropped). Model load time is measured separately from RTF.
R4 Engines are plugins in one registry; a fake engine in the tests proves bench.py works without real models.
R5 `setup.sh`: installs pinned versions (`requirements.txt` with exact `==` pins), builds whisper.cpp at the
   pinned tag, downloads every model and prints its sha256; README lists those sha256 values.
R6 `results/fleurs-fa.json` (raw) and `results/SUMMARY.md`: one row per engine+model+quant with model size MB,
   mean WER, mean CER, median RTF at 1 and 4 threads, peak RAM MB, runtime licence, model licence. Every number in
   SUMMARY.md must be computable from the JSON; add `summarize.py` that builds SUMMARY.md from the JSON, and a
   test that runs it on a small fixture.
R7 README.md: hardware of this VM (lscpu model name, cores, RAM), exact commands to reproduce, caveats (FLEURS is
   read speech; real voice notes are noisier), and a RECOMMENDATION for an Android-first app: which engine+model
   +quant, with the numbers that support it and the main risk. Say "unknown" where you did not measure.
R8 `pytest experiments/phone-spike/tests -q` passes in this VM; paste its last line in the README.

WHEN DONE: commit on a branch in this session (no pull request) and reply with ONE line: DONE, the branch name,
and the WER + RTF(4 threads) of your recommended engine.
