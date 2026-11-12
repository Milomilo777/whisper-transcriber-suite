# Persian voice model recommendation

Selecting Persian in the voice tab shows Chatterbox Farsi first, with a link to
its model and license page. The recommendation is external: Generate continues
to use the selected Kokoro or OmniVoice engine. Opening the tab or changing the
language never opens a website, downloads a model, installs a runtime or accepts
a license. The model page opens only when the person presses its button.

The [model metadata](https://huggingface.co/api/models/mehdi-hf/chatterbox-farsi)
was checked on 2026-11-13 at revision
`e553b6112b24ce5d5a38b8af9073c59a4505cbbb`: it identifies Persian TTS, an automatic
access gate, the non-commercial license, required attribution and no training or
distillation on outputs. The complete gated README and license could not be read
anonymously (HTTP 401); the person must read and accept them on Hugging Face.
Research skipped: anonymous access to the complete gated text is unavailable;
public model metadata and the existing model-card research inform this bounded
recommendation. No model was downloaded or license accepted during development.

The publisher's model-card research reports a required retained watermark and
lower Apple MPS quality. CPU quality and speed remain unverified. The UI recommends
NVIDIA rather than asserting measured CPU behavior or comparative WER/MOS.

Fable's runtime-isolation advice was accepted as a boundary: Chatterbox's pinned
Torch/Transformers stack must not be installed into the existing shared extras
folder. Integrated generation, isolated runtime installation, gated downloads,
license acceptance, watermark verification and real Persian audio validation are
separate unfinished work; this recommendation does not claim those capabilities.
