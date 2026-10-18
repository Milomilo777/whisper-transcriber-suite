<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**Gratis, offline transcriptie en ondertiteling voor lange opnames in jouw taal — op een gewone laptop, zonder account en zonder je audio te uploaden.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Download voor Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS en Linux: zie [Download](#download).

<!-- language-links:start -->

<p>
<a href="../../README.md">English</a> ·
<a href="README.de.md">Deutsch</a> ·
<a href="README.fr.md">Français</a> ·
<a href="README.es.md">Español</a> ·
<a href="README.it.md">Italiano</a> ·
<a href="README.pt-BR.md">Português (Brasil)</a> ·
<a href="README.pt.md">Português (Portugal)</a> ·
<b>Nederlands</b> ·
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
<a href="README.da.md">Dansk</a> ·
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

## Voor wie is het

Ondertitelaars, vertalers, onderzoekers en journalisten die lange 
opnames (interviews, hoorcolleges, lezingen, video's) omzetten in tekst of ondertiteling.
Sleep een audio- of videobestand naar binnen en de transcriptie wordt er direct naast geschreven. De spraakherkenning draait op je eigen computer, dus er zijn
geen kosten per minuut en, zodra het model is gedownload, is er geen internetverbinding
nodig.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="Het tabblad Transcribe: een plek om bestanden neer te zetten, keuzes voor engine en taal, opties voor sprekerlabels en tijdstempels per woord" width="80%">
</div>

## Wat is er nieuw in 2.0

- **Snelheid en resterende tijd:** het Queue-tabblad toont de snelheid van elke taak en een geschatte resterende tijd.
- **Ondertitelde video via een link:** download, transcribeer en brand de ondertiteling in als één taak ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Transcriptie als webpagina:** één `.html`-bestand met zoekfunctie en klik-om-af-te-spelen dat offline in elke browser werkt.
- **Werk offline en controleer het:** met Work offline ingeschakeld, toont een statusregel of de app of een gestart proces een netwerkverbinding heeft.
- **Vertaal naar het Engels:** niet-Engelse spraak wordt in één keer omgezet naar Engelse ondertiteling.
- **Snelle start:** nieuwe installaties stellen drie vragen, en een voorbeeldfragment van 18 seconden laat direct het resultaat zien.
- **Meld een probleem** vanuit Help, zonder een GitHub-account.
- **macOS:** app-menu met Settings (Command-komma), Licht en Donker thema's die het systeem volgen, meldingen. **Windows:** voortgang in de taakbalk en donkere titelbalken.

Volledige lijst: [CHANGELOG](../CHANGELOG.md).

## Functies

- **Lokale engines:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (standaard), whisper.cpp en NVIDIA Parakeet, voor de vele talen die Whisper
  herkent. Gebruikt een NVIDIA GPU
  via CUDA wanneer mogelijk, anders de CPU.
- **De app in jouw taal:** Menu's, knoppen en meldingen in 42 talen (automatisch
  vertaald en als zodanig gemarkeerd; correcties zijn welkom). De app volgt je
  systeemtaal, of je kiest er een in de Geavanceerde instellingen. Perzisch,
  Arabisch en Hebreeuws worden voorlopig op Windows aangeboden.
- **14 uitvoerformaten:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX en
  PDF, plus de oTranscribe, ELAN, InqScribe en Express Scribe formaten. DOCX
  en PDF renderen elk schrift, en Perzisch, Arabisch en Urdu lezen van rechts naar links
  met verbonden letters.
- **Deelbare webpagina:** sla een voltooide transcriptie op als één `.html`-bestand dat
  offline werkt in elke browser; klik op een woord om het te horen, zoek, spring naar
  hoofdstukken.
- **Sprekerslabels** zonder een Hugging Face-account, plus woordtijdstempels en
  tijdsbereik bijsnijden.
- **Onderbroken taken hervatten** vanaf hun laatste controlepunt in plaats van opnieuw
  te beginnen (standaard engine).
- **Online video's:** download van elke site die [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  ondersteunt en transcribeer wanneer het downloaden is voltooid.
- **Link naar ondertitelde video:** één vinkje verandert een link in `<title>-subbed.mp4`
  met de ingebrande ondertiteling: download, transcribeer en brand in als één taak in de wachtrij
  ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Live:** transcribeer een microfoon, of de systeemaudio op Windows, terwijl het
  gebeurt ([../LIVE.md](../LIVE.md)).
- **Batch-wachtrij en bewaakte map** voor veel bestanden.
- **Lokale netwerkmodus:** een transcriptiepagina en een OpenAI-compatibele API voor
  de andere apparaten in je netwerk ([../SERVER.md](../SERVER.md)).
- **Optioneel, standaard uitgeschakeld:** AI-tools voor een voltooide transcriptie (samenvatting,
  vragen, tweetalige SRT), en offline tekst-naar-spraak met stemklonen.

Hoe het zich verhoudt tot Subtitle Edit, Vibe, Buzz, noScribe en aTrain,
inclusief wanneer een andere app de betere keuze is:
**[../COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Download

Nieuwste release: **[releases page](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| File | For |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 of 11, 64-bit. De meeste mensen hebben deze nodig. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows zonder installatie: uitpakken en uitvoeren. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Macs met Apple silicon, macOS 14 of nieuwer. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Intel Macs, macOS 10.15 of nieuwer. |

Voor Linux bouw je vanuit de broncode: [../../platform/linux/README.md](../../platform/linux/README.md).

De meegeleverde FFmpeg is een GPL-build. De bijbehorende broncode is bij elke release gevoegd als
`WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*` bestanden; de exacte links staan in
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

ffmpeg en yt-dlp zijn meegeleverd. Bij de eerste start kiest een snelstartvenster
het spraakmodel voor jouw taal: Fast (Small, ongeveer 500 MB) of Best
quality (tot ongeveer 3 GB); het wordt één keer gedownload, bij het eerste gebruik. Houd rekening met 8 GB
aan RAM; op een CPU nemen de Large modellen ongeveer 1,5–2,5 keer de audiolengte in beslag en Small ongeveer de helft, een NVIDIA GPU is veel sneller. De Windows-builds zijn niet digitaal ondertekend en de Mac-builds zijn niet
genotariseerd, dus SmartScreen en Gatekeeper waarschuwen bij de eerste start;
[../INSTALL.md](../INSTALL.md) laat zien waarop je moet klikken. Om te updaten, voer je het
nieuwere installatieprogramma uit over de oude; instellingen blijven behouden.

**Downloads by version** (elke badge telt alleen de eigen release van die versie — oudere versies blijven gepubliceerd en hun tellingen worden nooit gereset):

[![v2.1.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.1.0/total?label=v2.1.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.1.0)
[![v2.0.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.0.0/total?label=v2.0.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0)
[![v1.9.3](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.3/total?label=v1.9.3&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.3)
[![v1.9.1](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.1/total?label=v1.9.1&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.1)
[![v1.9.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.0/total?label=v1.9.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.0)
[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

## Wat je computer verlaat

Met de standaardinstellingen blijven je audio en transcripties op je computer.
De app gebruikt het netwerk wel voor:

- het downloaden van een model of een optioneel onderdeel de eerste keer dat het nodig is;
- de online instellingen bij het opstarten en een dagelijkse updatecontrole op GitHub, die
  je alleen informeert over een nieuwe versie;
- gebruiksstatistieken, standaard ingeschakeld, na elke voltooide transcriptie: model,
  taal, duren, aantal woorden, app-versie, besturingssysteem, CPU en
  geheugengrootte, en regio, nooit de bestandsnaam. Schakel ze uit via
  **Help → Usage statistics**.

Audio of transcriptietekst wordt alleen verzonden als je een cloud-engine kiest (Gemini API
of Google Cloud Speech-to-Text) of zelf een externe AI-provider koppelt.
**File → Work offline** stopt dit alles. Elke verbinding wordt vermeld in
[../CONFIG.md](../CONFIG.md#network-use).

## Documentatie

[Install](../INSTALL.md) · [Configuration](../CONFIG.md) ·
[Live transcription](../LIVE.md) · [Local-network mode and API](../SERVER.md) ·
[Cloud engines](../CLOUD_STT.md) · [Architecture](../ARCHITECTURE.md) ·
[Changelog](../CHANGELOG.md) · [All docs](../README.md)

## Bouwen vanuit de broncode

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Vereist Python 3.11 of nieuwer. Bouwpijplijnen: [../BUILD.md](../BUILD.md). Tests en pull requests:
[../../CONTRIBUTING.md](../../CONTRIBUTING.md).

## Bijdragen en contact

- **Bugs en functieverzoeken:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Vragen en ideeën:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Al het andere:** per e-mail, via de
  [Contact section van de website](https://whisper-transcriber-suite.com/#contact)
- **Beveiligingsmeldingen:** [../../SECURITY.md](../../SECURITY.md)

Dit project volgt het [Contributor Covenant](../../.github/CODE_OF_CONDUCT.md).
Als de app je tijd bespaart, helpt een Ster bovenaan deze pagina andere mensen
om hem te vinden.

## Hoe dit project is gebouwd

De beheerder ontwikkelt het met veel hulp van AI-codeerassistenten (voornamelijk Claude). Typecontroles
en de unit tests moeten slagen voor elke commit, en CI voert ze opnieuw uit op Windows en Linux na
elke push. De [release checklist](../RELEASE_PROCESS.md) bevat een handmatige installatietest op een
echte machine. Commits gemaakt met AI-hulp vermelden nu het model in een `Assisted-by:` regel; veel oudere
hebben in plaats daarvan een `Co-Authored-By: Claude` regel.

## Licentie

Copyright (c) 2026 translation-robot (co-author). Het project bevindt zich in deze repository,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
De eigen broncode van het project valt onder de [BSD 3-Clause License](../../LICENSE). Meegeleverde
tools, de Python-runtime en de modellen behouden hun eigen licenties; zie
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
