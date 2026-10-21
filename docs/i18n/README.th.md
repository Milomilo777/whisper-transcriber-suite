<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**ถอดเสียงและสร้างซับไตเติลแบบออฟไลน์ได้ฟรีสำหรับไฟล์เสียงยาวๆ ในภาษาของคุณ — ทำงานบนแล็ปท็อปทั่วไป ไม่ต้องมีบัญชีผู้ใช้และไม่ต้องอัปโหลดไฟล์เสียง**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![downloads](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/total?label=downloads&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [ดาวน์โหลดสำหรับ Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS และ Linux: ดูที่ [Download](#download)

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
<b>ไทย</b> ·
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

## สำหรับใคร

เหมาะสำหรับนักทำซับไตเติล นักแปล นักวิจัย และนักข่าว ที่ต้องการแปลงไฟล์เสียงที่ยาว
(บทสัมภาษณ์ เลกเชอร์ การบรรยาย วิดีโอ) ให้เป็นข้อความหรือซับไตเติล
เพียงแค่ลากไฟล์เสียงหรือวิดีโอลงมา โปรแกรมก็จะเขียนข้อความถอดเสียงไว้ในโฟลเดอร์เดียวกัน ระบบรับรู้เสียงทำงานบนคอมพิวเตอร์ของคุณเอง ดังนั้นจึง
ไม่ต้องเสียค่าใช้จ่ายรายนาที และเมื่อดาวน์โหลดโมเดลเสร็จแล้ว ก็ไม่จำเป็นต้องใช้การเชื่อมต่ออินเทอร์เน็ตอีกต่อไป

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="แท็บ Transcribe: พื้นที่วางไฟล์ ตัวเลือกเอ็นจินและภาษา ตัวเลือกป้ายชื่อผู้พูดและเวลากำกับรายคำ" width="80%">
</div>

## มีอะไรใหม่ในเวอร์ชัน 2.0

- **แสดงความเร็วและเวลาที่เหลือ:** แถบ Queue จะแสดงความเร็วในการทำงานและเวลาที่เหลือโดยประมาณของแต่ละคิว
- **วิดีโอพร้อมซับไตเติลจากลิงก์:** ดาวน์โหลด ถอดเสียง และฝังซับไตเติลลงในวิดีโอให้เสร็จในงานเดียว ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md))
- **ข้อความถอดเสียงในรูปแบบหน้าเว็บ:** ไฟล์ `.html` เดียวที่มีระบบค้นหาและคลิกเพื่อเล่นเสียง ทำงานแบบออฟไลน์ได้บนทุกเบราว์เซอร์
- **ตรวจสอบสถานะเมื่อทำงานออฟไลน์:** เมื่อเปิด Work offline แถบสถานะจะแสดงให้เห็นว่าแอปหรือโปรเซสที่เกี่ยวข้องมีการเชื่อมต่อเครือข่ายอยู่หรือไม่
- **แปลเป็นภาษาอังกฤษ:** แปลงเสียงพูดภาษาอื่นๆ ให้เป็นซับไตเติลภาษาอังกฤษได้ในขั้นตอนเดียว
- **เริ่มต้นใช้งานอย่างรวดเร็ว:** การติดตั้งใหม่จะถามคำถามเพียง 3 ข้อ พร้อมตัวอย่างคลิป 18 วินาทีเพื่อให้เห็นผลลัพธ์ได้ทันที
- **รายงานปัญหา** ได้จากเมนู Help โดยไม่ต้องมีบัญชี GitHub
- **macOS:** เพิ่มเมนูแอปพร้อมเมนู Settings (Command-comma), ธีมสว่างและธีมมืดที่เปลี่ยนตามระบบ, ระบบแจ้งเตือน **Windows:** แสดงความคืบหน้าบนทาสก์บาร์และแถบชื่อเรื่องแบบธีมมืด

ดูรายการทั้งหมดได้ที่: [CHANGELOG](../CHANGELOG.md)

## คุณสมบัติ

- **เอ็นจินแบบโลคัล (รันบนเครื่อง):** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (ค่าเริ่มต้น), whisper.cpp และ NVIDIA Parakeet รองรับหลากหลายภาษาที่ Whisper 
  สามารถจำแนกได้ โปรแกรมจะใช้ NVIDIA GPU 
  ผ่าน CUDA เมื่อทำได้ หากไม่รองรับก็จะใช้ CPU แทน
- **แอปในภาษาของคุณ:** เมนู ปุ่ม และข้อความมี 42 ภาษา
  (แปลด้วยเครื่องและระบุไว้ว่าเป็นเช่นนั้น ยินดีรับคำแนะนำแก้ไข)
  แอปจะใช้ภาษาตามระบบของคุณ หรือคุณเลือกภาษาได้ในการตั้งค่าขั้นสูง
  ขณะนี้ภาษาเปอร์เซีย อาหรับ และฮีบรูมีให้ใช้บนระบบ Windows
- **ฟอร์แมตเอาต์พุต 14 แบบ:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX และ
  PDF รวมไปถึงฟอร์แมตสำหรับ oTranscribe, ELAN, InqScribe และ Express Scribe ทั้งนี้ DOCX
  และ PDF รองรับการเขียนทุกสคริปต์ภาษา รวมถึงการอ่านจากขวาไปซ้ายและตัวอักษรเชื่อมในภาษาเปอร์เซีย อาหรับ และอูรดู
- **หน้าเว็บสำหรับแชร์:** บันทึกข้อความถอดเสียงที่เสร็จแล้วเป็นไฟล์ `.html` ไฟล์เดียว
  ที่ใช้งานแบบออฟไลน์ได้บนเบราว์เซอร์ใดก็ได้; คลิกที่คำเพื่อฟังเสียง ค้นหา และข้ามไปยังบทต่างๆ ได้
- **ระบุตัวผู้พูด** โดยไม่ต้องใช้บัญชี Hugging Face พร้อมด้วยการประทับเวลาสำหรับแต่ละคำและ
  การตัดคลิปเสียงตามช่วงเวลา
- **ทำงานต่อจากจุดที่ค้างไว้:** หากงานถูกขัดจังหวะ โปรแกรมจะเริ่มทำงานต่อจากจุดตรวจสอบ (checkpoint) ล่าสุด แทนที่จะต้องเริ่มใหม่
  (สำหรับเอ็นจินเริ่มต้น)
- **วิดีโอออนไลน์:** ดาวน์โหลดจากเว็บไซต์ใดก็ได้ที่ [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  รองรับ และเริ่มการถอดเสียงทันทีเมื่อดาวน์โหลดเสร็จ
- **ลิงก์เป็นวิดีโอพร้อมซับไตเติล:** ติ๊กเพียงครั้งเดียวเพื่อเปลี่ยนลิงก์ให้เป็นไฟล์ `<title>-subbed.mp4`
  ที่มีซับไตเติลฝังอยู่: จัดคิวดาวน์โหลด ถอดเสียง และฝังซับไว้ในคิวเดียวกัน
  ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md))
