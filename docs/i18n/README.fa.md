<div align="center" dir="rtl">

<img src="../img/hero.png" alt="Whisper Transcriber Suite" width="100%">

# Whisper Transcriber Suite

### یک فایل صوتی یا ویدیویی را رها کنید. یک **رونوشت زمان‌بندی‌شده و قالب‌بندی‌شده** پس بگیرید — بدون آنکه فایل هرگز از رایانه‌ی شما خارج شود.

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![downloads](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/total?color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases)
[![License: BSD-3](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)
[![Stars](https://img.shields.io/github/stars/Milomilo777/whisper-transcriber-suite?style=flat&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/stargazers)

### [⬇ دانلود برای ویندوز](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

<p>
  <a href="../../README.md"><img src="https://flagcdn.com/16x12/us.png" alt="" width="16" height="12"> English</a> ∙
  <a href="README.zh-CN.md"><img src="https://flagcdn.com/16x12/cn.png" alt="" width="16" height="12"> 简体中文</a> ∙
  <a href="README.ja.md"><img src="https://flagcdn.com/16x12/jp.png" alt="" width="16" height="12"> 日本語</a> ∙
  <a href="README.ko.md"><img src="https://flagcdn.com/16x12/kr.png" alt="" width="16" height="12"> 한국어</a> ∙
  <a href="README.de.md"><img src="https://flagcdn.com/16x12/de.png" alt="" width="16" height="12"> Deutsch</a> ∙
  <a href="README.es.md"><img src="https://flagcdn.com/16x12/es.png" alt="" width="16" height="12"> Español</a> ∙
  <a href="README.fr.md"><img src="https://flagcdn.com/16x12/fr.png" alt="" width="16" height="12"> Français</a> ∙
  <a href="README.pt.md"><img src="https://flagcdn.com/16x12/pt.png" alt="" width="16" height="12"> Português</a> ∙
  <img src="https://flagcdn.com/16x12/ir.png" alt="" width="16" height="12">
  <b>فارسی</b>
</p>

</div>

---

یک برنامه‌ی دسکتاپ که مدل Whisper از OpenAI را **به‌صورت محلی** — از طریق [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — اجرا می‌کند: رونوشت‌برداری هیچ هزینه‌ای به‌ازای هر دقیقه ندارد، در هواپیما هم کار می‌کند، و ضبط شما را هرگز برای کسی آپلود نمی‌کند. یک فایل را داخل برنامه بیندازید تا `.srt`، `.vtt`، `.txt`، `.json`، `.docx`، `.pdf`، `.ass` و فرمت‌های دیگر را درست کنار فایل اصلی بنویسد. همچنین از هر سایتی که `yt-dlp` پشتیبانی می‌کند دانلود می‌کند، گوینده‌ها را برچسب می‌زند، صفی از کارها را دسته‌ای پردازش می‌کند، و می‌تواند خودش را به یک صفحه‌ی رونوشت‌برداری برای دستگاه‌های دیگر شبکه‌تان تبدیل کند.

بدون حساب کاربری. بدون کلید API. بدون اشتراک. فایل‌های شما روی دیسک خودتان می‌مانند.

- 🔒 **روی رایانه‌ی خودتان اجرا می‌شود** — پیش‌فرض [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CTranslate2)، به‌علاوه‌ی **whisper.cpp** و **NVIDIA Parakeet**
- 📝 **۱۴ فرمت خروجی** — `srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf`، به‌علاوه‌ی oTranscribe / ELAN / InqScribe / Express Scribe
- 🎙️ **رونوشت‌برداری زنده** — از میکروفون یا صدای سیستم، همزمان با رخ‌دادن → [LIVE.md](../LIVE.md)
- 🗣️ **برچسب گوینده** — تفکیک گوینده به‌صورت آفلاین، برچسب‌زمان به‌ازای هر کلمه، برش بازه‌ی زمانی
- 🎬 **دانلود** — هر سایتی که `yt-dlp` پشتیبانی کند، با رونوشت‌برداری خودکار اختیاری پس از پایان دانلود
- 🧹 **حذف نویز تطبیقی** — صدا را ابتدا می‌سنجد و فقط وقتی سنجش نشان دهد کمک می‌کند پاک‌سازی‌اش می‌کند → [DENOISE.md](../DENOISE.md)
- 🌐 **حالت شبکه‌ی محلی** — این رایانه را به یک صفحه‌ی رونوشت‌برداری برای دستگاه‌های دیگرتان تبدیل کنید
- 💸 **رایگان و با مجوز BSD-3** — بدون هزینه به‌ازای دقیقه، بدون اشتراک، بدون تله‌متری به‌صورت پیش‌فرض

## دانلود

آخرین نسخه را از **[صفحه‌ی رلیزها](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)** بردارید:

| فایل | حجم | مناسب برای |
|---|---|---|
| **`WhisperTranscriberSuite-…-Setup-Standard.exe`** | ~۲۱۵ مگابایت | **بیشتر کاربران.** یک نصب‌کننده‌ی معمولی: میان‌بر در منوی Start، ارتقا روی نسخه‌ی قدیمی‌تر، فایل‌های قابل‌مشاهده روی دیسک. |
| **`WhisperTranscriberSuite-…-Portable.zip`** | ~۳۳۰ مگابایت | استخراج کنید و اجرا کنید. بدون نصب، بدون نیاز به دسترسی مدیر، روی یک فلش‌مموری هم کار می‌کند. |
| **`WhisperTranscriberSuite-…-macOS-*.dmg`** | ~۴۰۰ مگابایت | macOS (نسخه‌های x64 و arm64 جداگانه منتشر می‌شوند). |

همه‌چیزِ لازم از قبل داخل بسته است — یک Python همراه، `ffmpeg`، `ffprobe` و `yt-dlp`. تنها چیزی که بعداً دانلود می‌شود خودِ مدل گفتار است (**۱ تا ۳ گیگابایت، فقط یک‌بار**، در اولین اجرا)؛ پس از آن برنامه کاملاً آفلاین کار می‌کند.

## امکانات

<div align="center">

<img src="../img/features.png" alt="" width="100%">

</div>

| | |
|---|---|
| **رونوشت‌برداری محلی** | پیش‌فرض `large-v3`، به‌علاوه‌ی `large-v3-turbo` و `distil-large-v3.5`. |
| **فرمت‌های خروجی زیاد** | `srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf` — درست کنار فایل ورودی نوشته می‌شوند. |
| **رونوشت‌برداری زنده** | یک میکروفون — یا هر چیزی که این رایانه در حال پخش آن است — را همزمان با رخ‌دادن رونوشت‌برداری می‌کند. برش‌ها در مکث‌های طبیعی انجام می‌شوند تا کلمه‌ای هرگز نصف نشود. |
| **تفکیک گوینده** | گزینه‌ی اختیاری «شناسایی گوینده‌ها»، به‌علاوه‌ی برچسب‌زمان به‌ازای هر کلمه و برش بازه‌ی زمانی. |
| **حذف نویز تطبیقی** | هر ضبط را ابتدا می‌سنجد و فقط وقتی سنجش آن را توجیه کند پاک‌سازی می‌کند؛ خروجی خودش را بررسی و در صورت حذف گفتار، آن را برمی‌گرداند. |
| **صف دسته‌ای** | وضعیت زنده برای هر کار در انتظار یا در حال اجرا، با **توقف / ادامه / لغو / اجرای دوباره / حذف** همیشه با یک کلیک. |
| **دانلود** | هرچه `yt-dlp` پشتیبانی کند، به‌علاوه‌ی لینک‌های اپیزود Supreme Master TV. دانلودها به‌جای شروع دوباره، از همان‌جا ادامه می‌یابند. |
| **حالت شبکه‌ی محلی** | یک وب‌سرور تنها با کتابخانه‌ی استاندارد پایتون، تا دستگاه‌های دیگر از طریق این رایانه رونوشت‌برداری کنند — رمز عبور اختیاری، تا وقتی شروعش نکنید خاموش است. |

## نحوه‌ی کارکرد

<div align="center">

<img src="../img/how-it-works.png" alt="" width="100%">

</div>

رابط گرافیکی Tk در فرآیند اصلی اجرا می‌شود. هر کار رونوشت‌برداری در یک زیرفرآیند کارگر با طول عمر بالا اجرا می‌شود که مدل Whisper را در حافظه نگه می‌دارد و از طریق JSON خط‌به‌خط روی stdin/stdout پاسخ می‌دهد؛ `yt-dlp` هم برای هر دانلود زیرفرآیند مخصوص خودش را می‌گیرد. یک توکن UUID به‌ازای هر کارگر و یک ضربان قلب ۵ ثانیه‌ای، این مسیریابی را در برابر بازچرخانی شناسه‌ی فرآیند مقاوم می‌کند و به رابط کاربری اجازه می‌دهد یک کارگرِ گیرکرده را تشخیص دهد، نه اینکه همراه آن هنگ کند.

## به‌صورت پیش‌فرض آفلاین

هر موتور پیش‌فرض روی رایانه‌ی شما اجرا می‌شود. هیچ‌چیز آپلود نمی‌شود، هیچ حساب کاربری‌ای وجود ندارد، و پس از دانلود مدل، برنامه با شبکه‌ی قطع‌شده هم کار می‌کند.

> [!IMPORTANT]
> دو موتور **اختیاری** این تضمین را می‌شکنند، و هر دو تا وقتی از **Advanced → Backend** انتخابشان نکنید خاموش می‌مانند. آن‌ها را فقط برای محتوایی به‌کار ببرید که مایلید به شخص ثالث ارسال شود.
>
> - **`cloud_stt`** — Google Gemini API
> - **`google_cloud_stt`** — Google Cloud Speech-to-Text

## ساخت از سورس

```bash
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

## مستندات

| سند | محتوا |
|---|---|
| [INSTALL.md](../INSTALL.md) | نصب و رفع اشکال |
| [LIVE.md](../LIVE.md) | تب رونوشت‌برداری زنده |
| [DENOISE.md](../DENOISE.md) | حذف نویز تطبیقی |
| [SERVER.md](../SERVER.md) | حالت سرور وب / شبکه‌ی محلی |
| [CONFIG.md](../CONFIG.md) | همه‌ی کلیدهای پیکربندی |
| [BUILD.md](../BUILD.md) | ساخت برنامه از سورس |
| [CHANGELOG.md](../CHANGELOG.md) | تاریخچه‌ی نسخه‌ها |

> مستندات کامل به انگلیسی است. این صفحه یک نمای کلی است؛ برای جزئیات به اسناد انگلیسی مراجعه کنید.

## مجوز

کدِ مختص این پروژه تحت **مجوز BSD 3-Clause** منتشر شده — به [LICENSE](../../LICENSE) مراجعه کنید. باینری‌های همراه (`ffmpeg`، `ffprobe`، `yt-dlp`)، محیط اجرایی Python همراه و بسته‌های آن، و خودِ مدل Whisper مجوزهای اصلیِ خود را حفظ می‌کنند؛ [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) آن‌ها را خلاصه می‌کند.

---

<div align="center">
<sub>رونوشت‌برداری آفلاین · رابط گرافیکی Whisper محلی · تولیدکننده‌ی زیرنویس · تفکیک گوینده · Windows · macOS · Linux</sub>
</div>
