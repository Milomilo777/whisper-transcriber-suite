<div align="center">

<img src="../img/hero.png" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**Безкоштовна транскрипція та субтитри для довгих записів вашою мовою — працює на звичайному ноутбуці без інтернету, без акаунта і без завантаження аудіо у хмару.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Завантажити для Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS та Linux: див. [Завантажити](#download).

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
<b>Українська</b> ·
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

## Для кого це

Програму створено для спеціалістів із субтитрів, перекладачів, дослідників та журналістів, яким потрібно перетворити на текст або субтитри довгі записи: інтерв'ю, лекції, виступи та відео. Просто перетягніть аудіо- або відеофайл у вікно програми, і текстова розшифровка (транскрипт) збережеться поруч із ним. Рушій розпізнавання мовлення працює локально на вашому комп'ютері, тому ви не платите за хвилини, а після завантаження мовної моделі вам навіть не знадобиться інтернет.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="Вкладка Transcribe: область для перетягування файлів, вибір рушія та мови, параметри міток мовців і часових міток слів" width="80%">
</div>

## Що нового у версії 2.0

- **Швидкість і час до завершення:** на вкладці Queue тепер відображається швидкість обробки та приблизний час до завершення кожного завдання.
- **Відео з субтитрами за посиланням:** завантаження, транскрипція та вшивання субтитрів за одне завдання ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Транскрипт як вебсторінка:** збереження в один `.html`-файл, у якому можна шукати текст і відтворювати аудіо за кліком на слово. Працює в будь-якому браузері без інтернету.
- **Офлайн-режим, який можна перевірити:** при увімкненій опції Work offline рядок стану показує, чи є підключення до мережі у застосунку або запущеного ним процесу.
- **Переклад на англійську:** мова, відмінна від англійської, перетворюється на англійські субтитри за один прохід.
- **Швидкий старт:** при новому встановленні ставляться три запитання, а 18-секундний приклад одразу показує результат.
- **Повідомити про проблему** з меню Help, без акаунта GitHub.
- **macOS:** меню застосунку з Settings (Command-кома), світла та темна теми, що відповідають системним налаштуванням, сповіщення. **Windows:** прогрес на панелі завдань та темні заголовки вікон.

Повний список: [CHANGELOG](../CHANGELOG.md).

## Можливості

- **Локальні рушії:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (за замовчуванням), whisper.cpp та NVIDIA Parakeet, для багатьох мов, які розпізнає Whisper. Використовує відеокарту NVIDIA (через CUDA), якщо це можливо, інакше — процесор.
- **Застосунок вашою мовою:** Меню, кнопки та повідомлення 42 мовами (машинний переклад, позначений як такий; виправлення вітаються). Мова береться із системи, або ви обираєте її в Розширених налаштуваннях. Перська, арабська та іврит наразі доступні у Windows.
- **14 форматів виводу:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX та PDF, а також формати oTranscribe, ELAN, InqScribe та Express Scribe. DOCX і PDF відображають будь-яку писемність, а перська, арабська та урду читаються справа наліво зі злитими літерами.
- **Вебсторінка, якою легко поділитися:** зберігайте готову транскрипцію як один файл `.html`, що працює без інтернету в будь-якому браузері; натискайте на слово, щоб його почути, шукайте, переходьте по розділах.
- **Мітки мовців** без акаунта Hugging Face, а також таймкоди для кожного слова і обрізання за часовим діапазоном.
- **Перервані завдання відновлюються** з останньої контрольної точки, а не починаються заново (рушій за замовчуванням).
- **Онлайн-відео:** завантаження з будь-якого сайту, який підтримує [yt-dlp](https://github.com/yt-dlp/yt-dlp), і транскрипція після завершення завантаження.
- **Посилання на відео із субтитрами:** одна галочка перетворює посилання на `<title>-subbed.mp4` із вшитими субтитрами: завантаження, транскрипція та вшивання в одному завданні у черзі ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **У реальному часі:** транскрипція з мікрофона або системного звуку в Windows під час звучання ([../LIVE.md](../LIVE.md)).
- **Пакетна черга та папка відстеження** для багатьох файлів.
- **Режим локальної мережі:** сторінка транскрипції та API, сумісний з OpenAI, для інших пристроїв у вашій мережі ([../SERVER.md](../SERVER.md)).
- **Додатково, вимкнено за замовчуванням:** ШІ-інструменти для готового транскрипту (короткий зміст, запитання, двомовні субтитри SRT) та офлайн-озвучування тексту з клонуванням голосу.

Порівняння з Subtitle Edit, Vibe, Buzz, noScribe та aTrain, включно з випадками, коли інший застосунок підходить краще:
**[../COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Завантажити

Останній реліз: **[releases page](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| Файл | Для чого |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 або 11, 64-біт. Більшості користувачів потрібен саме він. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows без встановлення: розпакуйте та запустіть. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Mac на процесорах Apple Silicon, macOS 14 або новіше. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Mac на процесорах Intel, macOS 10.15 або новіше. |

У Linux запускається з вихідного коду: [../../platform/linux/README.md](../../platform/linux/README.md).

Вбудований FFmpeg зібраний за ліцензією GPL. Відповідний вихідний код прикріплено до кожного релізу у вигляді файлів `WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*`; точні посилання вказані в [../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

ffmpeg та yt-dlp вже вбудовані. При першому запуску у вікні швидкого старту обирається мовна модель для вашої мови: Fast (Small, близько 500 МБ) або Best quality (до 3 ГБ); вона завантажується один раз, при першому використанні. Для роботи знадобиться 8 ГБ оперативної пам'яті; на процесорі (CPU) розпізнавання великими (Large) моделями займає приблизно в 1,5–2,5 раза більше часу, ніж тривалість аудіо, а моделями Small — близько половини; на відеокартах NVIDIA працює набагато швидше. Збірки для Windows не мають цифрового підпису, а збірки для Mac не нотаризовані, тому SmartScreen та Gatekeeper можуть показати попередження під час першого запуску; в [../INSTALL.md](../INSTALL.md) показано, куди натискати. Для оновлення запустіть новий інсталятор поверх старої версії; налаштування збережуться.

**Завантаження за версіями** (кожен бейдж рахує лише завантаження відповідного релізу — старі версії залишаються доступними, і їхні лічильники ніколи не скидаються):

[![v2.1.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.1.0/total?label=v2.1.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.1.0)
[![v2.0.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.0.0/total?label=v2.0.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0)
[![v1.9.3](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.3/total?label=v1.9.3&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.3)
[![v1.9.1](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.1/total?label=v1.9.1&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.1)
[![v1.9.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.0/total?label=v1.9.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.0)
[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

## Що залишає ваш комп'ютер

З налаштуваннями за замовчуванням ваші аудіо та транскрипти залишаються на комп'ютері. Застосунок використовує мережу для:

- завантаження моделі або додаткового компонента вперше, коли він потрібен;
- отримання онлайн-налаштувань під час запуску та щоденної перевірки оновлень на GitHub, яка лише повідомляє про нову версію;
- надсилання статистики використання, увімкненої за замовчуванням, після кожної завершеної транскрипції: модель, мова, тривалості, кількість слів, версія застосунку, операційна система, процесор та об'єм пам'яті, а також регіон, але ніколи не назву файлу. Вимкніть це в меню **Help → Usage statistics**.

Аудіо або текст надсилаються в мережу лише в тому разі, якщо ви самі обрали хмарний рушій (Gemini API або Google Cloud Speech-to-Text) або підключили стороннього ШІ-провайдера. **File → Work offline** зупиняє все це. Кожне підключення перелічено в [../CONFIG.md](../CONFIG.md#network-use).

## Документація

[Встановлення](../INSTALL.md) · [Налаштування](../CONFIG.md) ·
[Транскрипція в реальному часі](../LIVE.md) · [Режим локальної мережі та API](../SERVER.md) ·
[Хмарні рушії](../CLOUD_STT.md) · [Архітектура](../ARCHITECTURE.md) ·
[Історія змін](../CHANGELOG.md) · [Вся документація](../README.md)

## Збірка з вихідного коду

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Потрібен Python 3.11 або новіше. Процес збірки: [../BUILD.md](../BUILD.md). Тести та pull-реквести: [../../CONTRIBUTING.md](../../CONTRIBUTING.md).

## Допомога проєкту та контакти

- **Помилки та запити нових функцій:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Запитання та ідеї:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Все інше:** електронною поштою, через [розділ контактів на сайті](https://whisper-transcriber-suite.pages.dev/#contact)
- **Повідомлення про вразливості:** [../../SECURITY.md](../../SECURITY.md)

Цей проєкт дотримується [Кодексу поведінки](../../.github/CODE_OF_CONDUCT.md). Якщо застосунок економить ваш час, зірочка (Star) у верхній частині цієї сторінки допоможе іншим людям знайти його.

## Як створюється цей проєкт

Розробник створює його за активної допомоги ШІ-асистентів (головним чином Claude). Перевірки типів та юніт-тести повинні бути пройдені перед кожним коммітом, і система CI знову запускає їх на Windows та Linux після кожного push-у. [Контрольний список релізу](../RELEASE_PROCESS.md) включає ручну перевірку встановлення на реальній машині. Комміти, зроблені за допомогою ШІ, тепер містять назву моделі в рядку `Assisted-by:`; у багатьох старих коммітах замість неї використовується рядок `Co-Authored-By: Claude`.

## Ліцензія

Copyright (c) 2026 translation-robot (co-author). Проєкт знаходиться у цьому репозиторії,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
Власний вихідний код проєкту надається за [ліцензією BSD 3-Clause](../../LICENSE). Вбудовані інструменти, середовище виконання Python та моделі зберігають свої власні ліцензії; див. [../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
