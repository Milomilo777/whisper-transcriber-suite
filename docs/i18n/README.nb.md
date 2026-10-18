<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**Gratis, frakoblet transkripsjon og teksting for lange opptak på ditt språk — på en vanlig bærbar PC, uten konto og uten lydopplasting.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [⬇ Last ned for Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS og Linux: se [Nedlasting](#download).

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
<a href="README.da.md">Dansk</a> ·
<b>Norsk bokmål</b> ·
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

## Hvem den er for

Tekstere, oversettere, forskere og journalister som gjør lange
opptak (intervjuer, forelesninger, taler, videoer) om til tekst eller undertekster.
Dra og slipp en lyd- eller videofil, så lagres transkripsjonen i samme mappe. Talemotoren kjører på din egen datamaskin, så det er
ingen kostnad per minutt, og når modellen er lastet ned, kreves ingen
internettilkobling.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="Fanen Transcribe: et område for å slippe filer, valg av motor og språk, alternativer for talermerking og tidsstempler per ord" width="80%">
</div>

## Hva er nytt i 2.0

- **Hastighet og gjenværende tid:** Kø-fanen viser hver jobbs hastighet og en omtrentlig gjenværende tid.
- **Tekstet video fra en lenke:** last ned, transkriber og brenn inn undertekstene i én jobb ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Transkripsjon som nettside:** én `.html`-fil med søk og klikk-for-å-spille som fungerer frakoblet i enhver nettleser.
- **Sjekk status for frakoblet modus:** med Arbeid frakoblet slått på, viser en statuslinje om appen eller en prosess den startet har nettverkstilkobling.
- **Oversett til engelsk:** tale på andre språk blir til engelske undertekster i ett trinn.
- **Hurtigstart:** nye installasjoner stiller tre spørsmål, og et 18-sekunders prøveklipp viser et resultat med en gang.
- **Rapporter et problem** fra Hjelp, uten en GitHub-konto.
- **macOS:** appmeny med Innstillinger (Kommando-komma), Lys og Mørk som følger systemet, varsler. **Windows:** fremdrift på oppgavelinjen og mørke tittellinjer.

Fullstendig liste: [CHANGELOG](../CHANGELOG.md).

## Funksjoner

- **Lokale motorer:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (standard), whisper.cpp og NVIDIA Parakeet, for de mange språkene Whisper
  gjenkjenner. Bruker en NVIDIA-GPU
  via CUDA når den kan, ellers CPU-en.
- **Appen på ditt språk:** Menyer, knapper og meldinger på 42 språk (maskinoversatt
  og merket som det; rettelser er velkomne). Den følger systemspråket ditt, eller du
  kan velge et i Avanserte innstillinger. Persisk, arabisk og hebraisk tilbys
  foreløpig på Windows.
- **14 utdataformater:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX og
  PDF, pluss formatene til oTranscribe, ELAN, InqScribe og Express Scribe. DOCX
  og PDF tegner hvert skript, og persisk, arabisk og urdu leses fra høyre til venstre
  med sammenhengende bokstaver.
- **Delbar nettside:** lagre en ferdig transkripsjon som én `.html`-fil som
  fungerer frakoblet i enhver nettleser; klikk på et ord for å høre det, søk, hopp til
  kapitler.
- **Gjenkjenning av talere** uten en Hugging Face-konto, pluss ordtidsstempler og
  tidsbeskjæring.
- **Avbrutte jobber gjenopptas** fra deres siste sjekkpunkt i stedet for å starte
  på nytt (standard motor).
- **Videoer på nett:** last ned fra hvilken som helst side [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  støtter og transkriber når nedlastingen er ferdig.
- **Lenke til tekstet video:** en avkrysning gjør en lenke om til `<title>-subbed.mp4`
  med undertekstene innbrent: last ned, transkriber og brenn inn i én enkelt jobb i køen
  ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Direkte:** transkriber en mikrofon, eller systemlyden på Windows, mens det
  skjer ([../LIVE.md](../LIVE.md)).
- **Jobbkø (batch) og overvåket mappe** for mange filer.
- **Lokalnettverksmodus:** en transkripsjonsside og et OpenAI-kompatibelt API for
  de andre enhetene på nettverket ditt ([../SERVER.md](../SERVER.md)).
- **Valgfritt, av som standard:** KI-verktøy for en ferdig transkripsjon (sammendrag,
  spørsmål, tospråklig SRT), og frakoblet tekst-til-tale med stemmekloning.

Hvordan den sammenlignes med Subtitle Edit, Vibe, Buzz, noScribe og aTrain,
inkludert når en annen app er et bedre valg:
**[../COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Nedlasting

Siste utgivelse: **[utgivelsessiden](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| Fil | For |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 eller 11, 64-biters. De fleste vil ha denne. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows uten å installere: pakk ut og kjør. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Macer med Apple Silicon, macOS 14 eller nyere. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Intel-Macer, macOS 10.15 eller nyere. |

Linux kjører fra kildekoden: [../platform/linux/README.md](../../platform/linux/README.md).

Den medfølgende FFmpeg er en GPL-bygg. Den tilhørende kildekoden er vedlagt hver utgivelse som
`WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*`-filer; de nøyaktige lenkene er i
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

ffmpeg og yt-dlp følger med. Ved første oppstart velger et hurtigstartvindu
talemodellen for ditt språk: Rask (Small, omtrent 500 MB) eller Beste
kvalitet (opptil omtrent 3 GB); den lastes ned én gang, ved første gangs bruk. Beregn 8 GB RAM; på en CPU tar Large-modellene omtrent 1,5–2,5 ganger lengden av
lyden, og Small omtrent halvparten; en NVIDIA-GPU er mye raskere. Windows-byggene er ikke kodesignert, og Mac-byggene er ikke
notarisert, så SmartScreen og Gatekeeper advarer ved første oppstart;
[../INSTALL.md](../INSTALL.md) viser hva du skal klikke på. For å oppdatere, kjører du ganske enkelt det
nyere installasjonsprogrammet over det gamle; innstillingene beholdes.

**Nedlastinger etter versjon** (hvert merke teller kun den versjonens egen
utgivelse — eldre versjoner forblir publisert og tellingene deres blir aldri
nullstilt):

[![v2.1.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.1.0/total?label=v2.1.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.1.0)
[![v2.0.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.0.0/total?label=v2.0.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0)
[![v1.9.3](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.3/total?label=v1.9.3&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.3)
[![v1.9.1](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.1/total?label=v1.9.1&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.1)
[![v1.9.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.0/total?label=v1.9.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.0)
[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

## Hva forlater datamaskinen din?

Med standardinnstillingene forblir lyden din og transkripsjonene dine på datamaskinen.
Appen bruker imidlertid nettverket til:

- å laste ned en modell eller en valgfri komponent første gang den trengs;
- dens nettbaserte innstillinger ved oppstart og en daglig oppdateringssjekk på GitHub, som
  kun forteller deg om en ny versjon;
- bruksstatistikk, på som standard, etter hver ferdigstilte transkripsjon: modell,
  språk, varigheter, ordtelling, appversjon, operativsystem, CPU og
  minnestørrelse, samt region, aldri filens navn. Slå dem av under
  **Help → Usage statistics**.

Lyd eller transkripsjonstekst sendes kun hvis du velger en skybasert motor (Gemini API
eller Google Cloud Speech-to-Text) eller selv kobler til en ekstern KI-leverandør.
**File → Work offline** stopper alt dette. Hver tilkobling er listet opp i
[../CONFIG.md](../CONFIG.md#network-use).

## Dokumentasjon

[Installasjon](../INSTALL.md) · [Konfigurasjon](../CONFIG.md) ·
[Direkte transkripsjon](../LIVE.md) · [Lokalnettverksmodus og API](../SERVER.md) ·
[Skybaserte motorer](../CLOUD_STT.md) · [Arkitektur](../ARCHITECTURE.md) ·
[Endringslogg](../CHANGELOG.md) · [All dokumentasjon](../README.md)

## Bygg fra kildekode

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Krever Python 3.11 eller nyere. Bygge-pipelines: [../BUILD.md](../BUILD.md). Tester og pull-forespørsler:
[../../CONTRIBUTING.md](../../CONTRIBUTING.md).

## Bidrag og kontakt

- **Feil og funksjonsforespørsler:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Spørsmål og ideer:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Alt annet:** via e-post, gjennom
  [kontaktseksjonen på nettstedet](https://whisper-transcriber-suite.com/#contact)
- **Sikkerhetsrapporter:** [../../SECURITY.md](../../SECURITY.md)

Dette prosjektet følger [Contributor Covenant](../../.github/CODE_OF_CONDUCT.md).
Hvis appen sparer deg for tid, vil en stjerne øverst på denne siden hjelpe andre med å
finne den.

## Hvordan dette prosjektet er bygget

Vedlikeholderen utvikler det med mye hjelp fra KI-kodeassistenter (hovedsakelig Claude). Type-sjekker
og enhetstestene må bestå før hver 'commit', og CI kjører dem igjen på Windows og Linux etter
hver 'push'. [Utgivelsessjekklisten](../RELEASE_PROCESS.md) inkluderer en manuell installasjonstest på en
ekte maskin. Commits gjort med KI-hjelp navngir nå modellen i en `Assisted-by:`-linje; mange eldre
commits bærer i stedet en `Co-Authored-By: Claude`-linje.

## Lisens

Opphavsrett (c) 2026 translation-robot (medforfatter). Prosjektet bor i dette depotet,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
Prosjektets egen kildekode er underlagt [BSD 3-Clause License](../../LICENSE). Medfølgende
verktøy, Python-kjøretidsmiljøet og modellene beholder sine egne lisenser; se
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
