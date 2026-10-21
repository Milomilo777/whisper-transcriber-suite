<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: звук улази, текст излази. Бесплатна транскрипција отвореног кода која покреће Whisper на вашем рачунару." width="100%">

# Whisper Transcriber Suite

**Бесплатна, офлајн транскрипција и титлови за дуге снимке на вашем језику — на обичном лаптопу, без налога и без отпремања звука.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![downloads](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/total?label=downloads&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Преузмите за Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS и Linux: погледајте [Преузимање](#download).

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
<b>Српски</b> ·
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

## За кога је ово

За ауторе титлова, преводиоце, истраживаче и новинаре који дуге снимке (интервјуе, предавања, говоре, видео записе) претварају у текст или титлове.
Убаците аудио или видео фајл и транскрипт ће бити исписан поред њега. Систем за препознавање говора ради на вашем рачунару, тако да
нема трошкова по минуту, а након преузимања модела, није потребна интернет веза.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="Картица Transcribe: место за убацивање фајлова, избор система и језика, опције за ознаке говорника и временске ознаке за сваку реч" width="80%">
</div>

## Шта је ново у 2.0

- **Брзина и преостало време:** картица Queue приказује брзину сваког посла и грубо преостало време.
- **Титлован видео са линка:** преузимање, транскрипција и уграђивање титлова као један посао ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Транскрипт као веб страница:** један `.html` фајл са претрагом и функцијом "кликни за слушање" који ради офлајн у било ком прегледачу.
- **Проверљив рад ван мреже:** са укљученим Work offline, статусна линија показује да ли апликација или процес који је она покренула има мрежну везу.
- **Преведи на енглески:** говор који није на енглеском постаје енглески титл у једном пролазу.
- **Брзи почетак:** нове инсталације постављају три питања, а пробни снимак од 18 секунди одмах приказује резултат.
- **Пријавите проблем** из Help-а, без GitHub налога.
- **macOS:** мени апликације са Settings (Command-зарез), Light и Dark модом који прате систем, обавештења. **Windows:** напредак на таскбару и тамне насловне траке.

Комплетна листа: [CHANGELOG](../CHANGELOG.md).

## Функције

- **Локални системи:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (подразумевано), whisper.cpp и NVIDIA Parakeet, за многе језике које Whisper
  препознаје. Користи NVIDIA графичку картицу (GPU)
  кроз CUDA када је то могуће, иначе процесор (CPU).
- **Апликација на вашем језику:** Менији, дугмад и поруке на 42 језика (машински
  преведено и тако означено; исправке су добродошле). Прати језик система, а језик
  можете изабрати и у Напредним подешавањима. Персијски, арапски и хебрејски су за
  сада доступни на систему Windows.
- **14 излазних формата:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX и
  PDF, плус oTranscribe, ELAN, InqScribe и Express Scribe формати. DOCX
  и PDF цртају свако писмо, а персијски, арапски и урду читају се здесна налево
  са спојеним словима.
- **Веб страница за дељење:** сачувајте готов транскрипт као један `.html` фајл који
  ради офлајн у било ком прегледачу; кликните на реч да бисте је чули, претражујте, прескачите на поглавља.
- **Ознаке говорника** без Hugging Face налога, плус временске ознаке за сваку реч и
  исецање временског опсега.
- **Прекинути послови се настављају** са последње сачуване тачке уместо да почињу
  из почетка (подразумевани систем).
- **Онлајн видео записи:** преузмите са било ког сајта који [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  подржава и транскрибујте када се преузимање заврши.
- **Линк до титлованог видеа:** једна квачица претвара линк у `<title>-subbed.mp4`
  са уграђеним титловима: преузмите, транскрибујте и уградите у једном послу из реда чекања
  ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Уживо:** транскрибујте микрофон, или системски звук на Windows-у, док се
  дешава ([../LIVE.md](../LIVE.md)).
- **Групни ред чекања и надгледана фасцикла** за много фајлова.
- **Режим локалне мреже:** страница за транскрипцију и OpenAI-компатибилан API за
  друге уређаје на вашој мрежи ([../SERVER.md](../SERVER.md)).
- **Опционо, подразумевано искључено:** AI алати за готов транскрипт (сажетак,
  питања, двојезични SRT), и офлајн текст у глас са клонирањем гласа.

Како се упоређује са Subtitle Edit, Vibe, Buzz, noScribe и aTrain,
укључујући и ситуације када је друга апликација бољи избор:
**[../COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Преузимање

Најновија верзија: **[страница са издањима](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| Фајл | За кога |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 или 11, 64-бита. Већина људи жели ово. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows без инсталације: распакујте и покрените. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Mac рачунари са Apple silicon чиповима, macOS 14 или новији. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Intel Mac рачунари, macOS 10.15 или новији. |

Linux се покреће из изворног кода: [../../platform/linux/README.md](../../platform/linux/README.md).

Укључени FFmpeg је GPL верзија. Његов одговарајући изворни код је приложен уз свако издање као
`WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*` фајлови; тачни линкови су у
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

ffmpeg и yt-dlp су укључени у пакет. При првом покретању прозор за брзи почетак бира
модел говора за ваш језик: Fast (Мали, око 500 MB) или Best
quality (до око 3 GB); преузима се једном, приликом првог коришћења. Планирајте 8 GB
RAM-а; на процесору (CPU) великим моделима је потребно око 1,5–2,5 пута више времена од
трајања самог аудио снимка, а малим моделима око половине тог времена, NVIDIA GPU је много бржи. Windows верзије немају дигитални потпис, а Mac верзије нису
нотаризоване, тако да SmartScreen и Gatekeeper упозоравају при првом покретању;
[../INSTALL.md](../INSTALL.md) показује на шта треба кликнути. За ажурирање, покрените
новији инсталатер преко старог; подешавања остају сачувана.

**Преузимања по верзији** (свака значка броји само издање
те верзије — старије верзије остају објављене и њихови бројеви се никада
не ресетују):

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

## Шта напушта ваш рачунар

Са подразумеваним подешавањима ваш аудио и транскрипти остају на вашем рачунару.
Апликација ипак користи мрежу за:

- преузимање модела или опционалне компоненте први пут када је то потребно;
- своја онлајн подешавања при покретању и дневну проверу ажурирања на GitHub-у, што
  вас само обавештава о новој верзији;
- статистику коришћења, укључену подразумевано, након сваке завршене транскрипције: модел,
  језик, трајања, број речи, верзија апликације, оперативни систем, процесор и
  величина меморије, и регион, никада име фајла. Искључите то под
  **Help → Usage statistics**.

Аудио или текст транскрипта се шаљу само ако изаберете cloud систем (Gemini API
или Google Cloud Speech-to-Text) или сами повежете удаљеног AI провајдера.
**File → Work offline** зауставља све то. Свака конекција је наведена у
[../CONFIG.md](../CONFIG.md#network-use).

## Документација

[Инсталација](../INSTALL.md) · [Конфигурација](../CONFIG.md) ·
[Транскрипција уживо](../LIVE.md) · [Режим локалне мреже и API](../SERVER.md) ·
[Cloud системи](../CLOUD_STT.md) · [Архитектура](../ARCHITECTURE.md) ·
[Историја промена](../CHANGELOG.md) · [Сви документи](../README.md)

## Изградња из изворног кода

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Захтева Python 3.11 или новији. Процес изградње: [../BUILD.md](../BUILD.md). Тестови и захтеви за повлачење (pull requests):
[../../CONTRIBUTING.md](../../CONTRIBUTING.md).

## Доприноси и контакт

- **Бубе (bugs) и захтеви за нове функције:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Питања и идеје:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Све остало:** путем е-поште, преко
  [секције Contact на веб сајту](https://whisper-transcriber-suite.com/#contact) · ✉ [admin@whisper-transcriber-suite.com](mailto:admin@whisper-transcriber-suite.com)
- **Пријаве безбедносних пропуста:** [../../SECURITY.md](../../SECURITY.md)

Овај пројекат прати [Завет сарадника (Contributor Covenant)](../../.github/CODE_OF_CONDUCT.md).
Ако вам апликација штеди време, звездица на врху ове странице помаже другим људима
да је пронађу.

## Како се гради овај пројекат

Одржавалац га развија уз велику помоћ AI асистената за кодирање (углавном Claude). Провере типова
и јединични тестови морају да прођу пре сваког комита (commit), а CI их поново покреће на Windows-у и Linux-у након
сваког гурања (push). [Контролна листа за издање](../RELEASE_PROCESS.md) укључује ручни тест инсталације на
правој машини. Комити направљени уз помоћ AI сада наводе модел у линији `Assisted-by:`; многи старији
носе линију `Co-Authored-By: Claude` уместо тога.

## Лиценца

Ауторска права (c) 2026 translation-robot (коаутор). Пројекат живи у овом репозиторијуму,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
Сам изворни код пројекта је под [BSD 3-Clause лиценцом](../../LICENSE). Укључени
алати, Python окружење и модели задржавају своје сопствене лиценце; погледајте
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
