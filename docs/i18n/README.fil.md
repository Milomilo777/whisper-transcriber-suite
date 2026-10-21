<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**Libre at offline na transcription at subtitles para sa mahahabang recording sa wika mo — sa karaniwang laptop, walang account at hindi kailangang mag-upload ng audio.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![downloads](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/total?label=downloads&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [I-download para sa Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS at Linux: tingnan ang [Download](#download).

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
<b>Filipino</b>
</p>

<!-- language-links:end -->
<!-- translated from README.md at commit 66585d5 -->

</div>

## Para kanino ito

Mga gumagawa ng subtitle, tagasalin, mananaliksik, at mamamahayag na ginagawang teksto o subtitle
ang mahahabang recording (mga panayam, lektyur, usapan, video).
I-drop ang audio o video file at ang transcript ay awtomatikong gagawin sa folder kung nasaan ang file. Ang sistema na kumikilala sa boses (speech engine) ay tumatakbo mismo sa iyong computer, kaya walang
bayad bawat minuto at, kapag na-download na ang modelo, hindi na kailangan ng internet
connection.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="Ang tab na Transcribe: lugar para i-drop ang file, mga pagpipilian ng engine at wika, at mga opsyon para sa speaker label at timestamp ng bawat salita" width="80%">
</div>

## Ano ang bago sa 2.0

- **Bilis at natitirang oras:** ipinapakita sa Queue tab ang bilis ng bawat trabaho at ang tinatayang oras na natitira.
- **Subtitled video mula sa link:** i-download, i-transcribe at i-burn in ang mga subtitle sa isang tuluy-tuloy na gawain ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Transcript bilang webpage:** isang `.html` file na may search at click-to-play na gumagana offline sa kahit anong browser.
- **Malinaw na status ng Work offline:** kapag naka-on ang Work offline, ipinapakita ng status line kung ang app o ang prosesong sinimulan nito ay may network connection.
- **Isalin sa Ingles:** ang mga pananalitang hindi Ingles ay agad na isinasalin at ginagawang Ingles na subtitle sa iisang hakbang.
- **Quick start:** ang mga bagong pag-install ay nagtatanong ng tatlong bagay, at ang 18-segundong sample clip ay agad na nagpapakita ng resulta.
- **Report a problem** mula sa Help, nang walang GitHub account.
- **macOS:** app menu na may Settings (Command-comma), Light at Dark na sumusunod sa system, mga notification. **Windows:** taskbar progress at madidilim na title bar.

Buong listahan: [CHANGELOG](../CHANGELOG.md).

## Mga Tampok (Features)

- **Lokal na engine:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (default), whisper.cpp at NVIDIA Parakeet, para sa maraming wikang nakikilala
  ng Whisper. Gumagamit ng NVIDIA GPU
  sa pamamagitan ng CUDA kapag kaya nito, kung hindi ay gagamitin ang CPU.
- **Ang app sa wika mo:** Mga menu, button at mensahe sa 42 wika (isinalin ng makina
  at may markang ganoon; malugod na tinatanggap ang mga pagwawasto). Sinusunod nito
  ang wika ng iyong system, o pumili ng isa sa Mga advanced na setting. Sa ngayon,
  available ang Persian, Arabic at Hebrew sa Windows.
- **14 na format ng output:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX at
  PDF, kasama pa ang mga format na oTranscribe, ELAN, InqScribe at Express Scribe. Ang DOCX
  at PDF ay tumpak na narerender ang bawat script, at ang Persian, Arabic, at Urdu ay binabasa mula kanan pakaliwa
  nang may magkakadugtong na letra.
- **Naibabahaging webpage:** i-save ang natapos na transcript bilang isang `.html` file na
  gumagana offline sa kahit anong browser; i-click ang salita para marinig ito, maghanap, lumipat sa mga chapter.
- **Speaker labels** nang walang Hugging Face account, kasama ang word timestamps at
  time-range clipping.
- **Nagpapatuloy ang mga naantalang gawain** mula sa huling checkpoint nito sa halip na magsimula
  mula sa simula (default na engine).
- **Online na mga video:** i-download mula sa kahit anong site na sinusuportahan ng [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  at i-transcribe kapag natapos na ang pag-download.
- **Link patungo sa subtitled video:** ang isang pag-tick ay ginagawang `<title>-subbed.mp4` ang link
  kasama ang subtitle na naka-burn in: idada-download, ita-transcribe, at iba-burn in ang subtitle nang direkta mula sa pila
  ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Live:** i-transcribe ang sinasabi sa mikropono, o ang system audio sa Windows, nang
  real-time ([../LIVE.md](../LIVE.md)).
- **Batch queue at watched folder** upang sabay-sabay na maproseso ang maraming file.
- **Local-network mode:** isang transcription page at OpenAI-compatible na API para sa
  iba pang device sa network mo ([../SERVER.md](../SERVER.md)).
- **Opsyonal, off by default:** Mga AI tool para sa mga natapos nang transcript (buod,
  mga tanong, bilingual na SRT), at offline na text to voice gamit ang voice cloning.

Paghahambing sa Subtitle Edit, Vibe, Buzz, noScribe, at aTrain,
kasama ang kung kailan mas magandang piliin ang ibang app:
**[../COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Download

Pinakabagong release: **[releases page](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| File | Para sa |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 o 11, 64-bit. Ito ang kailangan ng karamihan. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows nang walang pag-install: i-unzip at patakbuhin. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Mac na may Apple silicon, macOS 14 o mas bago. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Intel na Mac, macOS 10.15 o mas bago. |

Ang Linux ay tumatakbo mula sa source: [../../platform/linux/README.md](../../platform/linux/README.md).

Ang nakapaloob na FFmpeg ay isang GPL build. Ang kaukulang source nito ay naka-attach sa bawat release bilang
mga file na `WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*`; ang mga eksaktong link ay nasa
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

Ang ffmpeg at yt-dlp ay nakapaloob na. Sa unang paglunsad, pipiliin ng quick start window
ang speech model para sa iyong wika: Fast (Small, nasa 500 MB) o Best
quality (hanggang humigit-kumulang 3 GB); ida-download ito nang minsan, sa unang paggamit. Maglaan ng 8 GB
ng RAM; sa CPU, inaabot ang mga Large na modelo ng tinatayang 1.5–2.5 na beses ng kabuuang haba ng
audio, samantalang ang mga Small na modelo ay umaabot lamang ng kalahati nito, mas mabilis nang malaki ang NVIDIA GPU. Ang mga build para sa Windows ay walang code-sign at ang mga build sa Mac ay hindi
notarized, kaya magbibigay ng babala ang SmartScreen at Gatekeeper sa unang paglunsad;
ipinapakita ng [../INSTALL.md](../INSTALL.md) kung ano ang dapat i-click. Upang mag-update, patakbuhin ang mas
bagong installer sa ibabaw ng luma; mananatili ang mga setting.

**Mga pag-download batay sa bersyon** (binibilang lamang ng bawat badge ang sariling release ng
bersyong iyon — ang mga mas lumang bersyon ay nananatiling naka-publish at ang mga bilang nila ay hindi kailanman
nare-reset):

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

## Anong datos ang lumalabas sa iyong computer

Gamit ang mga default na setting, mananatili sa computer mo ang audio at mga transcript mo.
Ginagamit lang ng app ang network para sa:

- pag-download ng model o opsyonal na bahagi sa unang beses na kakailanganin ito;
- mga online setting nito sa pag-startup at araw-araw na pagsuri ng update sa GitHub, na
  magsasabi lang sa iyo tungkol sa bagong bersyon;
- istatistika ng paggamit, naka-on by default, na ipinapadala matapos ang bawat transcription: model,
  wika, haba ng oras, bilang ng salita, bersyon ng app, operating system, uri ng CPU at
  kapasidad ng memory, at rehiyon, ngunit hinding-hindi isasama ang pangalan ng iyong file. I-off ang mga ito sa
  **Help → Usage statistics**.

Ipinapadala lang ang audio o teksto ng transcript kung pipili ka ng cloud engine (Gemini API
o Google Cloud Speech-to-Text) o kung ikaw mismo ang magkokonekta ng remote na provider ng AI.
Pinapahinto ng **File → Work offline** ang lahat ng ito. Ang kumpletong listahan ng mga koneksyon na ginagamit ay matatagpuan sa
[../CONFIG.md](../CONFIG.md#network-use).

## Dokumentasyon

[Install](../INSTALL.md) · [Configuration](../CONFIG.md) ·
[Live transcription](../LIVE.md) · [Local-network mode and API](../SERVER.md) ·
[Cloud engines](../CLOUD_STT.md) · [Architecture](../ARCHITECTURE.md) ·
[Changelog](../CHANGELOG.md) · [All docs](../README.md)

## Build from source

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Kinakailangan ang Python 3.11 o mas bago. Build pipelines: [../BUILD.md](../BUILD.md). Mga test at pull request:
[../../CONTRIBUTING.md](../../CONTRIBUTING.md).

## Contributing at contact

- **Bugs at feature requests:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Mga katanungan at ideya:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Iba pang katanungan:** sa pamamagitan ng email, gamit ang
  [Contact section ng website](https://whisper-transcriber-suite.com/#contact) · ✉ [admin@whisper-transcriber-suite.com](mailto:admin@whisper-transcriber-suite.com)
- **Mga ulat sa seguridad:** [../../SECURITY.md](../../SECURITY.md)

Sumusunod ang proyektong ito sa [Contributor Covenant](../../.github/CODE_OF_CONDUCT.md).
Kung nakatulong ang app para makatipid ka ng oras, ang pagbibigay ng Star sa tuktok ng pahinang ito ay nakakatulong sa iba
para mahanap ito.

## Paano binuo ang proyektong ito

Binuo ang application na ito ng maintainer sa tulong ng mga AI coding assistant (pangunahin na ang Claude). Dapat pumasa
ang mga type check at unit test bago ang bawat commit, at pinapagana itong muli ng CI sa Windows at Linux pagkatapos ng
bawat push. Kasama sa [release checklist](../RELEASE_PROCESS.md) ang isang manwal na test ng pag-install sa isang
totoong computer. Ang mga commit na ginawa sa tulong ng AI ay inilalagay na ngayon ang pangalan ng AI model sa `Assisted-by:` line; marami sa mga
mas luma ay naglalaman ng `Co-Authored-By: Claude` bilang pamalit.

## Lisensya

Copyright (c) 2026 translation-robot (co-author). Ang proyekto ay matatagpuan sa repositoryong ito,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
Ang mismong source ng proyekto ay nasa ilalim ng [BSD 3-Clause License](../../LICENSE). Ang mga nakapaloob na
tool, ang Python runtime at ang mga modelo ay pinapanatili ang kani-kanilang mga lisensya; tingnan ang
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
