# Competitive Analysis 2026 — Speech-to-Text Landscape

**Status:** research snapshot, May 2026. **Re-audited 2026-07-04** (see
"Section 1 status update" below) — this is the ecosystem/external-tools
survey, so only claims about **our own** capabilities needed
re-checking; the external-tool descriptions (sections A/B) and Chinese-
language research (section 2) are unaffected by anything we've shipped
and are left as-is.
**Audience:** maintainers of the `whisper_project_direct_download_v2` desktop app
**Scope:** EN + Mandarin/CJK + FR + DE. Persian/Arabic explicitly out of scope.
**Baseline:** `faster-whisper` (CTranslate2) + `yt-dlp` + Tkinter/Sun Valley, Session 5 feature set.

---

## A. Open-source landscape we have not yet evaluated

### Alibaba / FunAudioLLM stack

- **SenseVoice (FunAudioLLM, July 2024)** — non-autoregressive multilingual model (ZH/EN/yue/JA/KO for `Small`, 50+ langs for `Large`). Trained on 400k hours; Alibaba claims ~50% relative WER reduction vs Whisper on Chinese/Cantonese. Small variant transcribes 10s of audio in ~70ms — roughly 15x faster than `whisper-large`. Adds spoken-language ID, speech-emotion recognition (SER) and audio-event detection (AED) in one model. License: MIT for code, model weights under permissive terms. Repo: `FunAudioLLM/SenseVoice`.
- **FunASR (ModelScope, Alibaba DAMO)** — broader framework. Ships `Paraformer` (non-autoregressive Mandarin ASR, 60k-hour training set), `FSMN-VAD`, and crucially `CT-Transformer` / `ct-punc` for Chinese punctuation restoration as a separate post-processing model. Supports 7 Chinese dialects and 26 accents. The 2025 release `Fun-ASR-Nano-2512` adds 31-language low-latency streaming. License: MIT. Repo: `modelscope/FunASR`.
- **CapsWriter-Offline (HaujetZhao)** — open-source desktop dictation app, hotkey-driven (CapsLock by default). Architecture is interesting for us: a `sherpa-onnx` server hosts Paraformer + a separate punctuation model, a thin client captures audio and pipes to server. Ships SRT export with word-level timestamps, hot-word customization. Windows/macOS/Linux. License: MIT. Repo: `HaujetZhao/CapsWriter-Offline`.

### Speed-oriented Whisper variants

- **Insanely-Fast-Whisper (Vaibhavs10)** — Transformers pipeline with FlashAttention-2 + BetterTransformer + batched decoding. 150 minutes of audio transcribed in ~98 seconds on a single H100 with `large-v3`, vs ~31 min for fp32 baseline. Bets on GPU parallelism rather than quantization, so VRAM-hungry. License: Apache-2.0. Repo: `Vaibhavs10/insanely-fast-whisper`.
- **WhisperX (m-bain)** — adds wav2vec2 forced phoneme alignment for ~±50 ms word timestamps (vs ±500 ms for vanilla Whisper) plus `pyannote.audio` diarization. Up to 70x real-time with batched inference. Active through Nov 2025. License: BSD-4-Clause. Repo: `m-bain/whisperX`.
- **stable-ts (jianfch)** — drop-in replacement for `whisper.transcribe` with Dynamic Time Warping for word timestamps, silence-suppression on by default, and a `split_callback` API for custom line-splitting logic. Best-in-class for subtitle-grade timestamps without diarization overhead. License: MIT. Repo: `jianfch/stable-ts`.
- **WhisperKit (Argmax, argmaxinc/WhisperKit)** — Swift package that re-implemented Whisper to target Apple Neural Engine. Their ICML 2025 paper reports 2.2% WER with `large-v3 Turbo Optimized` at 0.46s streaming latency. Macros-only (irrelevant as a backend for us, but their open-vocab keyterm prompting and streaming-latency policy are worth studying). License: MIT.
- **Whisper-Streaming (UFAL)** — academic real-time wrapper using `LocalAgreement-n` policy: emit only tokens that 2 consecutive overlapping windows agree on. ~3.3s latency on long-form. CPU-friendly. The follow-up `SimulStreaming` from the same group (2025) extends to simultaneous translation. License: MIT.
- **WhisperLive (Collabora)** — production-grade websocket server, multi-backend (faster-whisper / TensorRT-LLM / OpenVINO), browser extension and iOS client. License: MIT. Repo: `collabora/WhisperLive`.
- **pywhispercpp (absadiki)** — Python bindings for `whisper.cpp`. v1.4.1 from Dec 2025. Optional `GGML_CUDA=1` build. Strictly worse than `faster-whisper` on GPU, but materially smaller wheel footprint and useful as a CPU fallback. License: MIT.

