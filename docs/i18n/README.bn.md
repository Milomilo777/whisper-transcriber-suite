<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**আপনার ভাষায় দীর্ঘ রেকর্ডিংয়ের জন্য সম্পূর্ণ বিনামূল্যে, অফলাইন ট্রান্সক্রিপশন এবং সাবটাইটেল — একটি সাধারণ ল্যাপটপে, কোনো অ্যাকাউন্ট ছাড়া এবং কোনো অডিও আপলোড না করেই।**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![downloads](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/total?label=downloads&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Windows-এর জন্য ডাউনলোড করুন](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS এবং Linux: [ডাউনলোড](#download) দেখুন।

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
<b>বাংলা</b> ·
<a href="README.fil.md">Filipino</a>
</p>

<!-- language-links:end -->
<!-- translated from README.md at commit 66585d5 -->

</div>

## এটি কাদের জন্য

সাবটাইটেল প্রস্তুতকারী, অনুবাদক, গবেষক এবং সাংবাদিকদের জন্য যারা দীর্ঘ রেকর্ডিং (সাক্ষাৎকার, বক্তৃতা, আলোচনা, ভিডিও) টেক্সট বা সাবটাইটেলে রূপান্তর করেন।
একটি অডিও বা ভিডিও ফাইল ছেড়ে দিন এবং এর ঠিক পাশেই ট্রান্সক্রিপ্ট লেখা হয়ে যাবে। স্পিচ ইঞ্জিনটি আপনার নিজের কম্পিউটারেই চলে, তাই প্রতি মিনিটের জন্য কোনো খরচ নেই এবং একবার মডেল ডাউনলোড হয়ে গেলে, ইন্টারনেট সংযোগেরও প্রয়োজন নেই।

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="Transcribe ট্যাব: ফাইল ফেলার জায়গা, ইঞ্জিন ও ভাষা বাছাইয়ের অংশ, বক্তার লেবেল ও শব্দের টাইমস্ট্যাম্পের অপশন" width="80%">
</div>

## 2.0-এ নতুন কী আছে

- **গতি এবং অবশিষ্ট সময়:** Queue (সারি) ট্যাব প্রতিটি কাজের গতি এবং আনুমানিক অবশিষ্ট সময় দেখায়।
- **লিঙ্ক থেকে সাবটাইটেলযুক্ত ভিডিও:** এক ধাপেই ডাউনলোড করুন, ট্রান্সক্রাইব করুন এবং সাবটাইটেল যুক্ত করুন ([docs/SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md))।
- **ওয়েব পেজ হিসেবে ট্রান্সক্রিপ্ট:** সার্চ এবং ক্লিক-টু-প্লে সুবিধা সহ একটি `.html` ফাইল যা যেকোনো ব্রাউজারে অফলাইনে কাজ করে।
- **যাচাইযোগ্য অফলাইন কাজ:** 'Work offline' চালু থাকলে, একটি স্ট্যাটাস লাইন দেখায় যে অ্যাপ বা এর দ্বারা শুরু হওয়া কোনো প্রক্রিয়ার নেটওয়ার্ক সংযোগ আছে কি না।
- **ইংরেজিতে অনুবাদ:** অ-ইংরেজি বক্তব্য এক ধাপেই ইংরেজি সাবটাইটেলে পরিণত হয়।
- **কুইক স্টার্ট:** নতুন ইনস্টলেশনে তিনটি প্রশ্ন জিজ্ঞাসা করে এবং একটি ১৮-সেকেন্ডের নমুনা ক্লিপ তাৎক্ষণিক ফলাফল দেখায়।
- **সমস্যার রিপোর্ট করুন:** কোনো GitHub অ্যাকাউন্ট ছাড়াই Help মেনু থেকে।
- **macOS:** সেটিংস সহ অ্যাপ মেনু (Command-comma), সিস্টেম অনুযায়ী লাইট এবং ডার্ক মোড, নোটিফিকেশন। **Windows:** টাস্কবার প্রগ্রেস এবং ডার্ক টাইটেল বার।

সম্পূর্ণ তালিকা: [CHANGELOG](../CHANGELOG.md)।

## বৈশিষ্ট্যসমূহ

- **লোকাল ইঞ্জিন:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (ডিফল্ট), whisper.cpp এবং NVIDIA Parakeet, Whisper যে সমস্ত ভাষা চিনতে পারে তার জন্য। সম্ভব হলে CUDA-এর মাধ্যমে একটি NVIDIA GPU ব্যবহার করে, অন্যথায় CPU ব্যবহার করে।
- **আপনার ভাষায় অ্যাপ:** মেনু, বোতাম ও বার্তা 42টি ভাষায় (মেশিন অনুবাদ, সেটি চিহ্নিত করা আছে; সংশোধন স্বাগত)। এটি আপনার সিস্টেমের ভাষা অনুসরণ করে, অথবা উন্নত সেটিংসে আপনি একটি ভাষা বেছে নিতে পারেন। আপাতত ফার্সি, আরবি ও হিব্রু Windows-এ পাওয়া যায়।
- **১৪টি আউটপুট ফরম্যাট:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX এবং PDF, এর সাথে oTranscribe, ELAN, InqScribe এবং Express Scribe ফরম্যাট। DOCX এবং PDF প্রতিটি স্ক্রিপ্ট সঠিকভাবে লেখে, এবং ফার্সি, আরবি এবং উর্দু ডান দিক থেকে বামে যুক্ত অক্ষরের সাথে পড়া যায়।
- **শেয়ার করার যোগ্য ওয়েব পেজ:** একটি সম্পন্ন ট্রান্সক্রিপ্ট একটি `.html` ফাইল হিসেবে সেভ করুন যা যেকোনো ব্রাউজারে অফলাইনে কাজ করে; শোনার জন্য একটি শব্দে ক্লিক করুন, সার্চ করুন, চ্যাপ্টারগুলোতে যান।
- **স্পিকার লেবেল:** কোনো Hugging Face অ্যাকাউন্ট ছাড়াই, এর সাথে শব্দের টাইমস্ট্যাম্প এবং টাইম-রেঞ্জ ক্লিপিং সুবিধা।
- **বাধাগ্রস্ত কাজ আবার শুরু হয়:** ডিফল্ট ইঞ্জিনের সাহায্যে, বাধাগ্রস্ত কাজগুলো প্রথম থেকে শুরু হওয়ার বদলে তাদের শেষ চেকপয়েন্ট থেকে আবার শুরু হয়।
- **অনলাইন ভিডিও:** [yt-dlp](https://github.com/yt-dlp/yt-dlp) সমর্থন করে এমন যেকোনো সাইট থেকে ডাউনলোড করুন এবং ডাউনলোড শেষ হলে ট্রান্সক্রাইব করুন।
- **সাবটাইটেলযুক্ত ভিডিওর লিঙ্ক:** একটিমাত্র টিক একটি লিঙ্ককে সাবটাইটেলযুক্ত `<title>-subbed.mp4`-এ পরিণত করে: সারিবদ্ধ একটি কাজের মাধ্যমেই ডাউনলোড করুন, ট্রান্সক্রাইব করুন এবং সাবটাইটেল যুক্ত করুন ([docs/SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md))।
- **লাইভ:** কথা বলার সাথে সাথেই মাইক্রোফোন বা Windows-এ সিস্টেম অডিও ট্রান্সক্রাইব করুন ([docs/LIVE.md](../LIVE.md))।
- **ব্যাচ সারি এবং ওয়াচড ফোল্ডার:** অনেক ফাইলের জন্য।
- **লোকাল-নেটওয়ার্ক মোড:** আপনার নেটওয়ার্কের অন্যান্য ডিভাইসের জন্য একটি ট্রান্সক্রিপশন পেজ এবং একটি OpenAI-সামঞ্জস্যপূর্ণ API ([docs/SERVER.md](../SERVER.md))।
- **ঐচ্ছিক, ডিফল্টরূপে বন্ধ:** একটি সম্পন্ন ট্রান্সক্রিপ্টের জন্য AI টুল (সারাংশ, প্রশ্ন, দ্বিভাষিক SRT), এবং ভয়েস ক্লোনিং সহ অফলাইন টেক্সট-টু-ভয়েস।

Subtitle Edit, Vibe, Buzz, noScribe এবং aTrain-এর সাথে এর তুলনা কেমন, এবং কখন অন্য অ্যাপ ভালো বিকল্প হতে পারে তা সহ:
**[docs/COMPARISON.md](../COMPARISON.md)**।

<a id="download"></a>

## ডাউনলোড

সর্বশেষ রিলিজ: **[রিলিজ পেজ](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**।

| ফাইল | কাদের জন্য |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 বা 11, 64-বিট। বেশিরভাগ মানুষ এটাই চান। |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | ইনস্টল না করেই Windows: আনজিপ করে চালান। |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Apple সিলিকন যুক্ত Mac, macOS 14 বা নতুন। |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Intel Mac, macOS 10.15 বা নতুন। |

Linux সোর্স থেকে চলে: [platform/linux/README.md](../../platform/linux/README.md)।

বান্ডেল করা FFmpeg একটি GPL বিল্ড। এর সংশ্লিষ্ট সোর্স প্রতিটি রিলিজের সাথে `WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*` ফাইল হিসেবে সংযুক্ত থাকে; সঠিক লিঙ্কগুলো [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md)-এ রয়েছে।

ffmpeg এবং yt-dlp বান্ডেল করা আছে। প্রথমবার লঞ্চ করার সময় একটি কুইক স্টার্ট উইন্ডো আপনার ভাষার জন্য স্পিচ মডেল বেছে নেয়: দ্রুত (ছোট, প্রায় 500 MB) বা সেরা মানের (প্রায় 3 GB পর্যন্ত); এটি প্রথম ব্যবহারের সময় একবার ডাউনলোড হয়। 8 GB RAM-এর পরিকল্পনা করুন; CPU-তে বড় (Large) মডেলগুলো অডিওর দৈর্ঘ্যের প্রায় ১.৫-২.৫ গুণ সময় নেয় এবং ছোট (Small) মডেলগুলো প্রায় অর্ধেক সময় নেয়, NVIDIA GPU অনেক দ্রুত কাজ করে। Windows বিল্ডগুলো কোড-সাইন করা নয় এবং Mac বিল্ডগুলো নোটারাইজ করা নয়, তাই প্রথমবার লঞ্চ করার সময় SmartScreen এবং Gatekeeper সতর্ক করে; [docs/INSTALL.md](../INSTALL.md) দেখায় কোথায় ক্লিক করতে হবে। আপডেট করার জন্য, পুরানোটির উপরে নতুন ইনস্টলারটি চালান; সেটিংস সংরক্ষিত থাকবে।

**সংস্করণ অনুযায়ী ডাউনলোড** (প্রতিটি ব্যাজ শুধুমাত্র সেই সংস্করণের নিজস্ব রিলিজ গণনা করে — পুরানো সংস্করণগুলো প্রকাশিত থাকে এবং তাদের গণনা কখনোই রিসেট হয় না):

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

## আপনার কম্পিউটার থেকে কী বাইরে যায়

ডিফল্ট সেটিংসের সাহায্যে আপনার অডিও এবং ট্রান্সক্রিপ্টগুলো আপনার কম্পিউটারেই থাকে।
অ্যাপটি নিচের কাজের জন্য নেটওয়ার্ক ব্যবহার করে:

- প্রথমবারের মতো প্রয়োজন হলে একটি মডেল বা ঐচ্ছিক উপাদান ডাউনলোড করার জন্য;
- স্টার্টআপের সময় এর অনলাইন সেটিংস এবং GitHub-এ দৈনিক আপডেট চেকের জন্য, যা আপনাকে শুধু নতুন সংস্করণ সম্পর্কে জানায়;
- প্রতিটি ট্রান্সক্রিপশন শেষ হওয়ার পর ব্যবহারের পরিসংখ্যানের জন্য (ডিফল্টরূপে চালু): মডেল, ভাষা, সময়কাল, শব্দ সংখ্যা, অ্যাপের সংস্করণ, অপারেটিং সিস্টেম, CPU এবং মেমোরির আকার, এবং অঞ্চল, কিন্তু কখনোই ফাইলের নাম নয়। এগুলো **Help → Usage statistics** থেকে বন্ধ করতে পারেন।

অডিও বা ট্রান্সক্রিপ্ট টেক্সট শুধুমাত্র তখনই পাঠানো হয় যদি আপনি কোনো ক্লাউড ইঞ্জিন (Gemini API বা Google Cloud Speech-to-Text) বেছে নেন অথবা নিজে কোনো রিমোট AI প্রদানকারী সংযুক্ত করেন।
**File → Work offline** এগুলোর সবকিছু বন্ধ করে দেয়। প্রতিটি সংযোগ [docs/CONFIG.md](../CONFIG.md#network-use)-এ তালিকাভুক্ত আছে।

## ডকুমেন্টেশন

[ইনস্টল করুন](../INSTALL.md) · [কনফিগারেশন](../CONFIG.md) ·
[লাইভ ট্রান্সক্রিপশন](../LIVE.md) · [লোকাল-নেটওয়ার্ক মোড এবং API](../SERVER.md) ·
[ক্লাউড ইঞ্জিন](../CLOUD_STT.md) · [আর্কিটেকচার](../ARCHITECTURE.md) ·
[চেঞ্জলগ](../CHANGELOG.md) · [সকল ডক্স](../README.md)

## সোর্স থেকে তৈরি করুন

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Python 3.11 বা নতুন সংস্করণ প্রয়োজন। বিল্ড পাইপলাইন: [docs/BUILD.md](../BUILD.md)। টেস্ট এবং পুল রিকোয়েস্ট:
[CONTRIBUTING.md](../../CONTRIBUTING.md)।

## অবদান এবং যোগাযোগ

- **বাগ এবং ফিচারের অনুরোধ:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **প্রশ্ন এবং ধারণা:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **অন্য সবকিছু:** ইমেলের মাধ্যমে, [ওয়েবসাইটের কন্টাক্ট সেকশনের](https://whisper-transcriber-suite.com/#contact) মাধ্যমে
- **সিকিউরিটি রিপোর্ট:** [SECURITY.md](../../SECURITY.md)

এই প্রজেক্টটি [কন্ট্রিবিউটর কভেন্যান্ট (Contributor Covenant)](../../.github/CODE_OF_CONDUCT.md) অনুসরণ করে।
যদি এই অ্যাপটি আপনার সময় বাঁচায়, তবে এই পৃষ্ঠার শীর্ষে থাকা একটি Star (স্টার) অন্য লোকেদের এটি খুঁজে পেতে সাহায্য করে।

## কীভাবে এই প্রজেক্ট তৈরি করা হয়েছে

মেইনটেইনার এটি এআই কোডিং সহকারীর (মূলত Claude) ব্যাপক সাহায্যে ডেভেলপ করেন। প্রতিটি কমিটের আগে টাইপ চেক এবং ইউনিট টেস্ট পাস হতে হবে এবং CI প্রতিটি পুশের পরে Windows এবং Linux-এ সেগুলোকে আবার চালায়। [রিলিজ চেকলিস্ট](../RELEASE_PROCESS.md)-এ বাস্তব মেশিনে ম্যানুয়াল ইনস্টল টেস্ট অন্তর্ভুক্ত রয়েছে। এআই-এর সাহায্যে তৈরি কমিটগুলোতে এখন `Assisted-by:` লাইনে মডেলটির নাম থাকে; পুরনো অনেক কমিটে এর পরিবর্তে `Co-Authored-By: Claude` লাইনটি রয়েছে।

## লাইসেন্স

কপিরাইট (c) 2026 translation-robot (co-author)। এই প্রজেক্টটি এই রিপোজিটরিতে রয়েছে, [Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite)। প্রজেক্টের নিজস্ব সোর্স [BSD 3-Clause License](../../LICENSE)-এর অধীনে রয়েছে। বান্ডেল করা টুল, Python রানটাইম এবং মডেলগুলোর নিজস্ব লাইসেন্স রয়েছে; [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) দেখুন।
