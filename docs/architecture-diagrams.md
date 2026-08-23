# Architecture diagrams

Two views are provided. Pick the one that fits your need.

- **Simple overview** — a Mermaid flowchart, renders inline on GitHub markdown. Good for "what talks to what" at a glance.
- **Full system diagram** — the colored SVG at [`architecture.svg`](architecture.svg) (1500 × 1100 px, layered, drop shadows, every subsystem labeled). Good for "where exactly does this file live, and what writes to it."

For the long-form prose description (threading rules, cancellation contract, worker stdio protocol, design rationale), see [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## Simple overview (Mermaid)

```mermaid
flowchart TB
    User([👤 User · Windows 10/11])

    subgraph App ["Tk App  (single thread)"]
        direction TB
        Entry["gui.py · 11 lines<br/>→ app/app.py · 489 lines"]
        Tabs["3 tabs: Transcribe · Queue · Download Videos"]
        Services["Services: transcription · download · format · integrations"]
        Queues[("Event queues: worker · format · download")]
        Entry --> Tabs --> Services --> Queues
    end

    subgraph Workers ["Transcription workers ×N"]
        direction TB
        Worker["core/worker.py · JSON stdio loop"]
        Trans["core/transcriber.py · VAD · word ts · batched"]
        FW["faster-whisper · CTranslate2 (CUDA fp16 / CPU int8)"]
        Worker --> Trans --> FW
    end

    subgraph Vendored ["External processes  (bin/)"]
        YTD["yt-dlp.exe · --newline · --progress-template"]
        FFM["ffmpeg.exe"]
        FFP["ffprobe.exe"]
    end

    subgraph Core ["core/  pure Python · 137 tests"]
        Config["config.py · atomic save · drive fallback"]
        Hist["history.py · SQLite"]
        Log["logging_setup.py · rotating handler"]
        Writers["writers/ · srt · vtt · tsv · txt · json · lrc"]
        OTR["integrations/otranscribe.py"]
    end

    subgraph FS ["%LOCALAPPDATA%\\WhisperTranscriberSuite\\"]
        ConfigJ[("config.json")]
        Logs[("logs/app.log")]
        Models[("Cache/models/...")]
        DB[("history.db · SQLite")]
    end

    Outputs[("User folder · &lt;title&gt;.srt .vtt .tsv .txt .json .lrc .otr · .mp4 .mp3 .m4a")]

    subgraph Net ["External network"]
        Mirror["smch.ir · model ZIP + MD5"]
        Sites["YouTube · 1000+ sites"]
        OTRWeb["otranscribe.com"]
        GH["github.com/yt-dlp releases"]
    end

    User -->|click · paste| Entry
    Services -->|spawn · JSON stdio| Workers
    Services -->|subprocess.Popen<br/>★ auto-transcribe after download| Vendored
    Workers --> Writers
    Writers --> Outputs
    Vendored --> Outputs
    App <--> Core
    Core -.read/write.-> FS
    Trans -.fetch.-> Mirror
    YTD -.fetch.-> Sites
    Services -.opens browser.-> OTRWeb
    YTD -.opt-in daily check.-> GH

    classDef user fill:#fce7f3,stroke:#db2777,stroke-width:2px,color:#0f172a
    classDef ui fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#0f172a
    classDef core fill:#d1fae5,stroke:#059669,stroke-width:2px,color:#0f172a
    classDef worker fill:#fed7aa,stroke:#ea580c,stroke-width:2px,color:#0f172a
    classDef ext fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#0f172a
    classDef fs fill:#f1f5f9,stroke:#475569,stroke-width:2px,stroke-dasharray:5 3,color:#0f172a

    class User user
    class App,Entry,Tabs,Services,Queues ui
    class Workers,Worker,Trans,FW worker
    class Vendored,YTD,FFM,FFP ext
    class Core,Config,Hist,Log,Writers,OTR core
    class FS,ConfigJ,Logs,Models,DB,Outputs fs
    class Net,Mirror,Sites,OTRWeb,GH ext
```

Legend: pink = user · blue = UI · green = `core/` · orange = transcription workers · purple = external processes / network · gray dashed = filesystem.

---

## Full system diagram

The colored detailed view, with every subsystem and every file path labeled:

![Whisper Transcriber Suite — system architecture](architecture.svg)

If GitHub doesn't inline the SVG above on your client, open [`architecture.svg`](architecture.svg) directly.

---

## Prose counterpart

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the long-form description: process model, threading rules, cancellation contract, worker stdio protocol, configuration schema, and the rationale for each choice.

The diagrams answer **what**; `ARCHITECTURE.md` answers **why**.
