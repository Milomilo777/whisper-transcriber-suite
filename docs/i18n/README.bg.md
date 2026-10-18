<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**Безплатна транскрипция и субтитри за дълги записи на вашия език — работи на обикновен лаптоп без интернет, без акаунт и без качване на аудиото в облака.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Изтегляне за Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS и Linux: вижте [Изтегляне](#download).

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
<b>Български</b> ·
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

## За кого е това

Програмата е създадена за създатели на субтитри, преводачи, изследователи и журналисти, на които им се налага да превръщат в текст или субтитри дълги записи: интервюта, лекции, речи и видеоклипове. Просто пуснете аудио или видео файл в прозореца на програмата и текстовата транскрипция (транскрипт) ще се запази до него. Двигателят за разпознаване на реч работи локално на вашия компютър, така че не плащате на минута, а след като изтеглите езиковия модел, дори няма да ви трябва интернет.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="Разделът Transcribe: зона за пускане на файлове, избор на двигател и език, опции за етикети на говорещите и времеви маркери на думите" width="80%">
</div>

## Какво ново в 2.0

- **Скорост и оставащо време:** в раздела Queue вече се показват скоростта на обработка и приблизителното време до завършване на всяка задача.
- **Видео със субтитри от връзка:** изтегляне, транскрипция и вграждане на субтитри в една задача ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Транскрипт като уеб страница:** запазване в един `.html` файл, в който можете да търсите текст и да възпроизвеждате аудио с щракване върху дума. Работи във всеки браузър без интернет.
- **Офлайн режим, който можете да проверите:** при включена опция Work offline, лентата на състоянието показва дали приложението или стартиран от него процес има мрежова връзка.
- **Превод на английски:** реч на други езици се превръща в английски субтитри с едно преминаване.
- **Бърз старт:** при нова инсталация се задават три въпроса, а 18-секунден примерен клип веднага показва резултат.
- **Съобщаване за проблем** от менюто Help, без акаунт в GitHub.
- **macOS:** меню на приложението с Settings (Command-запетая), светла и тъмна тема, следващи системата, известия. **Windows:** напредък в лентата на задачите и тъмни заглавни ленти.

Пълен списък: [CHANGELOG](../CHANGELOG.md).

## Възможности

- **Локални двигатели:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (по подразбиране), whisper.cpp и NVIDIA Parakeet, за многото езици, които Whisper разпознава. Ако в системата има видеокарта NVIDIA, се използва ускорение чрез CUDA, в противен случай обработката се извършва от процесора.
- **Приложението на вашия език:** Менюта, бутони и съобщения на 42 езика (машинен превод, означен като такъв; поправките са добре дошли). Следва езика на системата ви или можете да изберете език в Разширени настройки. Персийски, арабски и иврит засега са налични на Windows.
- **14 изходни формата:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX и PDF, плюс форматите oTranscribe, ELAN, InqScribe и Express Scribe. DOCX и PDF изобразяват всяка писменост, а персийският, арабският и урду се четат отдясно наляво със слети букви.
- **Уеб страница за споделяне:** запазете готовата транскрипция като един `.html` файл, който работи офлайн във всеки браузър; щракнете върху дума, за да я чуете, търсете, прескачайте по глави.
- **Етикети на говорещите** без акаунт в Hugging Face, плюс времеви кодове за всяка дума и изрязване по времеви диапазон.
- **Прекъснатите задачи се възобновяват** от последната си контролна точка, вместо да започват отначало (двигател по подразбиране).
- **Онлайн видеоклипове:** изтегляне от всеки сайт, който [yt-dlp](https://github.com/yt-dlp/yt-dlp) поддържа, и транскрипция, след като изтеглянето завърши.
- **Връзка към видео със субтитри:** една отметка превръща връзката в `<title>-subbed.mp4` с вградени субтитри: изтегляне, транскрипция и вграждане в една задача на опашката ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **На живо:** транскрипция от микрофон или от системния звук в Windows, докато се случва ([../LIVE.md](../LIVE.md)).
- **Пакетна опашка и наблюдавана папка** за много файлове.
- **Режим на локална мрежа:** страница за транскрипция и съвместим с OpenAI API за другите устройства във вашата мрежа ([../SERVER.md](../SERVER.md)).
- **Допълнително, изключено по подразбиране:** AI инструменти за готов транскрипт (резюме, въпроси, двуезични SRT) и офлайн текст към говор с клониране на глас.

Как се сравнява със Subtitle Edit, Vibe, Buzz, noScribe и aTrain, включително кога друго приложение е по-добрият избор:
**[../COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Изтегляне

Последно издание: **[releases page](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| Файл | За |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 или 11, 64-битов. Повечето хора се нуждаят от този. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows без инсталиране: разархивирайте и стартирайте. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Mac компютри с Apple silicon, macOS 14 или по-нова. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Mac компютри с процесори Intel, macOS 10.15 или по-нова. |

Linux се стартира от изходния код: [../../platform/linux/README.md](../../platform/linux/README.md).

Вграденият FFmpeg е компилиран под GPL лиценз. Съответният изходен код е прикачен към всяко издание като файлове `WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*`; точните връзки са в [../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

ffmpeg и yt-dlp са вградени. При първото стартиране в прозореца за бърз старт се избира речевият модел за вашия език: Fast (Small, около 500 MB) или Best quality (до 3 GB); той се изтегля веднъж, при първа употреба. За работа са необходими 8 GB RAM; на процесор (CPU) разпознаването с големи (Large) модели отнема време, равно на около 1,5–2,5 пъти дължината на аудиото, а с модели Small — около половината; с NVIDIA видеокарта е много по-бързо. Версиите за Windows нямат цифров подпис, а версиите за Mac не са нотаризирани, така че SmartScreen и Gatekeeper може да покажат предупреждение при първото стартиране; [../INSTALL.md](../INSTALL.md) показва какво да щракнете. За да актуализирате, стартирайте по-новия инсталатор върху стария; настройките се запазват.

**Изтегляния по версии** (всяка значка отчита само изтеглянията на съответното издание — по-старите версии остават публикувани и техните броячи никога не се нулират):

[![v2.1.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.1.0/total?label=v2.1.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.1.0)
[![v2.0.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.0.0/total?label=v2.0.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0)
[![v1.9.3](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.3/total?label=v1.9.3&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.3)
[![v1.9.1](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.1/total?label=v1.9.1&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.1)
[![v1.9.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.0/total?label=v1.9.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.0)
[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

## Какво напуска компютъра ви

С настройките по подразбиране вашето аудио и транскриптите остават на вашия компютър. Приложението използва мрежата за:

- изтегляне на модел или допълнителен компонент при първото му използване;
- получаване на онлайн настройките си при стартиране и ежедневна проверка за актуализации в GitHub, която само ви съобщава за нова версия;
- изпращане на статистика за използването, включено по подразбиране, след всяка завършена транскрипция: модел, език, продължителност, брой думи, версия на приложението, операционна система, процесор и размер на паметта, както и регион, но никога името на файла. Изключете това от **Help → Usage statistics**.

Аудио или текст се изпращат в мрежата само ако вие самите сте избрали облачен двигател (Gemini API или Google Cloud Speech-to-Text) или сте свързали външен AI доставчик. **File → Work offline** спира всичко това. Всяка връзка е изброена в [../CONFIG.md](../CONFIG.md#network-use).

## Документация

[Инсталиране](../INSTALL.md) · [Конфигурация](../CONFIG.md) ·
[Транскрипция на живо](../LIVE.md) · [Режим на локална мрежа и API](../SERVER.md) ·
[Облачни двигатели](../CLOUD_STT.md) · [Архитектура](../ARCHITECTURE.md) ·
[История на промените](../CHANGELOG.md) · [Всички документи](../README.md)

## Компилиране от изходния код

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Изисква Python 3.11 или по-нов. Процес на компилиране: [../BUILD.md](../BUILD.md). Тестове и pull заявки: [../../CONTRIBUTING.md](../../CONTRIBUTING.md).

## Принос и контакт

- **Грешки и заявки за функции:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Въпроси и идеи:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Всичко останало:** по имейл, чрез [раздела за контакт на уебсайта](https://whisper-transcriber-suite.com/#contact)
- **Доклади за сигурността:** [../../SECURITY.md](../../SECURITY.md)

Този проект следва [Кодекса на поведение](../../.github/CODE_OF_CONDUCT.md). Ако приложението ви спестява време, звезда (Star) в горната част на тази страница помага на други хора да го намерят.

## Как е създаден този проект

Поддържащият го разработва със значителна помощ от AI асистенти за програмиране (главно Claude). Проверките на типове и единичните тестове трябва да преминат преди всеки къмит, и CI системата ги изпълнява отново на Windows и Linux след всяко качване. [Списъкът за проверка на изданието](../RELEASE_PROCESS.md) включва ръчен тест за инсталиране на реална машина. Къмитите, направени с AI помощ, сега посочват името на модела в ред `Assisted-by:`; в много по-стари вместо това се използва ред `Co-Authored-By: Claude`.

## Лиценз

Copyright (c) 2026 translation-robot (co-author). Проектът се намира в това хранилище,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
Собственият изходен код на проекта е под [лиценза BSD 3-Clause](../../LICENSE). Включените инструменти, средата за изпълнение на Python и моделите запазват собствените си лицензи; вижте [../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