### NVIDIA NeMo family

- **Parakeet-TDT-0.6B-v3 (CC-BY-4.0)** — 600M-param, 25 European languages incl. EN/FR/DE. **Beats `whisper-large-v3` on multilingual averages** (9.7% vs 9.9% mean WER across 24 langs, 5.3% vs 5.8% on common-lang subset), at ~54x throughput. Lacks Chinese.
- **Canary-1B-v2** — 1B-param, transcription + translation across the same 25 European langs. Higher quality at ~10x faster than 3x-larger competitors. License: CC-BY-4.0.

### Other Chinese open releases

- **Tencent Covo-Audio (March 2026)** — 7B end-to-end speech LM. Skips the ASR→LM→TTS cascade entirely; ingests audio and emits audio. Tops MMAU/MMSU at 7B scale. Full-duplex conversation. CC-BY-4.0. Not a direct ASR replacement, but signals where the field is going.
- **ByteDance Seed LiveInterpret 2.0** — end-to-end simultaneous speech-to-speech translation. Not open-source yet but research is out.

### Wrapper apps to learn UX from

- **Vibe (thewh1teagle/vibe)** — Tauri (Rust + web view) front end over `whisper.cpp`. Cross-platform single binary, batch transcription, URL ingestion, AI summary panel. License: MIT.
- **Handy (cjpais/Handy)** — extensible offline STT, plugin model.
- **VoiceTypr (moinulmoin)** — Tauri dictation app aimed at Wispr Flow / SuperWhisper alternatives space.

---

## B. Commercial / SaaS — features that signal user demand

- **Deepgram Nova-3** — first STT model with self-serve fine-tuning. Real-time code-switching across 10 langs incl. EN/FR/DE. ~5.26% WER on internal EN. $0.0077/min streaming, $0.0043/min batch.
- **AssemblyAI Universal-3-Pro + LeMUR** — 99+ langs, but the differentiator is `LeMUR`: pipe up to 10h of transcript (~150k tokens) into Claude 4 Sonnet/Opus for summarization, Q&A, action items. Decouples ASR quality from downstream NLP.
- **ElevenLabs Scribe v2 / Scribe v2 Realtime (Nov 2025)** — claims 96.7% EN accuracy. Realtime variant: ~150ms latency, "negative latency prediction," text conditioning, keyterm prompting. Tags non-speech sound events (laughter, footsteps) and PII redaction with entity timestamps.
- **Rev.ai** — SOC 2 Type II, no AI-training on customer data. Strong for legal/medical.
- **Otter.ai** — meeting-attendee positioning. Free tier 300 min/mo, strong on calendar integration.
- **Descript** — the gold standard for transcript-driven editing. Delete a word in the transcript → audio cut. Filler-word AI ("remove all ums" in one click). Speaker auto-detect and global rename. Non-destructive edits.
- **Trint** — storyteller positioning, strong closed captioning (G2 score 8.9 vs Otter 7.9), collaboration features.
- **Sonix** — 53+ langs, AI topic detection and entity recognition, custom dictionaries.
- **Happy Scribe** — 120+ translation targets, expert proofreading add-on pushes accuracy to 99%.
- **VEED.io / Riverside.fm** — video-first; transcript is a side feature for caption burn-in.
- **Krisp** — combines two-way noise cancellation with transcription. Custom Vocabulary up to 750 words. On-device EN transcription, cloud for 15 others.
- **MacWhisper 12 (2025)** — first Mac app with on-device speaker diarization. Also supports Parakeet as alternative backend, plus ElevenLabs/Deepgram cloud routing.
- **WhisperHub / Wispr Flow / SuperWhisper** — dictation-replacement apps competing on system-wide hotkeys and stylistic post-editing.
- **Azure Speech Studio** — phrase-list biasing, batch/fast/real-time tiers, no-code studio UI.
- **Google Cloud Chirp v3** — 85+ langs, speaker diarization, automatic language detection, built-in denoiser, custom-vocabulary speech adaptation.
- **Apple Voice Memos (iOS 18)** — free, fully on-device, EN/ES/PT/IT/FR/DE/JA/KO/zh-Hans/zh-Hant. Apple Intelligence "summarize transcript" with a tap.

