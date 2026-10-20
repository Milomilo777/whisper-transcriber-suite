<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**Бесплатная транскрибация и субтитры для длинных записей на вашем языке — на обычном ноутбуке, без интернета, без аккаунта и без загрузки аудио в облако.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![downloads](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/total?label=downloads&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Скачать для Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS и Linux: см. [Скачать](#download).

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
<b>Русский</b> ·
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

## Для кого это

Программа создана для создателей субтитров, переводчиков, исследователей и журналистов, которым нужно перевести в текст или субтитры длинные записи: интервью, лекции, выступления и видео. Просто перетащите аудио- или видеофайл в окно программы, и текстовая расшифровка (транскрипт) сохранится рядом с ним. Движок распознавания речи работает локально на вашем компьютере, поэтому вы не платите за минуты, а после скачивания языковой модели вам даже не понадобится интернет.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="Вкладка Transcribe: область для перетаскивания файлов, выбор движка и языка, параметры меток говорящих и временных меток слов" width="80%">
</div>

## Что нового в 2.0

- **Скорость и время до завершения:** на вкладке Queue теперь отображается скорость обработки и примерное время до завершения каждой задачи.
- **Видео с субтитрами по ссылке:** скачивание, транскрибация и вшивание субтитров за одну задачу ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Транскрипт как веб-страница:** сохранение в один `.html`-файл, в котором можно искать текст и воспроизводить аудио по клику на слово. Работает в любом браузере без интернета.
- **Офлайн-режим, который можно проверить:** при включенной опции Work offline строка состояния показывает, есть ли подключение к сети у приложения или запущенного им процесса.
- **Перевод на английский:** речь на любом поддерживаемом языке автоматически переводится в английские субтитры за один проход.
- **Быстрый старт:** при новой установке задаются три вопроса, а 18-секундный пример сразу показывает результат.
- **Сообщить о проблеме** из меню Help, без аккаунта GitHub.
- **macOS:** меню приложения с Settings (Command-запятая), светлая и темная темы, соответствующие системе, уведомления. **Windows:** прогресс на панели задач и темные заголовки окон.

Полный список: [CHANGELOG](../CHANGELOG.md).

## Возможности

- **Локальные движки:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (по умолчанию), whisper.cpp и NVIDIA Parakeet, для множества языков, которые распознает Whisper. Если в системе есть видеокарта NVIDIA, используется ускорение через CUDA, иначе обработка идет на процессоре.
- **Приложение на вашем языке:** Меню, кнопки и сообщения на 42 языках (машинный перевод, помеченный как таковой; исправления приветствуются). Язык берется из настроек системы, либо вы выбираете его в Расширенных настройках. Персидский, арабский и иврит пока доступны в Windows.
- **14 форматов вывода:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX и PDF, а также форматы oTranscribe, ELAN, InqScribe и Express Scribe. DOCX и PDF отрисовывают любую письменность, а персидский, арабский и урду читаются справа налево со слитными буквами.
- **Веб-страница, которой легко поделиться:** сохраняйте готовую транскрибацию в виде одного файла `.html`, который работает без интернета в любом браузере; нажимайте на слово, чтобы его услышать, ищите, переходите по главам.
- **Метки говорящих** без аккаунта Hugging Face, а также таймкоды для каждого слова и обрезка по временному диапазону.
- **Прерванные задачи возобновляются** с последней контрольной точки, а не начинаются заново (движок по умолчанию).
- **Онлайн-видео:** скачивание с любого сайта, который поддерживает [yt-dlp](https://github.com/yt-dlp/yt-dlp), и транскрибация после завершения загрузки.
- **Ссылка на видео с субтитрами:** одна галочка превращает ссылку в `<title>-subbed.mp4` с вшитыми субтитрами: скачивание, транскрибация и вшивание в одной задаче в очереди ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **В реальном времени:** транскрибация с микрофона или системного звука в Windows в процессе звучания ([../LIVE.md](../LIVE.md)).
- **Пакетная очередь и отслеживаемая папка** для множества файлов.
- **Режим локальной сети:** страница транскрибации и API, совместимый с OpenAI, для других устройств в вашей сети ([../SERVER.md](../SERVER.md)).
- **Дополнительно, по умолчанию выключено:** ИИ-инструменты для готового транскрипта (краткое содержание, вопросы, двуязычные субтитры SRT) и офлайн-озвучивание текста с клонированием голоса.

Сравнение с Subtitle Edit, Vibe, Buzz, noScribe и aTrain, включая случаи, когда другое приложение подходит лучше:
**[../COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Скачать

Последний релиз: **[releases page](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| Файл | Для чего |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 или 11, 64-бит. Большинству пользователей нужен именно он. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows без установки: распакуйте и запустите. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Mac на процессорах Apple Silicon, macOS 14 или новее. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Mac на процессорах Intel, macOS 10.15 или новее. |

В Linux запускается из исходного кода: [../../platform/linux/README.md](../../platform/linux/README.md).

Встроенный FFmpeg собран под лицензией GPL. Соответствующий исходный код прикреплен к каждому релизу в виде файлов `WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*`; точные ссылки указаны в [../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

ffmpeg и yt-dlp уже встроены. При первом запуске в окне быстрого старта выбирается речевая модель для вашего языка: Fast (Small, около 500 МБ) или Best quality (до 3 ГБ); она скачивается один раз, при первом использовании. Для работы потребуется 8 ГБ оперативной памяти; на процессоре (CPU) распознавание с помощью больших (Large) моделей занимает примерно в 1.5–2.5 раза больше времени, чем длительность аудио, а моделями Small — около половины; на видеокартах NVIDIA распознавание происходит гораздо быстрее. Сборки для Windows не имеют цифровой подписи, а сборки для Mac не нотаризованы, поэтому SmartScreen и Gatekeeper могут показать предупреждение при первом запуске; в [../INSTALL.md](../INSTALL.md) показано, куда нажимать. Для обновления запустите новый установщик поверх старой версии; настройки сохранятся.

**Загрузки по версиям** (каждый бейдж считает только загрузки соответствующего релиза — старые версии остаются доступными, и их счетчики никогда не сбрасываются):

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

## Что покидает ваш компьютер

С настройками по умолчанию ваши аудио и транскрипты остаются на компьютере. Приложение использует сеть для:

- скачивания модели или дополнительного компонента в первый раз, когда он требуется;
- получения онлайн-настроек при запуске и ежедневной проверки обновлений на GitHub, которая лишь сообщает о новой версии;
- отправки статистики использования, включенной по умолчанию, после каждой завершенной транскрибации: модель, язык, длительности, количество слов, версия приложения, операционная система, процессор и объем памяти, а также регион, но никогда не имя файла. Отключите это в меню **Help → Usage statistics**.

Аудио или текст отправляются в сеть только в том случае, если вы сами выбрали облачный движок (Gemini API или Google Cloud Speech-to-Text) или подключили стороннего ИИ-провайдера. **File → Work offline** останавливает всё это. Каждое подключение перечислено в [../CONFIG.md](../CONFIG.md#network-use).

## Документация

[Установка](../INSTALL.md) · [Настройка](../CONFIG.md) ·
[Транскрибация в реальном времени](../LIVE.md) · [Режим локальной сети и API](../SERVER.md) ·
[Облачные движки](../CLOUD_STT.md) · [Архитектура](../ARCHITECTURE.md) ·
[История изменений](../CHANGELOG.md) · [Вся документация](../README.md)

## Сборка из исходного кода

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Требуется Python 3.11 или новее. Процесс сборки: [../BUILD.md](../BUILD.md). Тесты и pull-реквесты: [../../CONTRIBUTING.md](../../CONTRIBUTING.md).

## Помощь проекту и контакты

- **Ошибки и запросы новых функций:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Вопросы и идеи:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Всё остальное:** по электронной почте, через [раздел контактов на сайте](https://whisper-transcriber-suite.com/#contact)
- **Сообщения об уязвимостях:** [../../SECURITY.md](../../SECURITY.md)

Этот проект следует [Кодексу поведения](../../.github/CODE_OF_CONDUCT.md). Если приложение экономит ваше время, звездочка (Star) в верхней части этой страницы поможет другим людям найти его.

## Как создается этот проект

Разработчик создает его при активной помощи ИИ-ассистентов (в основном Claude). Проверки типов и юнит-тесты должны быть пройдены перед каждым коммитом, и система CI снова запускает их на Windows и Linux после каждого push-а. [Контрольный список релиза](../RELEASE_PROCESS.md) включает ручную проверку установки на реальной машине. Коммиты, сделанные с помощью ИИ, теперь содержат название модели в строке `Assisted-by:`; во многих старых коммитах вместо нее используется строка `Co-Authored-By: Claude`.

## Лицензия

Copyright (c) 2026 translation-robot (co-author). Проект находится в этом репозитории,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
Собственный исходный код проекта предоставляется под [лицензией BSD 3-Clause](../../LICENSE). Встроенные инструменты, среда выполнения Python и модели сохраняют свои собственные лицензии; см. [../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
