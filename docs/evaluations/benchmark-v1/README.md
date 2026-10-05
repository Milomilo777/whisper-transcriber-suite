# Multilingual benchmark v1: local Whisper models per language

Status: complete. Eight languages x six models x five utterances, on CPU. The per-language
recommended models in `core/language_defaults.py` are derived from these numbers.

`tools/benchmark_multilingual.py` scores the app's local faster-whisper models per language on
public read speech, on CPU, through the app's own backend (`FasterWhisperBackend` loads the model,
then `transcribe_to_segments` decodes, the calls the transcription worker makes). It touches
neither the user's config file nor the user's model folder.

```
python tools/benchmark_multilingual.py --languages fa ar zh ja ru hi es tr --models tiny -n 5 --force
python tools/benchmark_multilingual.py --languages fa ar zh ja ru hi es tr --models base small -n 5 --resume
python tools/benchmark_multilingual.py --report
```

`--resume` keeps every (language, model) pair whose rows hold exactly the utterances the run
would pick and measures only the missing pairs, so a run split into several invocations (or cut
off) continues where it stopped. `--model-hub <folder>` loads models that are already downloaded
from an existing model folder, in place: nothing is downloaded into it or written to it, and a
missing model is an error. `--report` prints the tables below from `results.csv`.

## Data and licence