- **แบบสด (Live):** ถอดเสียงจากไมโครโฟน (หรือระบบเสียงของเครื่องใน Windows) ได้แบบเรียลไทม์
  ([../LIVE.md](../LIVE.md))
- **คิวแบบกลุ่มและโฟลเดอร์เฝ้าดู (Watched folder)** สำหรับจัดการไฟล์จำนวนมาก
- **โหมดเครือข่ายท้องถิ่น (Local-network):** เปิดหน้าเว็บสำหรับถอดเสียงและ API ที่เข้ากันได้กับ OpenAI 
  เพื่อให้อุปกรณ์อื่นๆ ในเครือข่ายของคุณใช้งานได้ ([../SERVER.md](../SERVER.md))
- **เครื่องมือ AI เสริม (ค่าเริ่มต้นคือปิด):** สรุปเนื้อหา ถามคำถาม และสร้าง SRT สองภาษาจากข้อความถอดเสียงที่เสร็จสมบูรณ์ รวมถึงฟีเจอร์แปลงข้อความเป็นเสียงพูดแบบออฟไลน์พร้อมการโคลนเสียง

เปรียบเทียบแอปนี้กับ Subtitle Edit, Vibe, Buzz, noScribe และ aTrain
รวมถึงกรณีที่แอปอื่นๆ อาจเป็นทางเลือกที่ดีกว่า:
**[../COMPARISON.md](../COMPARISON.md)**

<a id="download"></a>

