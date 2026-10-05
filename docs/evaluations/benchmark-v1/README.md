# Multilingual benchmark v1: local Whisper models per language

Status: pilot (one language, two models). The full run is planned as a follow-up.

`tools/benchmark_multilingual.py` scores the app's local faster-whisper models per language on
public read speech, on CPU, through the app's own backend (`FasterWhisperBackend.load` then
`transcribe_to_segments`, the calls the transcription worker makes). It touches neither the user's
config file nor the user's model folder.

```
python tools/benchmark_multilingual.py --languages fa --models tiny base -n 10
```

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

## Method

- **Utterances.** Per language, the first N files of the test archive (a tar archive lists files in
  sorted-name order, so the pick is deterministic and only the start of the archive is downloaded)
  whose sentence id has not been taken yet. Different speakers reading the same sentence count once.
- **Reference.** The raw (cased, punctuated) FLEURS transcription.
- **Decoding.** `device=cpu`, `compute_type=int8`, language set explicitly, app defaults otherwise
  (no VAD, no initial prompt).
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
  consuming the segment generator). The first utterance of a run includes CPU warm-up.

Known limits: Chinese output in Traditional characters scores as errors against the Simplified
reference (no converter is bundled); dialect and spelling variants are not folded beyond the rules
above; ten utterances give wide error bars.

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

## Pilot result (fa, 10 utterances, CPU int8, 8 logical cores)

| Model | Corpus WER | Errors / words | Decode total | RTF (total) | RTF (without the first utterance) | Model load |
|---|---|---|---|---|---|---|
| tiny | 0.983 | 231 / 235 | 86.9 s | 0.59 | 0.44 | about 7 s |
| base | 0.843 | 198 / 235 | 46.4 s | 0.32 | 0.32 | about 16 s |

Both are close to unusable for Persian, as expected for the smallest models; the pilot's job is to
prove the pipeline end to end and to size the full run. Decoding is not deterministic (Whisper's
temperature fallback): a first complete run of the same ten utterances gave tiny 0.881 (207 / 235)
and base 0.843, so tiny's rate moved by 0.10 between runs and the full run should repeat the
small models or fix the temperature. A few tiny utterances decode unusually slowly (RTF up to 2.3,
the warm-up utterance included), so timings of tiny are noisy.
Sanity runs on es and zh (not committed; 10 utterances each) gave es tiny 0.162 and base 0.081 WER,
zh tiny 0.398 and base 0.256 CER: plausible orders of magnitude, not compared against
published figures.

Sizing for a full run: about 0.3 to 0.6 real-time on this CPU for tiny and base, so 8 languages x
10 utterances (about 15 s each, 1200 s of audio) x 2 small models is roughly 10 to 20 minutes of
decoding plus about 220 MB of model download; larger models are far slower on CPU and need their
own estimate. Rows are written as they are produced and an existing `--out` file is not
overwritten without `--force`.
