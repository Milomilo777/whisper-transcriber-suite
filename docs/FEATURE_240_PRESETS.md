# Named transcription presets

Open **Transcribe → Presets…** beside Advanced settings. Set your transcription
options first, type a name and choose **Save current**. To reuse it, choose its
name, inspect the language/model/output summary and choose **Apply**. Saving with
an existing name asks before replacing it. **Delete** removes the saved bundle
after confirmation and leaves the current settings alone.

Presets save transcription options: output formats, prompt, hotwords, timestamps,
batch size, silence detection, hallucination detection, denoising, source
separation, speaker identification/count/threshold, English translation, and the
current language. The language remains a session choice: a new app launch still
starts with Auto. Mixed-language mode and file time ranges are not captured.

Catalog Whisper model choices are included when the current engine uses that
catalog and no custom model path is active. Custom model paths and other engines'
models are excluded. Applying a model-bearing preset requires a compatible
Whisper engine and a model still present in the current catalog. Changing the
model clears the previous per-model override path (including a custom override
with the same catalog slug) and resolves the model through
the current catalog. Apply does not download models; normal model readiness and
download checks run when transcription starts.

Engines, hardware, model storage folders, output folders, accounts, credentials,
network/privacy switches, download preferences, integrations, AI actions and file
names are never captured or applied. Presets stay in the local profile's
`presets.json` alongside `config.json`; they are not shared or uploaded.
Prompts and hotwords are saved as text, so avoid putting credentials in them.

Wait until running transcriptions finish before applying a preset. Applying saves
the settings successfully before updating the controls or retiring idle workers.
The next transcription uses the applied settings. Existing result files and
history are untouched. Project override files still take precedence for their
supported per-file options.

Apply before adding files when you want every option to match a preset. Already
queued tasks keep their language/translation choice; unsnapshotted per-task
options use the current settings when dispatched. Resumed tasks keep the
per-task options from their original run, following the existing resume rules.