## ดาวน์โหลด

เวอร์ชันล่าสุด: **[หน้า releases](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**

| ไฟล์ | สำหรับ |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 หรือ 11 แบบ 64-bit (ผู้ใช้ส่วนใหญ่แนะนำตัวนี้) |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows แบบไม่ต้องติดตั้ง: แตกไฟล์และใช้งานได้เลย |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Mac ที่ใช้ Apple silicon, macOS 14 หรือใหม่กว่า |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Mac ที่ใช้ Intel, macOS 10.15 หรือใหม่กว่า |

Linux ต้องรันจากซอร์สโค้ด: [../../platform/linux/README.md](../../platform/linux/README.md)

FFmpeg ที่มาพร้อมแอปเป็นบิลด์แบบ GPL ซอร์สโค้ดที่เกี่ยวข้องได้แนบไว้ในแต่ละรีลีสในชื่อไฟล์
`WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*`; ดูลิงก์ที่แน่นอนได้ใน
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md)

แอปมาพร้อมกับ ffmpeg และ yt-dlp ในตัว เมื่อเปิดแอปครั้งแรก หน้าต่างเริ่มต้นใช้งานด่วนจะให้คุณเลือก
โมเดลเสียงสำหรับภาษาของคุณ: แบบ Fast (Small ประมาณ 500 MB) หรือ Best
quality (คุณภาพดีที่สุด ขนาดใหญ่สุดประมาณ 3 GB); ระบบจะดาวน์โหลดเพียงครั้งเดียวในการใช้งานครั้งแรก แนะนำให้มี RAM 
ขนาด 8 GB; สำหรับ CPU การทำงานด้วยโมเดล Large จะใช้เวลาประมาณ 1.5–2.5 เท่าของความยาว
ไฟล์เสียง และโมเดล Small จะใช้เวลาประมาณครึ่งหนึ่ง การมี NVIDIA GPU จะทำให้เร็วขึ้นมาก เนื่องจากแอปบน Windows ยังไม่ได้ผ่านการ sign โค้ด และแอปบน Mac ยังไม่ได้ถูก notarize จึงอาจมีคำเตือนจาก SmartScreen และ Gatekeeper เมื่อเปิดใช้ครั้งแรก;
[../INSTALL.md](../INSTALL.md) จะแสดงวิธีตั้งค่าให้ข้ามคำเตือนนี้ ในการอัปเดต ให้รันตัวติดตั้งเวอร์ชันใหม่ทับเวอร์ชันเดิมได้เลย โดยการตั้งค่าจะยังคงอยู่

**ยอดดาวน์โหลดแยกตามเวอร์ชัน** (แต่ละป้ายจะนับเฉพาะการดาวน์โหลดของเวอร์ชันนั้น — เวอร์ชันเก่าจะยังคงเปิดให้ดาวน์โหลดและไม่ถูกรีเซ็ตยอดนับ):

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

## ข้อมูลอะไรที่ถูกส่งออกจากคอมพิวเตอร์ของคุณบ้าง

ในตั้งค่าเริ่มต้น ข้อมูลเสียงและข้อความถอดเสียงของคุณจะอยู่แต่ในคอมพิวเตอร์ของคุณเท่านั้น
แอปจะใช้เครือข่ายสำหรับกรณีดังนี้เท่านั้น:

- การดาวน์โหลดโมเดลหรือคอมโพเนนต์เสริมในการใช้งานครั้งแรก
- ตรวจสอบตั้งค่าแบบออนไลน์ขณะเริ่มแอปและตรวจสอบอัปเดตเวอร์ชันใหม่ทุกวันจาก GitHub ซึ่ง
  จะแจ้งเตือนเมื่อมีเวอร์ชันใหม่เท่านั้น
- การส่งสถิติการใช้งาน ซึ่งจะเปิดเป็นค่าเริ่มต้น โดยจะส่งสถิติหลังจากที่ถอดเสียงเสร็จในแต่ละครั้ง: โมเดล,
  ภาษา, ระยะเวลา, จำนวนคำ, เวอร์ชันแอป, ระบบปฏิบัติการ, CPU และขนาดหน่วยความจำ และ
  ภูมิภาค โดยจะไม่เคยส่งชื่อไฟล์ คุณสามารถปิดได้ที่ **Help → Usage statistics**

