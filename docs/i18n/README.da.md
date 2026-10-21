<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**Gratis offline-transskription og undertekster til lange optagelser på dit sprog — på en almindelig bærbar computer, uden konto og uden at uploade lyd.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![downloads](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/total?label=downloads&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Download til Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS og Linux: se [Download](#download).

<!-- language-links:start -->

<p>
<a href="../../README.md">English</a> ·
<a href="README.de.md">Deutsch</a> ·
<a href="README.fr.md">Français</a> ·
<a href="README.es.md">Español</a> ·
<a href="README.it.md">Italiano</a> ·
<a href="README.pt-BR.md">Português (Brasil)</a> ·
<a href="README.pt.md">Português (Portugal)</a> ·
<a href="README.nl.md">Nederlands</a> ·
<a href="README.pl.md">Polski</a> ·
<a href="README.ru.md">Русский</a> ·
<a href="README.uk.md">Українська</a> ·
<a href="README.tr.md">Türkçe</a> ·
<a href="README.cs.md">Čeština</a> ·
<a href="README.sk.md">Slovenčina</a> ·
<a href="README.hu.md">Magyar</a> ·
<a href="README.ro.md">Română</a> ·
<a href="README.bg.md">Български</a> ·
<a href="README.el.md">Ελληνικά</a> ·
<a href="README.sv.md">Svenska</a> ·
<b>Dansk</b> ·
<a href="README.nb.md">Norsk bokmål</a> ·
<a href="README.fi.md">Suomi</a> ·
<a href="README.hr.md">Hrvatski</a> ·
<a href="README.sr.md">Српски</a> ·
<a href="README.sl.md">Slovenščina</a> ·
<a href="README.lt.md">Lietuvių</a> ·
<a href="README.zh-CN.md">简体中文</a> ·
<a href="README.zh-TW.md">繁體中文</a> ·
<a href="README.ja.md">日本語</a> ·
<a href="README.ko.md">한국어</a> ·
<a href="README.vi.md">Tiếng Việt</a> ·
<a href="README.th.md">ไทย</a> ·
<a href="README.id.md">Bahasa Indonesia</a> ·
<a href="README.ms.md">Bahasa Melayu</a> ·
<a href="README.hi.md">हिन्दी</a> ·
<a href="README.ar.md">العربية</a> ·
<a href="README.fa.md">فارسی</a> ·
<a href="README.he.md">עברית</a> ·
<a href="README.lv.md">Latviešu</a> ·
<a href="README.ca.md">Català</a> ·
<a href="README.bn.md">বাংলা</a> ·
<a href="README.fil.md">Filipino</a>
</p>

<!-- language-links:end -->

<!-- translated from README.md at commit 66585d5 -->

</div>

## Hvem det er til

Undertekstere, oversættere, forskere og journalister, der omdanner lange
optagelser (interviews, forelæsninger, taler, videoer) til tekst eller undertekster.
Træk og slip en lyd- eller videofil, så skrives transskriptionen lige ved siden af. Talemotoren kører på din egen computer, så der er
ingen minutpris, og når modellen først er downloadet, kræves der ingen
internetforbindelse.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="Fanen Transcribe: et område til at slippe filer i, valg af motor og sprog, indstillinger for talermærker og tidsstempler på ord" width="80%">
</div>

## Nyheder i 2.0

- **Hastighed og resterende tid:** Queue-fanen viser hastigheden for hver opgave og en omtrentlig resterende tid.
- **Undertekstet video fra et link:** download, transskriber og brænd underteksterne ind i en enkelt opgave ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Transskription som webside:** en enkelt `.html`-fil med søgefunktion og klik-for-at-afspille, der fungerer offline i enhver browser.
- **Offline-tilstand du kan kontrollere:** med Work offline slået til viser en statuslinje, om appen eller en proces, den har startet, har en netværksforbindelse.
- **Oversæt til engelsk:** tale, der ikke er på engelsk, bliver til engelske undertekster i én arbejdsgang.
- **Hurtig start:** ved nyinstallation stilles der tre spørgsmål, og et 18 sekunders prøveklip viser resultatet med det samme.
- **Rapporter et problem** fra Help, uden en GitHub-konto.
- **macOS:** app-menu med Settings (Command-komma), lyst og mørkt tema der følger systemet, notifikationer. **Windows:** proceslinjeforløb og mørke titellinjer.

Fuld liste: [CHANGELOG](../CHANGELOG.md).

## Funktioner

- **Lokale motorer:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (standard), whisper.cpp og NVIDIA Parakeet, til de mange sprog, som Whisper
  understøtter. Bruger en NVIDIA GPU
  via CUDA når det er muligt, ellers CPU'en.
- **Appen på dit sprog:** Menuer, knapper og beskeder på 42 sprog (maskinoversat og
  markeret som sådan; rettelser er velkomne). Den følger dit systemsprog, eller du
  vælger et under Avancerede indstillinger. Persisk, arabisk og hebraisk fås
  foreløbig på Windows.
- **14 outputformater:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX og
  PDF, plus formaterne oTranscribe, ELAN, InqScribe og Express Scribe. DOCX
  og PDF gengiver alle skriftsystemer, og persisk, arabisk og urdu læses fra højre til venstre
  med forbundne bogstaver.
- **Delbar webside:** gem en færdig transskription som en `.html`-fil, der
  fungerer offline i enhver browser; klik på et ord for at høre det, søg, spring til
  kapitler.
- **Taleretiketter** uden en Hugging Face-konto, plus tidsstempler pr. ord og
  beskæring af tidsintervaller.
- **Afbrudte opgaver genoptages** fra deres seneste gemmepunkt i stedet for at starte
  forfra (standardmotor).
- **Onlinevideoer:** download fra enhver side, som [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  understøtter, og transskriber, når overførslen er færdig.
- **Link til undertekstet video:** et enkelt flueben forvandler et link til `<title>-subbed.mp4`
  med de indbrændte undertekster: download, transskriber og brænd ind i en enkelt kø-opgave
  ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Live:** transskriber fra mikrofonen, eller systemlyden på Windows, mens det
  sker ([../LIVE.md](../LIVE.md)).
- **Batch-kø og overvåget mappe** til mange filer.
- **Lokal netværkstilstand:** en transskriptionsside og et OpenAI-kompatibelt API til
  de andre enheder på dit netværk ([../SERVER.md](../SERVER.md)).
- **Valgfrit, slået fra som standard:** AI-værktøjer til en færdig transskription (resumé,
  spørgsmål, tosproget SRT) og offline tekst-til-tale med stemmekloning.

Hvordan den sammenlignes med Subtitle Edit, Vibe, Buzz, noScribe og aTrain,
herunder hvornår en anden app er et bedre valg:
**[../COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Download

Nyeste version: **[releases page](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| File | For |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 eller 11, 64-bit. De fleste brugere har brug for denne. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows uden installation: pak ud og kør. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Mac-computere med Apple Silicon, macOS 14 eller nyere. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Intel-Macs, macOS 10.15 eller nyere. |

På Linux køres det fra kildekoden: [../../platform/linux/README.md](../../platform/linux/README.md).

Den medfølgende FFmpeg er en GPL-version. Den tilhørende kildekode er vedhæftet hver udgivelse i filer kaldet
`WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*`; de præcise links findes i
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

ffmpeg og yt-dlp medfølger. Ved første opstart vælger et hurtigstartvindue
talemodellen til dit sprog: Fast (Small, ca. 500 MB) eller Best
quality (op til ca. 3 GB); den downloades én gang, ved første brug. Regn med 8 GB
RAM; på en CPU tager Large-modellerne cirka 1,5–2,5 gange lydens længde,
og Small cirka halvdelen, en NVIDIA GPU er meget hurtigere. Windows-versionerne er ikke kodesignerede, og Mac-versionerne er ikke
notariserede, så SmartScreen og Gatekeeper advarer ved første opstart;
[../INSTALL.md](../INSTALL.md) viser, hvad du skal klikke på. For at opdatere, kør det
nyere installationsprogram oven på det gamle; indstillingerne bevares.

**Downloads by version** (hvert badge tæller kun den specifikke versions egen release — ældre versioner forbliver publicerede og deres downloadtal nulstilles aldrig):

[![all versions](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/total?label=all%20versions&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases)
[![v2.1.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.1.0/total?label=v2.1.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.1.0)
[![v2.0.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.0.0/total?label=v2.0.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0)
[![v1.9.3](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.3/total?label=v1.9.3&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.3)
[![v1.9.1](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.1/total?label=v1.9.1&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.1)
[![v1.9.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.0/total?label=v1.9.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.0)
[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

## Hvad der forlader din computer

Med standardindstillingerne forbliver din lyd og dine transskriptioner på din computer.
Appen bruger dog netværket til:

- at downloade en model eller en valgfri komponent den første gang, det er nødvendigt;
- dens onlineindstillinger ved opstart og et dagligt opdateringstjek på GitHub, som
  kun giver dig besked om en ny version;
- brugsstatistikker, som er slået til som standard, efter hver færdiggjort transskription: model,
  sprog, varigheder, antal ord, appversion, operativsystem, CPU og
  hukommelsesstørrelse, samt region, aldrig filens navn. Slå dem fra under
  **Help → Usage statistics**.

Lyd eller transskriptionstekst sendes kun, hvis du vælger en cloud-motor (Gemini API
eller Google Cloud Speech-to-Text) eller selv tilslutter en ekstern AI-udbyder.
**File → Work offline** stopper alt dette. Enhver forbindelse er angivet i
[../CONFIG.md](../CONFIG.md#network-use).

## Dokumentation

[Install](../INSTALL.md) · [Configuration](../CONFIG.md) ·
[Live transcription](../LIVE.md) · [Local-network mode and API](../SERVER.md) ·
[Cloud engines](../CLOUD_STT.md) · [Architecture](../ARCHITECTURE.md) ·
[Changelog](../CHANGELOG.md) · [All docs](../README.md)

## Byg fra kildekoden

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Kræver Python 3.11 eller nyere. Byggepipelines: [../BUILD.md](../BUILD.md). Tests og pull requests:
[../../CONTRIBUTING.md](../../CONTRIBUTING.md).

## Bidrag og kontakt

- **Fejl og anmodninger om funktioner:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Spørgsmål og idéer:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Alt andet:** via e-mail, gennem
  [Contact-sektionen på hjemmesiden](https://whisper-transcriber-suite.com/#contact) · ✉ [admin@whisper-transcriber-suite.com](mailto:admin@whisper-transcriber-suite.com)
- **Sikkerhedsrapporter:** [../../SECURITY.md](../../SECURITY.md)

Dette projekt følger [Contributor Covenant](../../.github/CODE_OF_CONDUCT.md).
Hvis appen sparer dig tid, vil en stjerne øverst på denne side hjælpe andre med at
finde den.

## Hvordan dette projekt er bygget

Vedligeholderen udvikler det med stor hjælp fra AI-kodningsassistenter (især Claude). Typekontroller
og unit tests skal bestås før hver commit, og CI kører dem igen på Windows og Linux efter
hvert push. I [release checklist](../RELEASE_PROCESS.md) indgår en manuel installationstest på en
rigtig maskine. Commits lavet med AI-hjælp angiver nu modellen i en `Assisted-by:`-linje; mange ældre
commits indeholder i stedet en `Co-Authored-By: Claude`-linje.

## Licens

Copyright (c) 2026 translation-robot (co-author). Projektet findes i dette repository,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
Projektets egen kildekode er underlagt [BSD 3-Clause License](../../LICENSE). Medfølgende
værktøjer, Python-runtimen og modellerne beholder deres egne licenser; se
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
