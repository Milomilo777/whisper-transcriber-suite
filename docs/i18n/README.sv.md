<div align="center">

<img src="../img/hero.png" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**Gratis offline-transkription och undertexter för långa inspelningar på ditt språk — på en vanlig bärbar dator, utan konto och utan att ladda upp ljudet.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Ladda ner för Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS och Linux: se [Ladda ner](#download).

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
<b>Svenska</b> ·
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

## Vem det är för

Undertextare, översättare, forskare och journalister som omvandlar långa
inspelningar (intervjuer, föreläsningar, tal, videor) till text eller undertexter.
Dra in en ljud- eller videofil, så skrivs transkriptionen bredvid den. Talmotorn körs på din egen dator, så det kostar
inget per minut och, när modellen väl är nedladdad, krävs ingen
internetanslutning.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="Fliken Transcribe: en yta att släppa filer på, val av motor och språk, alternativ för talaretiketter och tidsstämplar per ord" width="80%">
</div>

## Nyheter i 2.0

- **Hastighet och återstående tid:** fliken Queue (Kö) visar hastigheten för varje jobb och en ungefärlig återstående tid.
- **Undertextad video från en länk:** ladda ner, transkribera och bränn in undertexterna i ett enda jobb ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Transkription som webbsida:** en enda `.html`-fil med sökfunktion och klicka-för-att-spela som fungerar offline i alla webbläsare.
- **Offline-läge du kan kontrollera:** när Work offline är aktiverat visar en statusrad om appen eller en process den startat har en nätverksanslutning.
- **Översätt till engelska:** tal som inte är på engelska omvandlas till engelska undertexter i ett enda pass.
- **Snabbstart:** vid nyinstallation ställs tre frågor, och ett 18 sekunders provklipp visar resultatet direkt.
- **Rapportera ett problem** från Help, utan GitHub-konto.
- **macOS:** appmeny med Settings (Kommando-komma), ljust och mörkt tema som följer systemet, notiser. **Windows:** förloppsindikator i aktivitetsfältet och mörka titelrader.

Fullständig lista: [CHANGELOG](../CHANGELOG.md).

## Funktioner

- **Lokala motorer:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (standard), whisper.cpp och NVIDIA Parakeet, för de många språk Whisper
  stöder. Använder en NVIDIA GPU
  via CUDA när det är möjligt, annars CPU:n.
- **Appen på ditt språk:** Menyer, knappar och meddelanden på 42 språk
  (maskinöversatta och markerade som sådana; rättelser är välkomna). Appen följer
  systemspråket, eller så väljer du ett under Avancerade inställningar. Persiska,
  arabiska och hebreiska erbjuds tills vidare på Windows.
- **14 utdataformat:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX och
  PDF, plus formaten oTranscribe, ELAN, InqScribe och Express Scribe. DOCX
  och PDF renderar alla skriftsystem, och persiska, arabiska och urdu läses från höger till vänster
  med sammanbundna bokstäver.
- **Delbar webbsida:** spara en färdig transkription som en `.html`-fil som
  fungerar offline i alla webbläsare; klicka på ett ord för att höra det, sök, hoppa till
  kapitel.
- **Talaretiketter** utan ett Hugging Face-konto, plus tidsstämplar per ord och
  klippning av tidsintervall.
- **Avbrutna jobb återupptas** från sin senaste kontrollpunkt istället för att börja
  om (standardmotor).
- **Onlinevideor:** ladda ner från valfri webbplats som [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  stöder, och transkribera när nedladdningen är klar.
- **Länk till undertextad video:** en kryssruta omvandlar en länk till `<title>-subbed.mp4`
  med inbrända undertexter: ladda ner, transkribera och bränn in i ett enda köjobb
  ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Live:** transkribera från mikrofonen, eller systemljudet på Windows, medan det
  händer ([../LIVE.md](../LIVE.md)).
- **Batch-kö och övervakad mapp** för många filer.
- **Lokalt nätverksläge:** en transkriptionssida och ett OpenAI-kompatibelt API för
  andra enheter i ditt nätverk ([../SERVER.md](../SERVER.md)).
- **Valfritt, inaktiverat som standard:** AI-verktyg för en färdig transkription (sammanfattning,
  frågor, tvåspråkig SRT) och offline text-till-tal med röstkloning.

Hur det står sig mot Subtitle Edit, Vibe, Buzz, noScribe och aTrain,
inklusive när en annan app är ett bättre val:
**[../COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Ladda ner

Senaste versionen: **[releases page](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| File | For |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 eller 11, 64-bitars. De flesta användare behöver den här. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows utan installation: packa upp och kör. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Mac-datorer med Apple Silicon, macOS 14 eller nyare. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Intel-Mac-datorer, macOS 10.15 eller nyare. |

På Linux körs det från källkoden: [../../platform/linux/README.md](../../platform/linux/README.md).

Den medföljande FFmpeg är en GPL-version. Tillhörande källkod bifogas varje release i filer som heter
`WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*`; de exakta länkarna finns i
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

ffmpeg och yt-dlp medföljer. Vid första uppstarten väljer ett snabbstartfönster
språkmodellen för ditt språk: Fast (Small, cirka 500 MB) eller Best
quality (upp till cirka 3 GB); den laddas ner en gång, vid första användningen. Räkna med 8 GB
RAM; på en CPU tar Large-modellerna ungefär 1,5–2,5 gånger ljudets längd
och Small ungefär hälften, en NVIDIA GPU är mycket snabbare. Windows-versionerna är inte kodsignerade och Mac-versionerna är inte
notariserade, så SmartScreen och Gatekeeper varnar vid första starten;
[../INSTALL.md](../INSTALL.md) visar vad du ska klicka på. För att uppdatera, kör den
nyare installationsfilen över den gamla; inställningarna bevaras.

**Downloads by version** (varje badge räknar bara den specifika versionens egen release — äldre versioner förblir publicerade och deras nedladdningsantal nollställs aldrig):

[![v2.1.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.1.0/total?label=v2.1.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.1.0)
[![v2.0.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.0.0/total?label=v2.0.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0)
[![v1.9.3](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.3/total?label=v1.9.3&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.3)
[![v1.9.1](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.1/total?label=v1.9.1&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.1)
[![v1.9.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.0/total?label=v1.9.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.0)
[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

## Vad som lämnar din dator

Med standardinställningarna stannar ditt ljud och dina transkriptioner på din dator.
Appen använder nätverket för:

- nedladdning av en modell eller en valfri komponent den första gången den behövs;
- dess onlineinställningar vid uppstart och en daglig uppdateringskontroll på GitHub, som
  bara meddelar dig om en ny version;
- användningsstatistik, aktiverat som standard, efter varje slutförd transkription: modell,
  språk, tidslängd, antal ord, appversion, operativsystem, CPU och
  minnesstorlek, och region, aldrig filens namn. Stäng av detta under
  **Help → Usage statistics**.

Ljud eller transkriptionstext skickas endast om du väljer en molnmotor (Gemini API
eller Google Cloud Speech-to-Text) eller ansluter till en extern AI-leverantör själv.
**File → Work offline** stoppar allt detta. Varje anslutning finns listad i
[../CONFIG.md](../CONFIG.md#network-use).

## Dokumentation

[Install](../INSTALL.md) · [Configuration](../CONFIG.md) ·
[Live transcription](../LIVE.md) · [Local-network mode and API](../SERVER.md) ·
[Cloud engines](../CLOUD_STT.md) · [Architecture](../ARCHITECTURE.md) ·
[Changelog](../CHANGELOG.md) · [All docs](../README.md)

## Bygg från källkoden

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Kräver Python 3.11 eller nyare. Byggpipelines: [../BUILD.md](../BUILD.md). Tester och pull requests:
[../../CONTRIBUTING.md](../../CONTRIBUTING.md).

## Bidra och kontakt

- **Buggar och funktionsförfrågningar:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Frågor och idéer:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Allt annat:** via e-post, genom
  [Contact-sektionen på webbplatsen](https://whisper-transcriber-suite.pages.dev/#contact)
- **Säkerhetsrapporter:** [../../SECURITY.md](../../SECURITY.md)

Detta projekt följer [Contributor Covenant](../../.github/CODE_OF_CONDUCT.md).
Om appen sparar tid åt dig hjälper en stjärna högst upp på den här sidan andra att
hitta den.

## Hur projektet byggs

Underhållaren utvecklar det med stor hjälp från AI-kodassistenter (främst Claude). Typkontroller
och enhetstester måste passera innan varje commit, och CI kör dem igen på Windows och Linux efter
varje push. I [release checklist](../RELEASE_PROCESS.md) ingår ett manuellt installationstest på en
riktig dator. Commits gjorda med AI-hjälp anger nu modellen i en `Assisted-by:`-rad; många äldre
innehåller istället raden `Co-Authored-By: Claude`.

## Licens

Copyright (c) 2026 translation-robot (co-author). Projektet finns i detta repository,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
Projektets egen källkod lyder under [BSD 3-Clause License](../../LICENSE). Medföljande
verktyg, Python-körtiden och modellerna behåller sina egna licenser; se
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