ข้อมูลเสียงหรือข้อความที่ถอดจะถูกส่งออกเฉพาะเมื่อคุณเลือกใช้เอนจินคลาวด์ (Gemini API 
หรือ Google Cloud Speech-to-Text) หรือทำการเชื่อมต่อกับผู้ให้บริการ AI ภายนอกด้วยตัวคุณเองเท่านั้น
เมนู **File → Work offline** จะทำการหยุดการทำงานเหล่านี้ทั้งหมด คุณสามารถดูรายการการเชื่อมต่อทั้งหมดได้ใน
[../CONFIG.md](../CONFIG.md#network-use)

## เอกสาร (Documentation)

[การติดตั้ง](../INSTALL.md) · [การกำหนดค่า](../CONFIG.md) ·
[ถอดเสียงแบบสด](../LIVE.md) · [โหมดเครือข่ายท้องถิ่นและ API](../SERVER.md) ·
[เอ็นจินคลาวด์](../CLOUD_STT.md) · [สถาปัตยกรรมแอป](../ARCHITECTURE.md) ·
[บันทึกการเปลี่ยนแปลง (Changelog)](../CHANGELOG.md) · [เอกสารทั้งหมด](../README.md)

## บิลด์จากซอร์สโค้ด

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

ต้องใช้ Python 3.11 หรือใหม่กว่า ไปป์ไลน์การบิลด์: [../BUILD.md](../BUILD.md) การทดสอบและการส่ง pull request:
[../../CONTRIBUTING.md](../../CONTRIBUTING.md)

## การมีส่วนร่วมและการติดต่อ

- **รายงานบั๊กและขอฟีเจอร์ใหม่:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **คำถามและไอเดีย:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **ช่องทางอื่นๆ:** ทางอีเมล ผ่านทาง
  [ส่วน Contact ในหน้าเว็บไซต์](https://whisper-transcriber-suite.com/#contact) · ✉ [admin@whisper-transcriber-suite.com](mailto:admin@whisper-transcriber-suite.com)
- **การรายงานความปลอดภัย:** [../../SECURITY.md](../../SECURITY.md)

โปรเจ็กต์นี้ปฏิบัติตาม [Contributor Covenant](../../.github/CODE_OF_CONDUCT.md)
ถ้าแอปนี้ช่วยให้คุณประหยัดเวลาได้ การให้ดาว (Star) ที่ด้านบนของหน้านี้จะช่วยให้ผู้อื่น
หาแอปนี้เจอง่ายขึ้น

## โปรเจ็กต์นี้สร้างขึ้นมาอย่างไร

ผู้ดูแลโปรเจ็กต์นี้พัฒนาโดยได้รับความช่วยเหลืออย่างมากจากผู้ช่วยเขียนโค้ด AI (หลักๆ คือ Claude) การอัปเดตโค้ดต้องผ่านการตรวจสอบประเภทข้อมูล (Type checks) 
และการทดสอบ unit tests ก่อนการ commit แต่ละครั้ง และระบบ CI จะทำการทดสอบอีกครั้งบน Windows และ Linux 
หลังจากแต่ละการ push รายการตรวจสอบเมื่อปล่อยเวอร์ชันใหม่ ([docs/RELEASE_PROCESS.md](../RELEASE_PROCESS.md)) รวมไปถึงการทดสอบการติดตั้งด้วยมือบน
เครื่องจริงด้วย การ commit โค้ดที่มีความช่วยเหลือจาก AI ตอนนี้จะมีชื่อโมเดลในบรรทัด `Assisted-by:`; สำหรับการ commit 
เก่าๆ มักจะมีบรรทัด `Co-Authored-By: Claude` แทน

## ไลเซนส์ (License)

Copyright (c) 2026 translation-robot (co-author). โปรเจ็กต์นี้อยู่บน repository 
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite)
ซอร์สโค้ดของโปรเจ็กต์นี้อยู่ภายใต้ [BSD 3-Clause License](../../LICENSE) 
แต่ไลบรารีเครื่องมือที่พ่วงมาด้วย, ตัวรันไทม์ Python, และตัวโมเดลจะใช้ไลเซนส์ของตนเอง; กรุณาดูที่
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md)
