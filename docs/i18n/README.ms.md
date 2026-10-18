<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**Transkripsi dan sarikata luar talian percuma untuk rakaman panjang dalam bahasa anda — pada komputer riba biasa, tanpa akaun dan tanpa muat naik audio.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Muat turun untuk Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS dan Linux: lihat [Download](#download).

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
<b>Bahasa Melayu</b> ·
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

## Untuk siapa aplikasi ini

Pencipta sarikata, penterjemah, penyelidik dan wartawan yang mengubah rakaman
panjang (temu bual, kuliah, ceramah, video) menjadi teks atau sarikata.
Tarik dan lepaskan fail audio atau video, dan transkrip akan dihasilkan di folder yang sama. Sistem pengecaman pertuturan berjalan pada komputer anda sendiri, jadi tidak
ada kos seminit dan, sebaik model dimuat turun, sambungan internet tidak
diperlukan.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="Tab Transcribe: kawasan untuk menjatuhkan fail, pemilih enjin dan bahasa, pilihan label penutur dan cap masa setiap perkataan" width="80%">
</div>

## Apa yang baru dalam 2.0

- **Kelajuan dan baki masa:** tab Queue menunjukkan kelajuan setiap tugas dan anggaran baki masa.
- **Video dengan sarikata dari pautan:** muat turun, transkripsikan dan menyatukan (burn in) sarikata sebagai satu tugasan ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Transkrip sebagai laman web:** satu fail `.html` dengan carian dan click-to-play yang berfungsi di luar talian dalam mana-mana pelayar web.
- **Status Work offline yang jelas:** dengan Work offline dihidupkan, baris status menunjukkan sama ada aplikasi atau proses yang dimulakannya mempunyai sambungan rangkaian.
- **Terjemah ke bahasa Inggeris:** pertuturan dalam bahasa selain bahasa Inggeris akan diterjemahkan menjadi sarikata bahasa Inggeris dalam satu langkah.
- **Quick start:** pemasangan baru menanyakan tiga soalan, dan sampel klip 18 saat terus menunjukkan hasil.
- **Report a problem** dari Help, tanpa akaun GitHub.
- **macOS:** menu aplikasi dengan Settings (Command-koma), Light dan Dark yang mengikut sistem, pemberitahuan. **Windows:** progres taskbar dan title bar gelap.

Senarai penuh: [CHANGELOG](../CHANGELOG.md).

## Ciri-ciri

- **Enjin setempat:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (default), whisper.cpp dan NVIDIA Parakeet, untuk pelbagai bahasa yang dikenali
  Whisper. Menggunakan GPU NVIDIA
  melalui CUDA apabila boleh, jika tidak CPU.
- **Aplikasi dalam bahasa anda:** Menu, butang dan mesej dalam 42 bahasa (diterjemah
  oleh mesin dan ditandakan sedemikian; pembetulan dialu-alukan). Ia mengikut bahasa
  sistem anda, atau anda boleh memilih satu dalam Tetapan lanjutan. Bahasa Parsi,
  Arab dan Ibrani buat masa ini ditawarkan pada Windows.
- **14 format output:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX dan
  PDF, ditambah format oTranscribe, ELAN, InqScribe dan Express Scribe. DOCX
  dan PDF memaparkan setiap aksara dengan tepat, dan Parsi, Arab serta Urdu dibaca dari kanan ke kiri
  dengan huruf-huruf bersambung.
- **Laman web yang boleh dikongsi:** simpan transkrip yang siap sebagai satu fail `.html` yang
  berfungsi di luar talian dalam mana-mana pelayar; klik perkataan untuk mendengarnya, cari, lompat ke bab.
- **Speaker labels** tanpa akaun Hugging Face, ditambah word timestamps dan
  time-range clipping.
- **Tugas terganggu disambung semula** dari checkpoint terakhir dan bukannya mula
  dari awal (enjin default).
- **Video dalam talian:** muat turun dari mana-mana laman yang disokong oleh [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  dan transkripsikan apabila muat turun selesai.
- **Pautan ke video bersarikata:** satu tanda semak menukar pautan menjadi `<title>-subbed.mp4`
  berserta sarikata yang telah disatukan (burn in): muat turun, transkripsi dan satukan sarikata dalam satu tugasan beratur
  ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Live:** transkripsikan mikrofon, atau audio sistem pada Windows, secara
  langsung (real-time) ([../LIVE.md](../LIVE.md)).
- **Batch queue dan watched folder** untuk memproses banyak fail serentak.
- **Local-network mode:** laman transkripsi dan API serasi OpenAI untuk
  peranti lain di rangkaian anda ([../SERVER.md](../SERVER.md)).
- **Pilihan, dimatikan (off) secara default:** Alat AI untuk transkrip yang telah siap (ringkasan,
  soalan, SRT dwibahasa), dan ciri teks ke suara luar talian (text-to-voice) dengan kebolehan mengklon suara.

Perbandingan dengan Subtitle Edit, Vibe, Buzz, noScribe dan aTrain,
termasuk bila aplikasi lain adalah pilihan yang lebih baik:
**[../COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Download

Keluaran terbaru: **[releases page](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| Fail | Untuk |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 atau 11, 64-bit. Kebanyakan orang memerlukan yang ini. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows tanpa pemasangan: unzip dan jalankan. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Mac dengan Apple silicon, macOS 14 atau lebih baru. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Intel Mac, macOS 10.15 atau lebih baru. |

Linux dijalankan dari sumber: [../../platform/linux/README.md](../../platform/linux/README.md).

FFmpeg yang disertakan ialah binaan GPL. Sumbernya dilampirkan pada setiap keluaran sebagai
fail `WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*`; pautan tepat ada di
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

ffmpeg dan yt-dlp sudah disertakan. Semasa pelancaran pertama, tetingkap quick start memilih
model pertuturan untuk bahasa anda: Fast (Small, sekitar 500 MB) atau Best
quality (hingga sekitar 3 GB); ia dimuat turun sekali, pada penggunaan pertama. Rancang untuk 8 GB
RAM; pada CPU model Large memerlukan masa memproses sekitar 1.5–2.5 kali ganda durasi
audio, manakala model Small mengambil masa separuh daripadanya, GPU NVIDIA jauh lebih pantas. Binaan (build) Windows tidak dilengkapi code-sign dan binaan Mac tidak
dinotarisasi, jadi SmartScreen dan Gatekeeper memberi amaran pada pelancaran pertama;
[../INSTALL.md](../INSTALL.md) menunjukkan apa yang perlu diklik. Untuk mengemas kini, jalankan pemasang
baru menindih yang lama; tetapan dikekalkan.

**Muat turun mengikut versi** (setiap lencana hanya mengira keluaran
versi tersebut sendiri — versi lama tetap diterbitkan dan bilangannya tidak pernah
ditetapkan semula):

[![v2.1.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.1.0/total?label=v2.1.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.1.0)
[![v2.0.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.0.0/total?label=v2.0.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0)
[![v1.9.3](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.3/total?label=v1.9.3&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.3)
[![v1.9.1](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.1/total?label=v1.9.1&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.1)
[![v1.9.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.0/total?label=v1.9.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.0)
[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

## Data yang dihantar keluar dari komputer anda

Dengan tetapan default, audio dan transkrip anda kekal dalam komputer anda.
Aplikasi menggunakan rangkaian untuk:

- memuat turun model atau komponen pilihan kali pertama ia diperlukan;
- tetapan dalam taliannya semasa startup dan semakan kemas kini harian di GitHub, yang
  hanya memberitahu anda tentang versi baharu;
- statistik penggunaan, aktif secara default, dihantar setiap kali transkripsi selesai: model,
  bahasa, durasi, jumlah kata, versi aplikasi, sistem operasi, jenis CPU dan
  kapasiti memori, serta wilayah, namun tidak pernah menyertakan nama fail anda. Matikannya di
  **Help → Usage statistics**.

Audio atau teks transkrip hanya dihantar jika anda memilih enjin awan (Gemini API
atau Google Cloud Speech-to-Text) atau menghubungkan pembekal AI jauh anda sendiri.
**File → Work offline** menghentikan semua ini. Senarai lengkap semua sambungan rangkaian boleh didapati dalam
[../CONFIG.md](../CONFIG.md#network-use).

## Dokumentasi

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

Memerlukan Python 3.11 atau lebih baru. Talian paip binaan: [../BUILD.md](../BUILD.md). Ujian dan pull requests:
[../../CONTRIBUTING.md](../../CONTRIBUTING.md).

## Contributing and contact

- **Laporan pepijat dan permintaan ciri:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Soalan dan idea:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Hal-hal lain:** melalui e-mel, menerusi
  [Contact section of the website](https://whisper-transcriber-suite.com/#contact)
- **Laporan keselamatan:** [../../SECURITY.md](../../SECURITY.md)

Projek ini mengikut [Contributor Covenant](../../.github/CODE_OF_CONDUCT.md).
Jika aplikasi ini menjimatkan masa anda, Star di bahagian atas halaman ini membantu orang lain
mencarinya.

## Bagaimana projek ini dibina

Penyelenggara (maintainer) membangunkan aplikasi ini dengan bantuan meluas daripada pembantu pengekodan AI (terutamanya Claude). Type checks
dan unit tests mesti lulus sebelum setiap commit, dan CI menjalankannya lagi di Windows dan Linux selepas
setiap push. [release checklist](../RELEASE_PROCESS.md) termasuk ujian pemasangan manual di
komputer sebenar. Commit yang dibuat dengan bantuan AI kini mencatatkan nama model pada baris `Assisted-by:`; banyak yang lebih lama
sebaliknya membawa baris `Co-Authored-By: Claude`.

## Lesen

Hak cipta (c) 2026 translation-robot (co-author). Projek ini berada dalam repositori ini,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
Sumber projek itu sendiri berada di bawah [BSD 3-Clause License](../../LICENSE). Pelbagai alat bawaan,
runtime Python dan model mengekalkan lesen mereka masing-masing; lihat
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
