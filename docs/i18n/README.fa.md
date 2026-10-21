<div align="center" dir="rtl">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**رونوشت‌برداری و زیرنویس آفلاین و رایگان برای ضبط‌های طولانی به زبان شما — روی یک لپ‌تاپ معمولی، بدون نیاز به حساب کاربری و بدون آپلود صدا.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![downloads](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/total?label=downloads&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [دانلود برای ویندوز](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

برای macOS و Linux: بخش [دانلود](#download) را ببینید.

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
<b>فارسی</b> ·
<a href="README.he.md">עברית</a> ·
<a href="README.lv.md">Latviešu</a> ·
<a href="README.ca.md">Català</a> ·
<a href="README.bn.md">বাংলা</a> ·
<a href="README.fil.md">Filipino</a>
</p>

<!-- language-links:end -->
<!-- translated from README.md at commit 66585d5 -->

</div>

<div dir="rtl">

## برای چه کسانی است

زیرنویس‌سازان، مترجمان، پژوهشگران و روزنامه‌نگارانی که ضبط‌های طولانی (مصاحبه‌ها، سخنرانی‌ها، ارائه‌ها، ویدیوها) را به متن یا زیرنویس تبدیل می‌کنند. یک فایل صوتی یا ویدیویی را رها کنید و رونوشت آن در کنارش نوشته می‌شود. موتور گفتار روی رایانه‌ی خودتان اجرا می‌شود، بنابراین هیچ هزینه‌ای به‌ازای هر دقیقه وجود ندارد و پس از دانلود مدل، نیازی به اتصال اینترنت نیست.

</div>

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="تب Transcribe: ناحیه‌ی رها کردن فایل، انتخاب موتور و زبان، گزینه‌های برچسب گوینده و زمان‌نگاشت کلمات" width="80%">
</div>

<div dir="rtl">

## تازه‌های نسخه‌ی ۲.۰

- **سرعت و زمان باقی‌مانده:** تب Queue سرعت هر کار و زمان تقریبی باقی‌مانده را نشان می‌دهد.
- **ویدیوی زیرنویس‌دار از یک لینک:** دانلود، رونوشت‌برداری و چسباندن زیرنویس روی ویدیو به‌عنوان یک کار ([docs/SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **رونوشت به‌صورت صفحه‌ی وب:** یک فایل `.html` با قابلیت جستجو و پخش با کلیک که در هر مرورگری به‌صورت آفلاین کار می‌کند.
- **کار آفلاین با قابلیت بررسی:** با روشن بودن Work offline، یک نوار وضعیت نشان می‌دهد که آیا برنامه یا فرآیندِ آغازشده توسط آن به شبکه متصل است یا خیر.
- **ترجمه به انگلیسی:** گفتار غیرانگلیسی در یک مرحله به زیرنویس انگلیسی تبدیل می‌شود.
- **شروع سریع:** در نصب‌های جدید سه سؤال پرسیده می‌شود و یک نمونه کلیپ ۱۸ ثانیه‌ای بلافاصله نتیجه را نشان می‌دهد.
- **گزارش مشکل:** از منوی Help، بدون نیاز به حساب کاربری GitHub.
- **سیستم‌عامل macOS:** منوی برنامه با تنظیمات (Command-comma)، تم‌های Light و Dark هماهنگ با سیستم، اعلان‌ها. **سیستم‌عامل Windows:** پیشرفت کار در نوار وظیفه (taskbar) و نوارهای عنوان (title bars) تاریک.

لیست کامل: [CHANGELOG](../CHANGELOG.md).

## امکانات

- **موتورهای محلی:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (پیش‌فرض)، whisper.cpp و NVIDIA Parakeet، برای بسیاری از زبان‌هایی که Whisper تشخیص می‌دهد. در صورت امکان از پردازنده‌ی گرافیکی NVIDIA از طریق CUDA استفاده می‌کند، در غیر این صورت از پردازنده‌ی مرکزی (CPU).
- **برنامه به زبان شما:** منوها، دکمه‌ها و پیام‌ها به 42 زبان (ترجمه‌ی ماشینی، با برچسب مشخص؛ از اصلاحات استقبال می‌کنیم). از زبان سیستم شما پیروی می‌کند یا می‌توانید در تنظیمات پیشرفته زبانی را انتخاب کنید. فارسی، عربی و عبری فعلاً در Windows ارائه می‌شوند.
- **۱۴ فرمت خروجی:** SRT، VTT، ASS، TSV، TXT، JSON، LRC، Markdown، DOCX و PDF، به‌علاوه‌ی فرمت‌های oTranscribe، ELAN، InqScribe و Express Scribe. فرمت‌های DOCX و PDF هر نوع خطی را رسم می‌کنند، و فارسی، عربی و اردو از راست به چپ و با حروف پیوسته خوانده می‌شوند.
- **صفحه‌ی وب قابل اشتراک‌گذاری:** یک رونوشت پایان‌یافته را به‌عنوان یک فایل `.html` ذخیره کنید که در هر مرورگری به‌صورت آفلاین کار می‌کند؛ روی یک کلمه کلیک کنید تا آن را بشنوید، جستجو کنید، به فصل‌ها پرش کنید.
- **برچسب‌های گوینده** بدون نیاز به حساب Hugging Face، به‌علاوه‌ی برچسب‌زمان به‌ازای هر کلمه و برش بازه‌ی زمانی.
- **کارهای قطع‌شده ادامه می‌یابند:** از آخرین نقطه‌ی ذخیره‌شده (checkpoint) به‌جای شروع دوباره (موتور پیش‌فرض).
- **ویدیوهای آنلاین:** از هر سایتی که [yt-dlp](https://github.com/yt-dlp/yt-dlp) پشتیبانی کند دانلود کنید و وقتی دانلود تمام شد رونوشت‌برداری کنید.
- **لینک به ویدیوی زیرنویس‌دار:** با یک تیک، یک لینک به `<title>-subbed.mp4` با زیرنویس‌های چسبیده تبدیل می‌شود: دانلود، رونوشت‌برداری و چسباندن زیرنویس در یک کارِ صف‌بندی‌شده ([docs/SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **زنده:** یک میکروفون، یا صدای سیستم در Windows را، همزمان با رخ‌دادن رونوشت‌برداری می‌کند ([docs/LIVE.md](../LIVE.md)).
- **صف دسته‌ای و پوشه‌ی تحت‌نظر** برای فایل‌های زیاد.
- **حالت شبکه‌ی محلی:** یک صفحه‌ی رونوشت‌برداری و یک API سازگار با OpenAI برای سایر دستگاه‌های شبکه‌ی شما ([docs/SERVER.md](../SERVER.md)).
- **اختیاری، به‌طور پیش‌فرض خاموش:** ابزارهای هوش مصنوعی برای یک رونوشت پایان‌یافته (خلاصه، پرسش‌ها، SRT دوزبانه)، و تبدیل متن به صدا به‌صورت آفلاین با شبیه‌سازی صدا.

نحوه مقایسه آن با Subtitle Edit، Vibe، Buzz، noScribe و aTrain، از جمله اینکه چه زمانی برنامه‌ای دیگر انتخاب بهتری است:
**[docs/COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## دانلود

آخرین رلیز: **[صفحه‌ی رلیزها](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| فایل | برای |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 یا 11، ۶۴ بیتی. بیشتر کاربران این یکی را می‌خواهند. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows بدون نصب: استخراج و اجرا کنید. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | مک‌های با پردازنده‌ی Apple silicon، سیستم‌عامل macOS 14 یا جدیدتر. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | مک‌های Intel، سیستم‌عامل macOS 10.15 یا جدیدتر. |

لینوکس از روی سورس اجرا می‌شود: [platform/linux/README.md](../../platform/linux/README.md).

فایل اجرایی همراهِ FFmpeg یک بیلد GPL است. سورس مربوط به آن به همراه هر رلیز به‌عنوان فایل‌های `WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*` پیوست شده است؛ لینک‌های دقیق در [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) قرار دارند.

ابزارهای ffmpeg و yt-dlp همراه برنامه هستند. در اولین اجرا، یک پنجره‌ی شروع سریع مدل گفتار را برای زبان شما انتخاب می‌کند: سریع (Fast، حدود ۵۰۰ مگابایت) یا بهترین کیفیت (Best quality، تا حدود ۳ گیگابایت)؛ فقط یک بار، هنگام اولین استفاده دانلود می‌شود. برنامه‌ریزی کنید که ۸ گیگابایت RAM داشته باشید؛ روی یک پردازنده‌ی مرکزی (CPU)، زمان موردنیاز برای مدل‌های بزرگ (Large) حدود ۱.۵ تا ۲.۵ برابرِ طولِ فایل صوتی، و برای مدل‌های کوچک (Small) حدود نصفِ آن است؛ یک پردازنده‌ی گرافیکی NVIDIA بسیار سریع‌تر است. بیلدهای Windows امضای کد ندارند و بیلدهای Mac دارای تأییدیه‌ی Notarize نیستند، بنابراین SmartScreen و Gatekeeper در اولین اجرا هشدار می‌دهند؛ [docs/INSTALL.md](../INSTALL.md) نشان می‌دهد که باید روی چه چیزی کلیک کنید. برای به‌روزرسانی، نصب‌کننده‌ی جدیدتر را روی نصب‌کننده‌ی قدیمی اجرا کنید؛ تنظیمات حفظ می‌شوند.

**تعداد دانلودها بر اساس نسخه** (هر نشان (badge) فقط رلیز مربوط به همان نسخه را می‌شمارد — نسخه‌های قدیمی‌تر منتشرشده باقی می‌مانند و شمارش آن‌ها هرگز صفر نمی‌شود):

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

## چه چیزی از رایانه‌ی شما خارج می‌شود

با تنظیمات پیش‌فرض، صداها و رونوشت‌های شما روی رایانه‌تان باقی می‌مانند.
برنامه از شبکه برای این موارد استفاده می‌کند:

- دانلود یک مدل یا یک جزء اختیاری در اولین باری که به آن نیاز است؛
- تنظیمات آنلاین در هنگام راه‌اندازی و بررسی روزانه‌ی به‌روزرسانی روی GitHub، که فقط نسخه‌ی جدید را به شما اطلاع می‌دهد؛
- آمارهای استفاده، که به‌طور پیش‌فرض روشن است، پس از هر رونوشت‌برداریِ پایان‌یافته: مدل، زبان، مدت‌زمان‌ها، تعداد کلمات، نسخه‌ی برنامه، سیستم‌عامل، پردازنده‌ی مرکزی و حجم حافظه، و منطقه. نام فایل هرگز فرستاده نمی‌شود. می‌توانید آن‌ها را در بخش **Help → Usage statistics** خاموش کنید.

صدا یا متنِ رونوشت تنها زمانی ارسال می‌شود که شما یک موتور ابری (Gemini API یا Google Cloud Speech-to-Text) را انتخاب کنید یا خودتان یک ارائه‌دهنده‌ی هوش مصنوعیِ از راه‌دور را متصل کنید.
گزینه‌ی **File → Work offline** تمام این ارتباطات را متوقف می‌کند. هر اتصال در [docs/CONFIG.md](../CONFIG.md#network-use) لیست شده است.

## مستندات

[نصب](../INSTALL.md) · [پیکربندی](../CONFIG.md) ·
[رونوشت‌برداری زنده](../LIVE.md) · [حالت شبکه‌ی محلی و API](../SERVER.md) ·
[موتورهای ابری](../CLOUD_STT.md) · [معماری](../ARCHITECTURE.md) ·
[تاریخچه‌ی نسخه‌ها](../CHANGELOG.md) · [همه‌ی مستندات](../README.md)

</div>

## ساخت از سورس

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

<div dir="rtl">

نیازمند Python 3.11 یا جدیدتر است. خط‌لوله‌های ساخت (Build pipelines): [docs/BUILD.md](../BUILD.md). تست‌ها و درخواست‌های کشش (pull requests):
[CONTRIBUTING.md](../../CONTRIBUTING.md).

## مشارکت و تماس

- **باگ‌ها و درخواست امکانات:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **سؤالات و ایده‌ها:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **موارد دیگر:** از طریق ایمیل، بخش [تماس در وب‌سایت](https://whisper-transcriber-suite.com/#contact) · ✉ [admin@whisper-transcriber-suite.com](mailto:admin@whisper-transcriber-suite.com)
- **گزارش‌های امنیتی:** [SECURITY.md](../../SECURITY.md)

این پروژه از [پیمان مشارکت‌کنندگان (Contributor Covenant)](../../.github/CODE_OF_CONDUCT.md) پیروی می‌کند.
اگر این برنامه در زمان شما صرفه‌جویی می‌کند، دادن یک ستاره (Star) در بالای این صفحه به دیگران کمک می‌کند تا آن را پیدا کنند.

## نحوه‌ی ساخت این پروژه

نگه‌دارنده‌ی (maintainer) این پروژه آن را با کمک زیاد از دستیارهای کدنویسی هوش مصنوعی (عمدتاً Claude) توسعه می‌دهد. بررسی‌های نوعِ داده (Type checks) و تست‌های واحد باید پیش از هر کامیت (commit) با موفقیت پاس شوند، و سامانه‌ی یکپارچه‌سازیِ پیوسته (CI) آن‌ها را دوباره روی Windows و Linux پس از هر پوش (push) اجرا می‌کند. [چک‌لیست رلیز](../RELEASE_PROCESS.md) شامل یک تست نصبِ دستی روی یک ماشین واقعی است. کامیت‌هایی که با کمک هوش مصنوعی ساخته شده‌اند، اکنون نام مدل را در یک خط `Assisted-by:` می‌آورند؛ بسیاری از کامیت‌های قدیمی‌تر به‌جای آن یک خط `Co-Authored-By: Claude` دارند.

## مجوز

حق نسخه‌برداری (c) 2026 translation-robot (نویسنده‌ی همکار). این پروژه در این مخزن قرار دارد، [Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
سورسِ خود پروژه تحت [مجوز BSD 3-Clause](../../LICENSE) است. ابزارهای همراه، محیط اجرایی Python و مدل‌ها، مجوزهای مخصوص به خود را حفظ می‌کنند؛ برای اطلاعات بیشتر [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) را ببینید.

</div>