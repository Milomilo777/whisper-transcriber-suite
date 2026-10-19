# Spec review — flaws ranked by impact

**1. x86 VM results cannot answer "best on a phone-class CPU".**
Flaw: everything runs in a VM (almost certainly x86 server silicon), but the decision targets Android phones (ARM, big.LITTLE cores, NEON/dot-product SIMD, thermal throttling).
Why: relative speed of q5_1 vs q8_0, and of whisper.cpp vs sherpa-onnx vs Vosk, depends heavily on SIMD paths and memory bandwidth; rankings can flip between x86 and ARM. 4 threads on homogeneous VM cores ≠ 4 threads on big.LITTLE. This alone can make the recommendation wrong.
Fix: run the top 2–3 engine/model/quant combos on at least one physical mid-range Android device (adb + NDK binary or Termux), same WAVs, 1 and 4 threads; until then the README must state the phone ranking is "unknown (x86 proxy only)".

**2. 40 utterances, "first 40", no statistics.**
Flaw: tiny sample, taken in dataset order, with no confidence intervals.
Why: WER differences of a few points between tiny/base/small will be within noise; dataset order can correlate with speaker or length. The recommendation may rest on luck.
Fix: use the full FLEURS fa_ir test split (a few hundred utterances — exact count unsure) or a seeded random sample of ≥300; report corpus-level WER plus a bootstrap 95% CI, and a paired per-utterance comparison for the top two engines.

**3. Normalisation biases the metric itself.**
Flaw: R1 maps ZWNJ (U+200C) to a space, and digits to ASCII without unifying digit-vs-word forms.
Why: ZWNJ sits *inside* Persian words; turning it into a space splits words, inflates WER denominators, and heavily penalises engines whose ZWNJ usage differs from FLEURS (engines differ a lot here). Separately, an engine that outputs "بیست‌وسه" while the reference has "۲۳"→"23" is scored wrong even though it is correct (I am unsure whether FLEURS fa references spell numbers as digits or words — either way the two forms must be unified).
Fix: delete ZWNJ instead of splitting (and publish both variants once as a sensitivity check); add a number-word↔digit normalisation step applied to ref and hyp; re-run the broken-test requirement against these.

**4. Unfair measurement harness: in-process vs subprocess, unpinned decoding, no warm-up/repeats.**
Flaw: Vosk and sherpa-onnx run in the bench Python process, whisper.cpp runs as a CLI subprocess; "peak RSS of the engine process" therefore measures different things. Decoding flags are not pinned beyond `-l fa` (whisper.cpp beam/greedy/temperature, Vosk and sherpa settings are unspecified). No warm-up, no repetition, no CPU pinning.
Why: RSS for in-process engines includes Python/numpy and previously loaded models; ONNX session init can land in the first file; unpinned decoding changes WER between runs; single-run wall times on a shared VM are noisy.
Fix: wrap *every* engine in its own subprocess runner so RSS (child `ru_maxrss`) and timing are measured identically; pin and record the full flag set per engine in results.json; discard one warm-up file; ≥3 timing repeats per file, report median; pin CPU affinity and record core count/governor.

**5. Metric definition: "mean WER" is ambiguous and misleading on short clips.**
Flaw: R6 says "mean WER" over files.
Why: FLEURS utterances are short; a 1-word error in a 3-word line counts as 33%. Mean-of-ratios overweights short lines and differs from standard corpus WER.
Fix: headline metric = aggregate WER (Σ edits / Σ ref words) and aggregate CER; keep per-utterance median as secondary; make summarize.py compute exactly that.

**6. Asymmetric / incomplete model coverage.**
Flaw: whisper.cpp gets tiny/base/small; sherpa-onnx only tiny/base; Vosk only the small fa model (a larger Vosk Persian model exists — exact name unsure); no long-form or noisy condition.
Why: the app handles "voice notes and recordings" — minutes-long, noisy, spontaneous audio. FLEURS is short read speech; nothing tests long-form drift, hallucination/repetition, or streaming behaviour, where these engines differ most.
Fix: match size tiers across engines or justify each gap; add one long test (e.g., concatenated FLEURS or a multi-minute public-domain recording) plus a noisy public fa set if one exists without login (unsure which corpora qualify); record failures honestly per R3.

**7. Timing environment not controlled.**
Flaw: no check for other VM load, no fixed governor, thread counts 1 and 4 regardless of actual core count.
Why: RTF on a noisy shared VM is not reproducible; the supervisor rerunning gets different numbers.
Fix: pin to N physical cores, record `nproc`, run benchmarks in a quiet window, repeat the whole run twice and report both; flag variance in SUMMARY.

**8. Quantisation coverage/detail.**
Flaw: only q5_1 and q8_0 for whisper.cpp; the phone-relevant sweet spot may be elsewhere; the quantize step may leave some tensors unquantized, so "q8_0" is not uniformly 8-bit.
Why: size/quality trade-offs drive the app decision; mislabelled quant misleads.
Fix: record measured on-disk size per file (R6 already does), note which tensors were quantized if the tool reports it, and justify the two chosen quants as covering the plausible range — or add q4 if build time allows.

**9. The "Android-first" recommendation lacks an integration axis.**
Flaw: recommendation rests on WER/RTF/RAM only.
Why: for an app, maintained Android bindings/AAR, NDK build effort, and binary size matter as much as 2 WER points.
Fix: add columns "Android bindings available? (link)" and "integration notes" to SUMMARY.md, "unknown" where unmeasured, and require the recommendation to address them.

**10. Minor:** no sanity check that hypotheses are non-degenerate (an engine returning empty strings yields WER 1 but "passes"). Fix: assert non-empty output on ≥1 known file and print two sample ref/hyp pairs in SUMMARY.md.