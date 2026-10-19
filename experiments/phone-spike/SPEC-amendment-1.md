UNATTENDED: never ask, decide and record. AMENDMENT to the phone-spike task (it wins over the first message where they differ):
A1 Data: a seeded random sample of 300 FLEURS fa_ir test utterances (seed 1234; all of them if fewer). Report
   AGGREGATE WER and CER (sum of edits / sum of reference words or characters) as the headline numbers, a
   bootstrap 95 % confidence interval (1000 resamples, seed 1234), the per-utterance median as a secondary
   column, and a paired per-utterance comparison of the best two engines.
A2 Normalisation: ZWNJ is DELETED (not turned into a space) in the headline metric; also report WER with
   ZWNJ -> space as a sensitivity column. Persian number words vs digits: add a step that converts Persian
   number words up to 9999 to ASCII digits in both reference and hypothesis; unit tests for it.
A3 Fair harness: every engine runs in its own child process (one runner per engine); peak RSS = the child's
   ru_maxrss; one warm-up file is discarded; each timed file is run 3 times and the median is used; record
   the full decoding settings per engine in results.json (whisper.cpp: greedy, beam 1, temperature 0, no
   timestamps; Vosk and sherpa-onnx: their defaults, written out). Record nproc and the CPU governor if readable.
A4 Long form: also build one ~5-minute file by concatenating 25 sampled utterances with 0.5 s silence between
   them; report WER on it and whether any engine repeats or drops text (count repeated n-grams).
A5 Sanity: an engine whose hypotheses are empty or identical for all files is marked FAILED, not scored.
   SUMMARY.md shows two sample reference/hypothesis pairs per engine.
A6 SUMMARY.md also gets the columns "Android binding (link)" and "integration notes" ("unknown" if unknown).
A7 README states plainly that this VM is not a phone (CPU architecture, SIMD): speed rankings are an x86 proxy
   until the same runner is run on a real Android phone; add `phone/README.md` with exact steps to run the top
   two engine+model+quant combinations on a phone with Termux or adb (no app code needed).
Keep R1-R8 otherwise. Reply line when done unchanged.
