<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**Transkripsi dan subtitle offline gratis untuk rekaman panjang dalam bahasa Anda — di laptop biasa, tanpa akun dan tanpa mengunggah audio.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Unduh untuk Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

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
<b>Bahasa Indonesia</b> ·
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

## Untuk siapa aplikasi ini

Pembuat subtitle, penerjemah, peneliti, dan jurnalis yang mengubah rekaman
panjang (wawancara, kuliah, pembicaraan, video) menjadi teks atau subtitle.
Tarik dan lepas file audio atau video, lalu transkripnya akan dibuat di lokasi yang sama. Sistem pengenalan suara berjalan di komputer Anda sendiri, sehingga
tidak ada biaya per menit dan, setelah model diunduh, koneksi internet tidak
diperlukan.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="Tab Transcribe: area untuk menjatuhkan berkas, pemilih mesin dan bahasa, opsi label pembicara dan stempel waktu per kata" width="80%">
</div>

## Apa yang baru di 2.0

- **Kecepatan dan sisa waktu:** tab Queue menampilkan kecepatan masing-masing tugas dan perkiraan sisa waktu.
- **Video dengan subtitle dari tautan:** unduh, transkripsikan, dan menyatukan (burn in) subtitle dalam satu tugas ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Transkrip sebagai halaman web:** satu file `.html` dengan fitur pencarian dan click-to-play yang berfungsi offline di browser apa pun.
- **Status Work offline yang jelas:** dengan Work offline dihidupkan, baris status menampilkan apakah aplikasi atau proses yang dimulainya memiliki koneksi jaringan.
- **Terjemahkan ke bahasa Inggris:** ucapan dalam bahasa selain bahasa Inggris akan diubah menjadi subtitle bahasa Inggris dalam satu langkah.
- **Quick start:** instalasi baru akan menanyakan tiga pertanyaan, dan sampel klip 18 detik langsung menunjukkan hasilnya.
- **Report a problem** dari Help, tanpa memerlukan akun GitHub.
- **macOS:** menu aplikasi dengan Settings (Command-koma), Light dan Dark yang mengikuti sistem, notifikasi. **Windows:** progres taskbar dan title bar gelap.

Daftar lengkap: [CHANGELOG](../CHANGELOG.md).

## Fitur

- **Mesin lokal:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (default), whisper.cpp, dan NVIDIA Parakeet, untuk berbagai bahasa yang dikenali Whisper. Menggunakan GPU NVIDIA
  melalui CUDA jika bisa, jika tidak, menggunakan CPU.
- **Aplikasi dalam bahasa Anda:** Menu, tombol, dan pesan dalam 42 bahasa
  (diterjemahkan mesin dan ditandai demikian; koreksi sangat diterima). Mengikuti
  bahasa sistem Anda, atau Anda bisa memilih satu di Pengaturan lanjutan. Bahasa
  Persia, Arab, dan Ibrani untuk sementara tersedia di Windows.
- **14 format output:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX, dan
  PDF, ditambah format oTranscribe, ELAN, InqScribe, dan Express Scribe. DOCX
  dan PDF merender setiap aksara, dan bahasa Persia, Arab, serta Urdu dibaca dari kanan ke kiri
  dengan huruf-huruf bersambung.
- **Halaman web yang dapat dibagikan:** simpan transkrip yang selesai sebagai satu file `.html` yang
  berfungsi offline di browser apa pun; klik pada sebuah kata untuk mendengarnya, cari, lompat ke bab.
- **Speaker labels** tanpa akun Hugging Face, ditambah word timestamps dan
  time-range clipping.
- **Tugas terputus dilanjutkan** dari checkpoint terakhirnya daripada memulai
  dari awal (mesin default).