| | |
|---|---|
| Dataset | Google FLEURS, test split ([paper](https://arxiv.org/abs/2205.12446)) |
| Source | `https://huggingface.co/datasets/google/fleurs` (`data/<lang>/test.tsv`, `data/<lang>/audio/test.tar.gz`) |
| Licence | CC-BY-4.0 (dataset card front matter: `license: cc-by-4.0`) |
| Access | Public; no account, no token, not gated (checked 2026-10-05 through the Hub API) |
| Redistribution | Scores and utterance ids are published here under the licence; the audio is not copied into this repository (it is fetched into a cache outside the tree) |

Attribution: FLEURS is by Conneau et al., *FLEURS: Few-shot Learning Evaluation of Universal
Representations of Speech* (arXiv:2205.12446), released under CC-BY-4.0.

Common Voice was not used. Its Hugging Face dataset repositories now contain only a notice that
Common Voice is available exclusively through Mozilla Data Collective since October 2025 (the files
are gone, checked 2026-10-05), which is a separate site with its own terms. FLEURS needs none of
that.

## Language set

Eight of the app's user-base languages, chosen to cover the scripts that stress a recogniser or a
scorer differently:

| Code | FLEURS folder | Script / reason | Metric |
|---|---|---|---|
| fa | `fa_ir` | Arabic script, right to left; ZWNJ (half-space) handling matters | WER |
| ar | `ar_eg` | Arabic script, a large user group, diacritics in the output | WER |
| zh | `cmn_hans_cn` | CJK, no spaces | CER |
| ja | `ja_jp` | CJK, mixed scripts, no spaces | CER |
| ru | `ru_ru` | Cyrillic | WER |
| hi | `hi_in` | Devanagari (combining vowel signs) | WER |
| es | `es_419` | Latin, a high-resource baseline | WER |
| tr | `tr_tr` | Latin with the dotted/dotless I case-folding trap | WER |

Not in v1 (candidates for a later version): ko, th, vi, uk, pl.

## Models

The six multilingual models of the app's registry that matter on a local machine, with the
approximate download size from the registry (`approx_size_gb`):

| Slug | Download |
|---|---|
| `tiny` | about 0.075 GB |
| `base` | about 0.145 GB |
| `small` | about 0.5 GB |
| `medium` | about 1.5 GB |
| `large-v3-turbo` | about 1.6 GB |
| `large-v3` | about 3.0 GB (the app's default) |

## Method

- **Utterances.** Per language, the first five files of the test archive (a tar archive lists
  files in sorted-name order, so the pick is deterministic and only the start of the archive is
  downloaded) whose sentence id has not been taken yet. Different speakers reading the same
  sentence count once. Every model hears the same five utterances of a language.
- **Reference.** The raw (cased, punctuated) FLEURS transcription.
- **Decoding.** `device=cpu`, `compute_type=int8`, language set explicitly, app defaults otherwise
  (no VAD, no initial prompt, the app's repetition guard on). CTranslate2's sampling seed is set to
  0 before every utterance. This narrows, but does not remove, the run-to-run variation of
  Whisper's temperature fallback (which samples): a repeat of `tiny` on fa, hi and tr gave the
  same error count on 15 of 15 utterances, but three back-to-back decodes of one fallback-prone
  utterance in one process still gave three different transcripts. An utterance that falls back
  can therefore score differently in another run; an earlier unseeded pilot of `tiny` on Persian
  moved by 0.10 WER between two runs.
- **Normaliser** (identical for reference and hypothesis): Unicode NFC; case folding (Turkish
  `I`/`i` and `I with dot` mapped before folding); digits of any script to ASCII; Arabic marks and
  tatweel removed; Arabic yeh and kaf folded to the Persian letters; ZWNJ read as a word break;
  apostrophes and invisible format characters (zero-width space, LRM/RLM, BOM) deleted; all other
  punctuation and symbols removed; whitespace collapsed. Combining marks of Indic scripts are kept.
- **Metric.** Levenshtein distance (insert, delete, substitute = 1) with the standard library. WER on
  words; CER on characters without spaces for zh and ja. Corpus-level rate = total errors / total
  reference units (not the mean of per-utterance rates). An empty reference scores 0 for an empty
  hypothesis and 1 otherwise.
- **RTF** = decode seconds / audio seconds, measured around `transcribe_to_segments` (it includes
  consuming the segment generator), summed over the five utterances. Below 1.0 the model decodes
  faster than the audio plays. The first utterance of each model run includes CPU warm-up; model
  loading is not counted.
- **Machine class.** One 4-core / 8-thread x86-64 desktop CPU, 16 GB RAM, Windows 10, no GPU. The
  run was split into twelve invocations of a few minutes each (one model at a time, other programs
  open), resumed per (language, model) pair. Speeds on another CPU differ; only this CPU was
  measured.

## Results

Error rate: WER (words) or CER (characters), lower is better; it can exceed 1.0 when the model
adds many words. Units are reference words (WER) or characters (CER).

<!-- results:start -->
### fa

| Model | WER | Errors / units | Utterances | Audio | Decode | RTF |
|---|---|---|---|---|---|---|
| tiny | 0.903 | 112 / 124 | 5 | 74.9 s | 11.1 s | 0.15 |
| base | 0.911 | 113 / 124 | 5 | 74.9 s | 13.8 s | 0.18 |
| small | 0.589 | 73 / 124 | 5 | 74.9 s | 35.6 s | 0.48 |
| medium | 0.371 | 46 / 124 | 5 | 74.9 s | 99.5 s | 1.33 |
| large-v3-turbo | 0.234 | 29 / 124 | 5 | 74.9 s | 94.1 s | 1.26 |
| large-v3 | 0.218 | 27 / 124 | 5 | 74.9 s | 177.2 s | 2.37 |

### ar

| Model | WER | Errors / units | Utterances | Audio | Decode | RTF |
|---|---|---|---|---|---|---|
| tiny | 0.475 | 47 / 99 | 5 | 57.4 s | 6.2 s | 0.11 |
| base | 0.394 | 39 / 99 | 5 | 57.4 s | 11.1 s | 0.19 |
| small | 0.232 | 23 / 99 | 5 | 57.4 s | 31.4 s | 0.55 |
| medium | 0.111 | 11 / 99 | 5 | 57.4 s | 87.5 s | 1.52 |
| large-v3-turbo | 0.101 | 10 / 99 | 5 | 57.4 s | 90.5 s | 1.58 |
| large-v3 | 0.101 | 10 / 99 | 5 | 57.4 s | 146.5 s | 2.55 |

### zh

| Model | CER | Errors / units | Utterances | Audio | Decode | RTF |
|---|---|---|---|---|---|---|
| tiny | 0.364 | 71 / 195 | 5 | 60.8 s | 5.3 s | 0.09 |
| base | 0.231 | 45 / 195 | 5 | 60.8 s | 9.9 s | 0.16 |
| small | 0.118 | 23 / 195 | 5 | 60.8 s | 27.1 s | 0.45 |
| medium | 0.149 | 29 / 195 | 5 | 60.8 s | 77.5 s | 1.27 |
| large-v3-turbo | 0.046 | 9 / 195 | 5 | 60.8 s | 86.6 s | 1.42 |
| large-v3 | 0.046 | 9 / 195 | 5 | 60.8 s | 133.7 s | 2.20 |

### ja

| Model | CER | Errors / units | Utterances | Audio | Decode | RTF |
|---|---|---|---|---|---|---|
| tiny | 0.400 | 100 / 250 | 5 | 62.1 s | 5.5 s | 0.09 |
| base | 0.280 | 70 / 250 | 5 | 62.1 s | 10.3 s | 0.17 |
| small | 0.152 | 38 / 250 | 5 | 62.1 s | 28.1 s | 0.45 |
| medium | 0.116 | 29 / 250 | 5 | 62.1 s | 78.9 s | 1.27 |
| large-v3-turbo | 0.084 | 21 / 250 | 5 | 62.1 s | 87.4 s | 1.41 |
| large-v3 | 0.064 | 16 / 250 | 5 | 62.1 s | 142.2 s | 2.29 |

### ru

| Model | WER | Errors / units | Utterances | Audio | Decode | RTF |
|---|---|---|---|---|---|---|
| tiny | 0.205 | 18 / 88 | 5 | 64.4 s | 5.3 s | 0.08 |
| base | 0.159 | 14 / 88 | 5 | 64.4 s | 11.5 s | 0.18 |
| small | 0.045 | 4 / 88 | 5 | 64.4 s | 26.8 s | 0.42 |
| medium | 0.034 | 3 / 88 | 5 | 64.4 s | 81.5 s | 1.27 |
| large-v3-turbo | 0.000 | 0 / 88 | 5 | 64.4 s | 94.7 s | 1.47 |
| large-v3 | 0.011 | 1 / 88 | 5 | 64.4 s | 131.9 s | 2.05 |

### hi

| Model | WER | Errors / units | Utterances | Audio | Decode | RTF |
|---|---|---|---|---|---|---|
| tiny | 1.065 | 131 / 123 | 5 | 56.2 s | 19.2 s | 0.34 |
| base | 1.081 | 133 / 123 | 5 | 56.2 s | 11.3 s | 0.20 |
| small | 0.512 | 63 / 123 | 5 | 56.2 s | 56.2 s | 1.00 |
| medium | 0.325 | 40 / 123 | 5 | 56.2 s | 154.6 s | 2.75 |
| large-v3-turbo | 0.309 | 38 / 123 | 5 | 56.2 s | 108.7 s | 1.93 |
| large-v3 | 0.276 | 34 / 123 | 5 | 56.2 s | 250.6 s | 4.46 |

### es

| Model | WER | Errors / units | Utterances | Audio | Decode | RTF |
|---|---|---|---|---|---|---|
| tiny | 0.160 | 21 / 131 | 5 | 63.1 s | 5.4 s | 0.09 |
| base | 0.115 | 15 / 131 | 5 | 63.1 s | 28.1 s | 0.44 |
| small | 0.046 | 6 / 131 | 5 | 63.1 s | 32.0 s | 0.51 |
| medium | 0.031 | 4 / 131 | 5 | 63.1 s | 75.8 s | 1.20 |
| large-v3-turbo | 0.015 | 2 / 131 | 5 | 63.1 s | 88.0 s | 1.39 |
| large-v3 | 0.015 | 2 / 131 | 5 | 63.1 s | 133.1 s | 2.11 |

### tr

| Model | WER | Errors / units | Utterances | Audio | Decode | RTF |
|---|---|---|---|---|---|---|
| tiny | 0.358 | 34 / 95 | 5 | 70.1 s | 12.4 s | 0.18 |
| base | 0.295 | 28 / 95 | 5 | 70.1 s | 10.1 s | 0.14 |
| small | 0.200 | 19 / 95 | 5 | 70.1 s | 27.9 s | 0.40 |
| medium | 0.105 | 10 / 95 | 5 | 70.1 s | 81.2 s | 1.16 |
| large-v3-turbo | 0.084 | 8 / 95 | 5 | 70.1 s | 91.1 s | 1.30 |
| large-v3 | 0.063 | 6 / 95 | 5 | 70.1 s | 154.0 s | 2.20 |

### Recommended models

| Language | Fast | Best |
|---|---|---|
| fa | small | large-v3 |
| ar | small | large-v3-turbo |
| zh | small | large-v3-turbo |
| ja | small | large-v3 |
| ru | small | large-v3-turbo |
| hi | small | large-v3 |
| es | small | large-v3-turbo |
| tr | small | large-v3 |
<!-- results:end -->

What the tables show (counts from `results.csv`):

- `tiny` and `base` are not usable for Persian and Hindi (WER 0.90 or more). `small` stays under
  an error rate of 0.25 in six languages, but not in Persian (0.589) and Hindi (0.512).
- `large-v3-turbo` and `large-v3` are within five errors of each other in every language (tied in
  ar, zh and es; `large-v3-turbo` ahead in ru) while `large-v3-turbo` decodes 1.4 to 2.3 times
  faster on this CPU.
- `medium` makes more errors than `large-v3-turbo` in all eight languages, at a similar speed in
  seven of them (RTF 1.16 to 1.52 against 1.26 to 1.58) and slower in Hindi (2.75 against 1.93).
- Both CPU-heavy models stay slower than real time here: `large-v3-turbo` RTF 1.26 to 1.93,
  `large-v3` 2.05 to 4.46.

## How the recommended models are picked

- **Best** = the model with the lowest error rate for the language (a tie goes to the lower RTF).
- **Fast** = the most accurate of the models with a download of at most 0.5 GB (`tiny`, `base`,
  `small`; a tie goes to the lower RTF). The cap is on download size, not on speed: speed depends on
  the CPU and on hallucination loops, and on this CPU `small` decodes at 0.40 to 0.55 of the
  audio length in seven languages (1.00 in Hindi), right on any "twice as fast as real time"
  line, so a speed cap would flip with noise.
- `core/language_defaults.py` holds these picks (`recommended_model(language, mode)`); a language
  that is not in the table gets `small` for "fast" (the size rule picked it in all eight measured
  languages) and keeps the app's default model (`large-v3`) for "best". A test recomputes the
  picks from `results.csv` and fails when the table, this page or the CSV disagree.
- The median RTF of each model over the eight languages is the CPU speed the first-run quick
  start window shows per minute of audio (`core.hardware.CPU_SECONDS_PER_AUDIO_SECOND`, also
  checked against `results.csv` by a test).

## Limits

- **Five utterances per language** (88 to 250 reference units per language): a difference of a few
  errors between two models is within noise. The picks are a sensible default, not a ranking
  to quote.
- **Read speech.** FLEURS is sentences read aloud from Wikipedia-style text, mostly clean audio.
  Conversations, noise, music, accents and long recordings (where VAD and the repetition guard
  matter more) are not covered.
- **CPU only.** No GPU numbers; on a GPU the larger models are far faster relative to the
  smaller ones. The RTF of one language also rises when a model falls into a hallucination loop
  (the repetition guard drops the repeats, but the decoding time is spent).
- **Scoring.** Chinese output in Traditional characters scores as errors against the Simplified
  reference (no converter is bundled); dialect and spelling variants are not folded beyond the
  normaliser rules above.

An earlier pilot of this script (Persian, ten utterances, `tiny` and `base`, no fixed seed) is
replaced by this run; it is in the git history of this folder.

## Files

`results.csv`: one row per (language, model, utterance).

| Column | Meaning |
|---|---|
| `language` | Whisper language code |
| `model` | App registry slug (`tiny`, `base`, ...) |
| `utterance_id` | FLEURS file stem (`<id>.wav` in the test split) |
| `metric` | `wer` or `cer` |
| `score` | Error rate of this utterance (can exceed 1.0) |
| `ref_len` | Reference units after normalising (words or characters) |
| `errors` | Edit distance |
| `audio_s`, `decode_s`, `rtf` | Audio length, decode time, real-time factor |
