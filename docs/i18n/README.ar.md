<div align="center" dir="rtl">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**تفريغ صوتي مجاني دون اتصال بالإنترنت وترجمات مصاحبة للتسجيلات الطويلة بلغتك — على كمبيوتر محمول عادي، بدون حساب وبدون رفع ملفات الصوت.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![downloads](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/total?label=downloads&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [تحميل لنظام Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

أنظمة macOS و Linux: انظر [التحميل](#download).

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
<b>العربية</b> ·
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

<div dir="rtl">

## لمن هذا البرنامج

لمعدي الترجمات المصاحبة (Subtitlers) والمترجمين والباحثين والصحفيين الذين يحولون التسجيلات الطويلة (المقابلات والمحاضرات والمحادثات ومقاطع الفيديو) إلى نصوص أو ترجمات.
أسقط ملف صوت أو فيديو ليُكتب النص بجانبه. يعمل محرك التعرف على الكلام على جهازك الخاص، لذا لا توجد تكلفة لكل دقيقة، وبمجرد تنزيل النموذج، لا حاجة للاتصال بالإنترنت.

</div>

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="علامة تبويب Transcribe: منطقة لإسقاط الملفات، وأدوات اختيار المحرك واللغة، وخيارات تسميات المتحدثين والطوابع الزمنية للكلمات" width="80%">
</div>

<div dir="rtl">

## ما الجديد في 2.0

- **السرعة والوقت المتبقي:** تعرض علامة تبويب قائمة الانتظار سرعة كل مهمة والوقت التقريبي المتبقي.
- **فيديو مترجم من رابط:** قم بتنزيل وتفريغ صوتي ودمج الترجمات في الفيديو كمهمة واحدة ([docs/SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **النص كصفحة ويب:** ملف `.html` واحد مع إمكانية البحث والنقر للتشغيل يعمل دون إنترنت في أي متصفح.
- **العمل دون اتصال قابل للتحقق:** عند تفعيل العمل دون اتصال، يوضح شريط الحالة ما إذا كان التطبيق أو أي عملية بدأها يمتلك اتصالاً بالشبكة.
- **الترجمة إلى الإنجليزية:** يتحول الكلام بغير الإنجليزية إلى ترجمات إنجليزية في خطوة واحدة.
- **البدء السريع:** تطرح عمليات التثبيت الجديدة ثلاثة أسئلة، ويعرض مقطع تجريبي مدته 18 ثانية النتيجة على الفور.
- **الإبلاغ عن مشكلة:** من قائمة المساعدة، دون الحاجة لحساب GitHub.
- **نظام macOS:** قائمة التطبيق مع الإعدادات (Command-comma)، وضع الإضاءة الفاتح والداكن المتبع للنظام، والإشعارات. **نظام Windows:** تقدم في شريط المهام وأشرطة عناوين داكنة.

القائمة الكاملة: [CHANGELOG](../CHANGELOG.md).

## الميزات

- **محركات محلية:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (الافتراضي)، whisper.cpp و NVIDIA Parakeet، للعديد من اللغات التي يتعرف عليها Whisper. يستخدم وحدة معالجة الرسومات من NVIDIA عبر CUDA عندما يكون ذلك ممكناً، وإلا يستخدم وحدة المعالجة المركزية.
- **التطبيق بلغتك:** القوائم والأزرار والرسائل بـ 42 لغة (ترجمة آلية مع الإشارة إلى ذلك، والتصحيحات مرحَّب بها). يتبع لغة نظامك، أو يمكنك اختيار لغة من الإعدادات المتقدمة. الفارسية والعربية والعبرية متاحة على Windows حالياً.
- **14 تنسيقاً للمخرجات:** SRT و VTT و ASS و TSV و TXT و JSON و LRC و Markdown و DOCX و PDF، بالإضافة إلى تنسيقات oTranscribe و ELAN و InqScribe و Express Scribe. يكتب DOCX و PDF كل اللغات بشكل صحيح، حيث تُقرأ الفارسية والعربية والأردية من اليمين إلى اليسار مع أحرف متصلة.
- **صفحة ويب قابلة للمشاركة:** احفظ النص النهائي كملف `.html` واحد يعمل دون اتصال في أي متصفح؛ انقر على كلمة لسماعها، ابحث، وانتقل إلى الفصول المختلفة.
- **تسميات المتحدثين** بدون حساب Hugging Face، بالإضافة إلى طوابع زمنية للكلمات واقتطاع نطاق زمني.
- **استئناف المهام المنقطعة** من آخر نقطة حفظ لها بدلاً من البدء من جديد (للمحرك الافتراضي).
- **مقاطع الفيديو عبر الإنترنت:** قم بالتنزيل من أي موقع يدعمه [yt-dlp](https://github.com/yt-dlp/yt-dlp) وقم بالتفريغ الصوتي عند انتهاء التنزيل.
- **رابط لفيديو مترجم:** علامة اختيار واحدة تحول الرابط إلى `<title>-subbed.mp4` مع ترجمة مدمجة: قم بالتنزيل والنسخ والدمج في مهمة واحدة في قائمة الانتظار ([docs/SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **التفريغ الصوتي المباشر:** قم بتفريغ كلام الميكروفون صوتياً، أو صوت النظام في Windows، أثناء حدوثه ([docs/LIVE.md](../LIVE.md)).
- **قائمة انتظار الدفعات والمجلد المراقب** للعديد من الملفات.
- **وضع الشبكة المحلية:** صفحة تفريغ صوتي وواجهة برمجة تطبيقات (API) متوافقة مع OpenAI للأجهزة الأخرى على شبكتك ([docs/SERVER.md](../SERVER.md)).
- **اختياري، متوقف افتراضياً:** أدوات ذكاء اصطناعي للنص النهائي (ملخص، أسئلة، SRT ثنائي اللغة)، وتحويل النص إلى صوت دون إنترنت مع استنساخ الصوت.

مقارنة التطبيق مع Subtitle Edit، وVibe، وBuzz، وnoScribe، وaTrain، بما في ذلك الحالات التي يكون فيها تطبيق آخر خياراً أفضل:
**[docs/COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## التحميل

أحدث إصدار: **[صفحة الإصدارات](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| الملف | مخصص لـ |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | نظام Windows 10 أو 11 بنواة 64 بت. يفضل معظم الأشخاص هذا الملف. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | نظام Windows بدون تثبيت: قم بفك الضغط والتشغيل. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | أجهزة Mac بمعالجات Apple، ونظام macOS 14 أو أحدث. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | أجهزة Mac بمعالجات Intel، ونظام macOS 10.15 أو أحدث. |

يعمل Linux من المصدر الأساسي: [platform/linux/README.md](../../platform/linux/README.md).

برنامج FFmpeg المدمج هو بناء مرخص بـ GPL. يُرفق مصدره الأصلي بكل إصدار على شكل ملفات `WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*`؛ الروابط الدقيقة موجودة في [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

تم دمج ffmpeg و yt-dlp. عند التشغيل الأول، تختار نافذة البدء السريع نموذج التعرف على الكلام للغتك: سريع (صغير، حوالي 500 ميغابايت) أو أفضل جودة (حتى حوالي 3 غيغابايت)؛ يتم تنزيله مرة واحدة عند الاستخدام الأول. جهز 8 غيغابايت من ذاكرة الوصول العشوائي (RAM)؛ على وحدة المعالجة المركزية، تستغرق النماذج الكبيرة (Large) حوالي 1.5-2.5 ضعف طول الصوت والنماذج الصغيرة (Small) حوالي النصف، وحدة معالجة الرسومات (GPU) من NVIDIA أسرع بكثير. إصدارات Windows غير موقعة رقمياً وإصدارات Mac غير موثقة (notarized)، لذلك ستظهر تحذيرات من SmartScreen و Gatekeeper عند التشغيل الأول؛ يوضح [docs/INSTALL.md](../INSTALL.md) ما يجب النقر عليه. للتحديث، قم بتشغيل أداة التثبيت الأحدث فوق القديمة؛ يتم الاحتفاظ بالإعدادات.

**التحميلات حسب الإصدار** (تحسب كل شارة إصدارها الخاص فقط - تظل الإصدارات القديمة منشورة ولا يتم تصفير عدد تحميلاتها أبداً):

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

## ما الذي يخرج من جهازك

باستخدام الإعدادات الافتراضية، تبقى ملفات الصوت والنصوص على جهازك.
يستخدم التطبيق الشبكة من أجل:

- تنزيل نموذج أو مكون إضافي اختياري عند الحاجة إليه لأول مرة؛
- إعداداته عبر الإنترنت عند بدء التشغيل وفحص يومي للتحديثات على GitHub، والذي يخبرك فقط بوجود إصدار جديد؛
- إحصائيات الاستخدام، مُفعلة افتراضياً، بعد كل عملية تفريغ صوتي مكتملة: النموذج، اللغة، المدد، عدد الكلمات، إصدار التطبيق، نظام التشغيل، وحدة المعالجة المركزية وحجم الذاكرة، والمنطقة، وليس اسم الملف أبداً. قم بإيقاف تشغيلها من **Help → Usage statistics**.

يُرسل الصوت أو النص المُفرّغ فقط إذا اخترت محركاً سحابياً (Gemini API أو Google Cloud Speech-to-Text) أو قمت بتوصيل موفر ذكاء اصطناعي عن بعد بنفسك.
**File → Work offline** توقف كل هذا. كل اتصال مدرج في [docs/CONFIG.md](../CONFIG.md#network-use).

## الوثائق

[التثبيت](../INSTALL.md) · [التكوين](../CONFIG.md) ·
[التفريغ الصوتي المباشر](../LIVE.md) · [وضع الشبكة المحلية وواجهة برمجة التطبيقات](../SERVER.md) ·
[المحركات السحابية](../CLOUD_STT.md) · [البنية](../ARCHITECTURE.md) ·
[سجل التغييرات](../CHANGELOG.md) · [كل الوثائق](../README.md)

## البناء من المصدر

</div>
<div dir="ltr">

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

</div>

<div dir="rtl">

يتطلب Python 3.11 أو أحدث. مسارات البناء (Build pipelines): [docs/BUILD.md](../BUILD.md). الاختبارات وطلبات السحب (Pull requests):
[CONTRIBUTING.md](../../CONTRIBUTING.md).

## المساهمة والتواصل

- **الأخطاء وطلبات الميزات:** [مشكلات GitHub](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **الأسئلة والأفكار:** [نقاشات GitHub](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **كل شيء آخر:** عبر البريد الإلكتروني، من خلال [قسم التواصل في الموقع](https://whisper-transcriber-suite.com/#contact) · ✉ [admin@whisper-transcriber-suite.com](mailto:admin@whisper-transcriber-suite.com)
- **تقارير الأمان:** [SECURITY.md](../../SECURITY.md)

يتبع هذا المشروع [ميثاق المساهمين](../../.github/CODE_OF_CONDUCT.md).
إذا وفر لك التطبيق الوقت، فإن النجمة (Star) أعلى هذه الصفحة تساعد الأشخاص الآخرين في العثور عليه.

## كيف تم بناء هذا المشروع

يطوره المشرف بمساعدة مكثفة من مساعدي البرمجة بالذكاء الاصطناعي (أساساً Claude). يجب أن تنجح فحوصات النوع (Type checks) واختبارات الوحدة (Unit tests) قبل كل التزام (commit)، ويقوم نظام التكامل المستمر (CI) بتشغيلها مرة أخرى على Windows و Linux بعد كل دفع (push). تتضمن [قائمة مراجعة الإصدار](../RELEASE_PROCESS.md) اختبار تثبيت يدوي على جهاز حقيقي. الالتزامات (Commits) التي تتم بمساعدة الذكاء الاصطناعي تذكر الآن اسم النموذج في سطر `Assisted-by:`؛ العديد من الالتزامات الأقدم تحمل سطر `Co-Authored-By: Claude` بدلاً من ذلك.

## الترخيص

حقوق الطبع والنشر (c) 2026 translation-robot (co-author). يتواجد المشروع في هذا المستودع، [Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite). المصدر الخاص بالمشروع يخضع لـ [رخصة BSD 3-Clause](../../LICENSE). تحتفظ الأدوات المرفقة وبيئة تشغيل Python والنماذج بتراخيصها الخاصة؛ انظر [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

</div>