- **Video online:** unduh dari situs mana pun yang didukung [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  dan transkripsikan saat unduhan selesai.
- **Tautan ke video bersubtitle:** satu centang mengubah tautan menjadi `<title>-subbed.mp4`
  dengan subtitle yang menyatu (burn in): unduh, transkripsikan, dan satukan subtitle dalam satu tugas
  ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Live:** transkripsikan mikrofon, atau audio sistem di Windows, secara
  real-time ([../LIVE.md](../LIVE.md)).
- **Batch queue dan watched folder** untuk banyak file.
- **Local-network mode:** halaman transkripsi dan API kompatibel OpenAI untuk
  perangkat lain di jaringan Anda ([../SERVER.md](../SERVER.md)).
- **Opsional, off by default:** Alat AI untuk transkrip yang sudah selesai (ringkasan,
  pertanyaan, SRT dua bahasa), dan text to voice offline dengan fitur kloning suara.

Perbandingan dengan Subtitle Edit, Vibe, Buzz, noScribe, dan aTrain,
termasuk kapan aplikasi lain mungkin lebih baik:
**[../COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Download

Rilis terbaru: **[releases page](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| File | Untuk |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 atau 11, 64-bit. Sebagian besar orang membutuhkan yang ini. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows tanpa instalasi: unzip dan jalankan. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Mac dengan Apple silicon, macOS 14 atau lebih baru. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Intel Mac, macOS 10.15 atau lebih baru. |

Linux dijalankan dari source: [../../platform/linux/README.md](../../platform/linux/README.md).

FFmpeg yang disertakan adalah build GPL. Source yang sesuai dilampirkan pada setiap rilis sebagai
file `WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*`; tautan persisnya ada di
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

ffmpeg dan yt-dlp sudah disertakan. Saat peluncuran pertama, jendela quick start memilih
model ucapan untuk bahasa Anda: Fast (Small, sekitar 500 MB) atau Kualitas terbaik
(hingga sekitar 3 GB); ini diunduh sekali, pada penggunaan pertama. Siapkan 8 GB
RAM; pada CPU model Large membutuhkan waktu sekitar 1,5–2,5 kali lipat durasi
audio, sementara model Small membutuhkan sekitar setengahnya, GPU NVIDIA jauh lebih cepat. Build untuk Windows tidak dilengkapi code-sign dan build untuk Mac tidak
dinotarisasi, jadi SmartScreen dan Gatekeeper memperingatkan pada peluncuran pertama;
[../INSTALL.md](../INSTALL.md) menunjukkan apa yang harus diklik. Untuk memperbarui, jalankan installer
yang lebih baru di atas yang lama; pengaturan dipertahankan.

**Unduhan berdasarkan versi** (setiap lencana hanya menghitung
rilis versi tersebut sendiri — versi lama tetap dipublikasikan dan jumlahnya tidak pernah
di-reset):

[![v2.1.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.1.0/total?label=v2.1.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.1.0)
[![v2.0.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.0.0/total?label=v2.0.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0)
[![v1.9.3](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.3/total?label=v1.9.3&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.3)
[![v1.9.1](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.1/total?label=v1.9.1&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.1)
[![v1.9.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.0/total?label=v1.9.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.0)
[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

## Data apa saja yang keluar dari komputer Anda

Dengan pengaturan default, audio dan transkrip Anda tetap berada di komputer Anda.
Aplikasi menggunakan jaringan untuk:

- mengunduh model atau komponen opsional saat pertama kali dibutuhkan;
- pengaturan onlinenya saat startup dan pemeriksaan pembaruan harian di GitHub, yang
  hanya memberi tahu Anda tentang versi baru;
- statistik penggunaan, aktif secara default, dikirim setiap kali transkripsi selesai: model,
  bahasa, durasi, jumlah kata, versi aplikasi, sistem operasi, jenis CPU dan
  kapasitas memori, serta wilayah, namun tidak pernah menyertakan nama file. Matikan di
  **Help → Usage statistics**.

Audio atau teks transkrip dikirim hanya jika Anda memilih cloud engine (Gemini API
atau Google Cloud Speech-to-Text) atau menghubungkan penyedia AI jarak jauh Anda sendiri.
**File → Work offline** menghentikan semuanya. Daftar lengkap koneksi yang digunakan dapat dilihat di
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

Memerlukan Python 3.11 atau yang lebih baru. Pipeline build: [../BUILD.md](../BUILD.md). Tes dan pull request:
[../../CONTRIBUTING.md](../../CONTRIBUTING.md).

## Contributing and contact

- **Laporan bug dan permintaan fitur:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Pertanyaan dan ide:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Hal lainnya:** melalui email, melalui
  [Contact section of the website](https://whisper-transcriber-suite.com/#contact)
- **Laporan keamanan:** [../../SECURITY.md](../../SECURITY.md)

Proyek ini mengikuti [Contributor Covenant](../../.github/CODE_OF_CONDUCT.md).
Jika aplikasi ini menghemat waktu Anda, sebuah Bintang (Star) di bagian atas halaman ini membantu orang lain
menemukannya.

## Bagaimana proyek ini dibangun

Pengembang utama membangun aplikasi ini dengan bantuan ekstensif dari asisten coding AI (terutama Claude). Type checks
dan unit tests harus lulus sebelum setiap commit, dan CI menjalankannya lagi di Windows dan Linux setelah
setiap push. [release checklist](../RELEASE_PROCESS.md) mencakup tes instalasi manual di
komputer nyata. Commit yang dibuat dengan bantuan AI kini mencantumkan nama model pada baris `Assisted-by:`; banyak yang lebih lama
membawa baris `Co-Authored-By: Claude` sebagai gantinya.

## Lisensi

Hak cipta (c) 2026 translation-robot (co-author). Proyek ini ada di repositori ini,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
Source proyek sendiri berada di bawah [BSD 3-Clause License](../../LICENSE). Berbagai alat bawaan,
runtime Python, dan model yang digunakan memiliki lisensinya masing-masing; lihat
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