---

## 1. Top 15 features to consider, ranked by impact for EN/CJK/FR/DE

| # | Feature | Inspiration | Why it matters | Effort | Status (2026-07-04) |
|---|---------|-------------|----------------|--------|----------------------|
| 1 | **Chinese punctuation post-processor** (CT-Transformer/`ct-punc` or fine-tuned model) | FunASR, CapsWriter | Whisper under-punctuates Mandarin badly; without this, Chinese SRTs are unreadable walls of text. The single highest-leverage CJK fix. | M | 🔴 Not built — no punctuation-restoration model/postprocessor in `core/`. |
| 2 | **WhisperX-style forced alignment** for ±50 ms word timestamps | WhisperX | Current word timestamps drift; this is the prerequisite for click-to-jump editor and accurate karaoke-style highlighting. | M | 🟢 Shipped — `core/alignment.py` (stable-ts DTW refinement to ±50ms), opt-in via the Advanced-dialog "Refine word timings with stable-ts" checkbox, off by default, tested. |
| 3 | **Speaker diarization** (`pyannote.audio` 3.x) with global rename | WhisperX, MacWhisper 12, Descript | "Who said what" is the #1 user-visible gap. Global rename lets one edit propagate. | L | 🟢 Shipped — `core/diarization.py` (sherpa-onnx, no PyTorch), fully offline. Rename propagates everywhere within the open transcript (no cross-transcript speaker identity to rename against). |
| 4 | **Initial-prompt presets per language** (esp. zh-Hans/zh-Hant separators, FR quotation conventions, DE compound-hint) | Whisper community lore | Fixes simplified-vs-traditional drift and underpunctuation without retraining. Trivial to ship, large UX win. | XS | 🟡 Partial — `initial_prompt` is wired through as a single global user-supplied field (same mechanism as hotwords), not automatic per-language presets. |
| 5 | **Pluggable backend abstraction** (faster-whisper today, add SenseVoice / Parakeet later) | NVIDIA NeMo, FunASR | We will be stuck on one model otherwise. Build the seam now before features couple too tight. | M | 🟢 Shipped — `core/backends/base.py` `Backend` ABC, exactly the sketched layout in Section 3 below, now with 5 concrete backends. |
| 6 | **SenseVoice-Small as second backend** for Mandarin/Cantonese/JP/KO | FunAudioLLM | 15x faster than whisper-large, claimed 50% relative WER win on zh. Single biggest CJK accuracy lever. | L | 🔴 Not built as such — the seam (#5) was used for whisper.cpp, Gemini, Google Cloud STT, and NVIDIA Parakeet instead. The CJK-specific accuracy lever this row calls for is still open. |
| 7 | **Click-word → audio jump** in subtitle editor | Descript | The single feature that changes "transcript viewer" into "transcript editor." Requires #2. | M | 🟡 Partial — click-to-seek is shipped in `app/dialogs/transcript_viewer.py`, but at segment granularity, not per-word (the word label is a non-interactive display). |
| 8 | **Filler-word detection + bulk remove** (uh/um/啊/嗯/呃/euh/ähm) | Descript, Riverside, CapCut | Multilingual filler list per lang; one-click "remove all ums in this segment / file." | S | 🟡 Partial — shipped (`_strip_fillers` in the transcript viewer), but the word list (`_FILLER_WORDS`) is English-only (uh/um/uhm/er/erm/eh/ah/mm/mmm/hm) — no FR/DE/ZH fillers as this row specifically asked for. |
| 9 | **Custom hot-words / phrase biasing** | Deepgram, Azure, ElevenLabs, CapsWriter | Per-project glossary boosts proper-noun recall. Whisper supports via `initial_prompt`; we can wrap a UI on top. | S | 🟡 Partial — a "Hotwords" field exists in the Advanced dialog, but it's one global comma-separated field, not a per-project glossary manager. |
| 10 | **CJK-aware line splitting** (max ~16 chars/line ZH, 9-12 CPS budget) | Netflix ZH style guide | Current 42-char default is wrong for ZH. Needs a width-aware splitter that counts Han glyphs as 2 cells. | S | 🔴 Not built — no CJK-width-aware line splitter found anywhere in `core/`. |
| 11 | **Optional LLM post-processor** (summary, action items, chapter detection) | AssemblyAI LeMUR, Apple Intelligence, MacWhisper | Bring-your-own-key panel for local Ollama or cloud Claude/GPT. Decouples our ASR work from downstream NLP. | M | 🟡 Backend shipped, UI missing — `core/llm.py` (download-on-first-use local Qwen2.5-1.5B via llama-cpp-python) fully implements `summarise`/`action_items`/`ask`/`translate`, but the ONLY UI hook is the Advanced-dialog "Enable local LLM" download button — no button/panel anywhere actually invokes summarise/action-items/ask. Chapter detection (`core/chapters.py`) is a separate, fully-wired feature: it genuinely runs during transcription and writes a tested `<base>.chapters.json` sidecar, but per its own docstring the transcript viewer doesn't read it yet ("future work") — so chapters are generated but never navigable in the app. |
| 12 | **Streaming / live-mic mode** with LocalAgreement-n | Whisper-Streaming, WhisperLive | Unlocks dictation use case. ~3.3s latency is acceptable. | L | 🟡 Partial — the "Live" tab records mic/system-audio (`core/recorder.py`) to WAV then runs the normal transcribe pipeline (record-then-transcribe); true continuous streaming (LocalAgreement-n) still not built. |
| 13 | **Hot-key dictation overlay** | CapsWriter, MacWhisper, Wispr Flow | Hold-to-talk system tray app that drops text into focused window. Big productivity lever for power users. | L | 🔴 Not built — no hotkey/keyboard-hook code anywhere. |
| 14 | **Sound-event tagging** (music/laughter/applause as `[Music]`-style cues) | ElevenLabs Scribe v2 | Required for SDH (subtitles for the deaf and hard-of-hearing). SenseVoice already emits AED tags we can lean on. | M | 🔴 Not built — no AED/sound-event-tag code anywhere. |
| 15 | **PII / entity timestamps + redaction** | ElevenLabs Scribe v2, AssemblyAI | "Bleep out card numbers" feature; small but punches above its weight for healthcare/legal users. | M | 🔴 Not built — no redaction/PII/entity code anywhere. |

XS ≤ 1 day · S ≤ 3 days · M ≤ 1-2 weeks · L 2-4 weeks · XL > 4 weeks.

### Section 1 status update (2026-07-04)

Re-checked every row above against the current codebase (file:line
evidence in the Status column) — the same method used to fix
`docs/GAPS_AGAINST_PEERS_2026.md` the same day. **5 of 15 fully
shipped, 6 partial, 4 still not built.** The three biggest surprises
since May: forced alignment (#2), diarization (#3), and the pluggable
backend seam (#5) all landed — exactly as this document originally
recommended, in #5's case down to the literal file layout. The most
interesting *partial* is #11: a complete local-LLM post-processing
engine (summarize / action items / Q&A / translate) and a fully-wired
auto-chapter pipeline both exist in `core/`, tested and functional, but
neither has a UI entry point a user could actually find — the exact
same "built the engine, forgot the doorway" pattern the gap-analysis
audit found in `core/search.py`'s cross-history search. The CJK-specific
asks (#1, #6, #10) remain the least-served part of this document's
original brief — none of the three shipped.

---

## 2. Chinese-language considerations

**Tokenization.** Mandarin has no whitespace word boundaries. Whisper emits BPE tokens that frequently split mid-glyph or, worse, span across `汉字` boundaries inconsistently. For line-splitting, count visual width (CJK fullwidth = 2 cells; halfwidth = 1) rather than `len(s)`. For sentence segmentation, use punctuation-based splits with `jieba` or `pkuseg` only when actual word boundaries are needed (search, hotkey replacement); subtitle generation does not need full tokenization.

**Punctuation insertion.** Whisper's Mandarin training data was light on punctuation, so out-of-the-box transcripts are wall-of-text. Three workable mitigations:
1. `initial_prompt="以下是普通话的句子。"` (Simplified) or `"以下是普通話的句子。"` (Traditional) nudges the model into "punctuated mode" — measurable but inconsistent.
2. Run FunASR's `ct-punc` model as a post-processor on the plain text. Trained specifically for Chinese-English mixed punctuation. ~50 MB, CPU-friendly.
3. Switch to SenseVoice-Small for Chinese audio — it ships with internal punctuation and emits inverse-text-normalized output.

**Simplified vs Traditional.** Whisper drifts between simplified and traditional within a single file. Pin behavior with the initial prompt (give it a sample line in the target variant). For batch post-fix, use OpenCC (`opencc-python-reimplemented`) to normalize. Expose as `--zh-variant zh-Hans|zh-Hant|auto` in our config.

**Subtitle line-length conventions.** Netflix's ZH style guides cap at ~16 characters across screen, max 2 lines per cue. WCAG suggests 40 chars max for CJK. Our 42-char default (Latin) translates to a much heavier reading load in ZH. Target:
- Max 16 zh-Hans chars per line (Netflix).
- Max 20 zh-Hant chars per line (Netflix Traditional guide is slightly looser).
- 2 lines per cue, hard limit.

**Characters per second.** Latin "safe zone" is 15-17 CPS. CJK is 9-12 CPS because each character carries ~2-3x the information density. A 10 CPS Mandarin subtitle ≈ 20 CPS English in information rate.

**Whisper-on-Chinese gotchas we have to handle:**
- **Hallucinated English fragments.** Whisper inserts English phrases ("Thank you for watching.") into otherwise-Mandarin output, especially on silence or music. Aggressive VAD trimming + `condition_on_previous_text=False` for ZH cuts this. SenseVoice does not exhibit this.
- **Segment boundaries cut mid-word.** Whisper's 30s window often splits compounds like `中华人民共和国` across two segments. Use a VAD with longer minimum silence (we are on Silero defaults; for ZH bump `min_silence_duration_ms` to ~700-1000).
- **Repetition loops.** Identical line repeated 5-10 times on noisy input. Detected by checking same-text-different-timestamp; auto-collapse in post.
- **Numbers and dates.** Whisper transcribes "二零二六年" as Chinese characters; users often want "2026 年". `cn2an` (Apache-2.0) converts both directions, expose as a toggle.

---

## 3. Strongest model in 2026 for EN + CJK + FR + DE

The honest answer is **no single model wins all four**. Headline 2025/2026 numbers:

| Model | EN WER | DE WER | FR WER | ZH/CJK | Notes |
|---|---|---|---|---|---|
| `faster-whisper large-v3` | ~4-6% on LibriSpeech | ~4-5% (CV) | ~5-7% (CV) | weak, underpunctuates | our current baseline; 99 langs |
| `whisper-large-v3-turbo` | ~6% (216x RT on Groq) | similar to v2 | similar to v2 | mild degradation on yue | 4-decoder distilled, much faster |
| `SenseVoice-Small` | competitive | not supported (Small) | not supported (Small) | **best** on AISHELL/Wenetspeech; ~50% rel. win vs Whisper | only ZH/EN/yue/JA/KO |
| `Parakeet-TDT-0.6B-v3` | **strong** | strong (25 EU langs) | strong | **not supported** | beats whisper-large-v3 multilingual avg 9.7% vs 9.9%; ~54x throughput |
| `Canary-1B-v2` | strong | strong | strong | not supported | adds translation; CC-BY-4.0 |
| Deepgram Nova-3 | ~5.26% internal EN | covered | covered | not best-in-class | cloud only |
| ElevenLabs Scribe v2 | claimed 96.7% (3.3% WER) EN | covered | covered | covered | cloud only |

**Recommendation.** Keep `faster-whisper` as the default — it is the only OSS option that covers all four target languages competently in a single model. Add a **pluggable backend** with two concrete second-engines:

1. **SenseVoice-Small** routed when detected language ∈ {zh, yue, ja, ko}. This is the biggest accuracy lever we can ship for CJK, and the inference speed is a side benefit. Ships punctuation natively, sidesteps the FunASR `ct-punc` step.
2. **Parakeet-TDT-0.6B-v3** as an opt-in fast path for {en, fr, de} on machines with NeMo installed. The 54x throughput is real and meaningful for batch jobs over long content (lectures, podcasts).

Concretely: an interface roughly like
```
core/backends/
    base.py           # TranscriptionBackend ABC
    faster_whisper.py # current
    sensevoice.py     # new
    parakeet.py       # new
```
with a router that picks based on detected language + user preference + GPU presence. The existing `BatchedInferencePipeline` work and our SQLite history already speak a model-agnostic schema, so the cut should be tractable.

> **2026-07-04:** this recommendation shipped, almost exactly as sketched —
> `core/backends/base.py` defines a real `Backend` ABC, with
> `faster_whisper_be.py`, `whisper_cpp.py`, `cloud_stt.py`,
> `google_cloud_stt.py`, and `nvidia_asr.py` (Parakeet) as the five
> concrete backends, selectable from the Transcribe-tab engine
> combobox. The one gap: no `sensevoice.py` — the CJK-specific accuracy
> lever this section leads with is still unaddressed (see row #6
> above).

---

## 4. Editor UX — five features for Phase 4

Descript is the reference implementation; we do not have to copy everything, but five capabilities are now table stakes for any transcript editor:

1. **Click-word → audio jumps to that timestamp.** With WhisperX-style alignment (#2 above) we have ±50 ms word timestamps. Wire each word in the editor view to seek the media player. Single biggest UX shift from "viewer" to "editor."
2. **Speaker labels with global rename and color coding.** Diarization produces `SPK_00`, `SPK_01`, etc. Renaming "SPK_01 → Mahdi" should propagate everywhere in the file with one undo step. Color per-speaker on the timeline.
3. **Filler-word bulk operations.** Detect filler tokens per language (EN: um, uh, like, you know; FR: euh, ben, voilà; DE: ähm, also; ZH: 嗯, 啊, 那个, 这个). Show a counter ("Found 47 fillers"), let user preview, then "Remove all" or "Remove in selection." Critical caveat: removing filler words should support two modes — "remove from captions only" vs "remove from cut," which is a Descript pain point users actively request.
4. **Edit-back-to-subtitle with re-flowed timestamps.** When user merges/splits/edits cues in the editor, write SRT/VTT back with arithmetically re-distributed timestamps (`duration * (chars_before / chars_total)`) so caption sync survives. Add a "preserve original timing" toggle for the case where audio has been re-cut.
5. **Gap / silence detection panel** showing all silences > N seconds as a navigable list. Lets the editor jump straight to "dead air," delete it, and have downstream timestamps shift accordingly. Riverside and Descript both ship this. Useful for podcast post-prod and for tightening lecture recordings.

A reasonable Phase-4 cut order: (1) → (4) → (5) → (2) → (3). Items 1, 4, 5 are media-player and data-structure work that we can ship without diarization; 2 and 3 sit on top of the diarization branch.

---

## Sources

### Open source
- [FunAudioLLM/SenseVoice](https://github.com/FunAudioLLM/SenseVoice)
- [FunAudioLLM/SenseVoiceSmall on Hugging Face](https://huggingface.co/FunAudioLLM/SenseVoiceSmall)
- [modelscope/FunASR](https://github.com/modelscope/FunASR)
- [HaujetZhao/CapsWriter-Offline (releases)](https://github.com/HaujetZhao/CapsWriter-Offline/releases)
- [Vaibhavs10/insanely-fast-whisper](https://github.com/Vaibhavs10/insanely-fast-whisper)
- [m-bain/whisperX](https://github.com/m-bain/whisperx)
- [jianfch/stable-ts](https://github.com/jianfch/stable-ts)
- [argmaxinc/WhisperKit](https://github.com/argmaxinc/WhisperKit)
- [ufal/whisper_streaming](https://github.com/ufal/whisper_streaming)
- [collabora/WhisperLive](https://github.com/collabora/WhisperLive)
- [absadiki/pywhispercpp](https://github.com/absadiki/pywhispercpp)
- [thewh1teagle/vibe](https://github.com/thewh1teagle/vibe)
- [NVIDIA Parakeet-TDT-0.6B-v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3)
- [NVIDIA Canary-1B-v2](https://huggingface.co/nvidia/canary-1b-v2)
- [NVIDIA Granary dataset announcement](https://blogs.nvidia.com/blog/speech-ai-dataset-models/)
- [Tencent Covo-Audio 7B](https://www.marktechpost.com/2026/03/26/tencent-ai-open-sources-covo-audio-a-7b-speech-language-model-and-inference-pipeline-for-real-time-audio-conversations-and-reasoning/)
- [WhisperKit ICML 2025 paper](https://arxiv.org/html/2507.10860v1)
- [Canary-v2 / Parakeet-v3 arXiv](https://arxiv.org/html/2509.14128v1)

### Commercial / SaaS
- [Deepgram Nova-3 introduction](https://deepgram.com/learn/introducing-nova-3-speech-to-text-api)
- [Deepgram pricing 2025](https://deepgram.com/pricing)
- [AssemblyAI LeMUR docs](https://www.assemblyai.com/docs/lemur/apply-llms-to-audio-files)
- [AssemblyAI Claude 4 via LeMUR](https://www.assemblyai.com/blog/claude-4-models-now-available-through-our-lemur-api)
- [ElevenLabs Scribe v2 Realtime](https://elevenlabs.io/realtime-speech-to-text)
- [ElevenLabs Scribe accuracy review](https://venturebeat.com/ai/elevenlabs-new-speech-to-text-model-scribe-is-here-with-highest-accuracy-rate-so-far-96-7-for-english)
- [Descript transcript editor — Edit Like a Doc](https://help.descript.com/hc/en-us/articles/15726742913933-Edit-like-a-doc)
- [Descript filler-word removal](https://www.descript.com/filler-words)
- [Descript Speakers help](https://help.descript.com/hc/en-us/articles/10164803814285-Speakers)
- [Krisp transcription + noise cancellation](https://krisp.ai/meeting-transcription/)
- [MacWhisper 12 speaker diarization](https://9to5mac.com/2025/03/18/macwhisper-12-delivers-the-most-requested-feature-to-the-leading-ai-transcription-app/)
- [Azure Speech Studio overview](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-studio-overview)
- [Google Cloud Chirp 3 docs](https://docs.cloud.google.com/speech-to-text/docs/models/chirp-3)
- [Apple Voice Memos iOS 18 transcription](https://www.tomsguide.com/phones/iphones/ios-18-finally-adds-transcription-to-voice-memos-heres-how-to-use-it)
- [Trint vs Otter comparison](https://trint.com/blog/trint-or-otter)
- [Sonix vs Happy Scribe](https://sonix.ai/resources/sonix-vs-happy-scribe/)
- [Rev vs Otter](https://www.rev.com/blog/rev-vs-otter)

### Chinese subtitle conventions and Whisper gotchas
- [Netflix Chinese (Simplified) Timed Text Style Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215986007-Chinese-Simplified-Timed-Text-Style-Guide)
- [Netflix Chinese (Traditional) Timed Text Style Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215994807-Chinese-Traditional-Timed-Text-Style-Guide)
- [Subtitle standards guide (Netflix/BBC/Amazon)](https://subhero.io/blog/subtitle-standards-guide)
- [Whisper Chinese punctuation discussion (HF)](https://huggingface.co/openai/whisper-large-v3/discussions/103)
- [Whisper simplified vs traditional Chinese discussion](https://github.com/openai/whisper/discussions/277)
- [faster-whisper Chinese punctuation issue](https://github.com/SYSTRAN/faster-whisper/issues/662)
- [Memo.ac — Whisper hallucinations solutions](https://memo.ac/blog/whisper-hallucinations)

### Benchmarks
- [Parakeet V3 vs Whisper benchmark](https://whispernotes.app/blog/parakeet-v3-default-mac-model)
- [Northflank — Best OSS STT 2026 benchmarks](https://northflank.com/blog/best-open-source-speech-to-text-stt-model-in-2026-benchmarks)
- [Artificial Analysis STT leaderboard](https://artificialanalysis.ai/speech-to-text)
- [Ionio 2025 Edge STT benchmark](https://www.ionio.ai/blog/2025-edge-speech-to-text-model-benchmark-whisper-vs-competitors)
- [Modal — choosing Whisper variants](https://modal.com/blog/choosing-whisper-variants)
