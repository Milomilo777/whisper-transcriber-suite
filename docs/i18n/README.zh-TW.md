<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**為您的長篇錄音提供免費、離線的逐字稿與字幕功能 — 支援您的語言，並在一般的筆記型電腦上運行，無需建立帳號或上傳音訊。**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![downloads](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/total?label=downloads&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [下載 Windows 版本](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS 與 Linux：請參見 [Download](#download)。

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
<b>繁體中文</b> ·
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

## 適用對象

為需要將長篇錄音（訪談、課程、演講、影片）轉換為文字或字幕的字幕譯者、翻譯人員、研究員及新聞工作者設計。
只需拖放音訊或影片檔案，即可在旁邊生成文字稿。語音引擎完全在您的電腦上運行，因此沒有每分鐘的計費，而且模型下載完成後，完全不需要網路連線。

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="Transcribe 分頁：檔案拖放區、引擎與語言選擇器、說話者標籤與逐字時間戳記選項" width="80%">
</div>

## 2.0 版本的新功能

- **速度與剩餘時間：** Queue 標籤頁會顯示每個任務的處理速度與大約剩餘時間。
- **透過連結生成含字幕的影片：** 下載、轉錄並將字幕燒錄到影片中，一次搞定（[../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)）。
- **網頁版逐字稿：** 產生單一 `.html` 檔案，具備搜尋與點擊播放功能，可在任何瀏覽器中離線使用。
- **可檢查的離線工作模式：** 開啟 Work offline 後，狀態列會顯示應用程式或其啟動的處理程序是否連接了網路。
- **翻譯為英文：** 一次處理即可將非英語的語音轉換為英文字幕。
- **快速入門：** 全新安裝時會詢問三個問題，並透過一段 18 秒的範例短片立即展示結果。
- **回報問題：** 可直接從 Help 選單中回報問題，無需 GitHub 帳號。
- **macOS：** 應用程式選單中加入 Settings（Command-comma），自動跟隨系統的深淺色主題，並支援通知。**Windows：** 工作列進度顯示與深色標題列。

完整清單請見：[CHANGELOG](../CHANGELOG.md)。

## 功能特色

- **本機引擎：** 支援 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  （預設）、whisper.cpp 和 NVIDIA Parakeet，可用於 Whisper
  能夠辨識的多種語言。若設備許可，將透過 CUDA 使用 NVIDIA GPU 加速，否則將使用 CPU。
- **應用程式使用您的語言：** 選單、按鈕和訊息支援 42 種語言（機器翻譯，並已如實標示；歡迎提出修正）。它會跟隨系統語言，也可以在進階設定中自行選擇。波斯語、阿拉伯語和希伯來語目前在 Windows 上提供。
- **14 種輸出格式：** SRT、VTT、ASS、TSV、TXT、JSON、LRC、Markdown、DOCX 與
  PDF，以及 oTranscribe、ELAN、InqScribe 和 Express Scribe 格式。DOCX
  和 PDF 支援各種文字腳本，並支援波斯文、阿拉伯文和烏爾都文由右至左的連字顯示。
- **可分享的網頁：** 將完成的逐字稿儲存為單一 `.html` 檔案，
  可在任何瀏覽器中離線運作；點擊單字即可播放對應的聲音，支援搜尋並能跳轉至各章節。
- **講者標籤**：無需 Hugging Face 帳號，並提供單字時間戳記和選定時間範圍的擷取功能。
- **中斷任務接續執行**：從上一個檢查點繼續，無需重新開始
  （適用於預設引擎）。
- **線上影片：** 從任何 [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  支援的網站下載影片，並在下載完成後自動轉錄。
- **連結轉含字幕的影片：** 勾選一次，即可將連結轉換為燒錄好字幕的 `<title>-subbed.mp4` 檔案：將下載、轉錄與字幕燒錄整合為單一排程任務
  （[../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)）。
- **即時轉錄：** 即時將麥克風，或在 Windows 上將系統音訊，轉換為文字
  （[../LIVE.md](../LIVE.md)）。
- **批次排程與監控資料夾**：方便處理大量檔案。
- **區域網路模式：** 為您網域內的其他裝置提供轉錄網頁及相容於 OpenAI 的 API
  （[../SERVER.md](../SERVER.md)）。
- **可選用的 AI 工具（預設關閉）：** 為完成的文字稿提供摘要、
  問答與雙語 SRT 服務，並提供支援聲音複製的離線文字轉語音功能。

了解本應用與 Subtitle Edit、Vibe、Buzz、noScribe 和 aTrain 的比較，
以及何時選擇其他應用程式會更合適：
**[../COMPARISON.md](../COMPARISON.md)**。

<a id="download"></a>

## 下載

最新版本：**[releases 頁面](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**。

| 檔案 | 適用對象 |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 或 11，64 位元。多數使用者適用此版本。 |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows 免安裝版：解壓縮後即可執行。 |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | 搭載 Apple 晶片的 Mac，macOS 14 或更新版本。 |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | 搭載 Intel 處理器的 Mac，macOS 10.15 或更新版本。 |

Linux 版本需從原始碼執行：[../../platform/linux/README.md](../../platform/linux/README.md)。

內建的 FFmpeg 為 GPL 版本。其對應的原始碼會以 `WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*` 的形式附在每次發佈版本中；詳細連結請見
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md)。

已內建 ffmpeg 和 yt-dlp。首次啟動時，快速入門視窗會讓您選擇語言對應的語音模型：Fast（Small，約 500 MB）或 Best
quality（最大約 3 GB）；模型僅需在首次使用時下載一次。建議準備 8 GB
的 RAM；在 CPU 上運行 Large 模型所需的時間大約是音訊長度的 1.5 到 2.5 倍，而 Small 模型則只需一半的時間，使用 NVIDIA GPU 則會快得多。Windows 執行檔沒有程式碼簽章，Mac 執行檔也沒有公證，因此 SmartScreen 和 Gatekeeper 在首次啟動時可能會發出警告；
[../INSTALL.md](../INSTALL.md) 會教您如何點擊略過。更新時，只需執行較新的安裝程式覆蓋舊版即可，設定將會被保留。

**各版本下載次數**（每個徽章僅計算該版本的下載次數 — 舊版本仍會保留發佈，其計算亦不會被重置）：

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

## 資料會送到哪裡

在預設設定下，您的音訊和轉錄文字都會留在您的電腦上。
本應用程式只會在以下情況使用網路：

- 首次需要時下載模型或選用元件；
- 啟動時讀取線上設定，並每天向 GitHub 確認一次是否有新版本，
  此動作只會通知您新版本資訊；
- 使用統計數據（預設開啟）：在每次轉錄完成後發送使用統計數據，包含：使用的模型、
  語言、時長、字數、應用程式版本、作業系統、CPU 與記憶體大小，
  以及所在地區，絕對不會傳送檔案名稱。您可以前往
  **Help → Usage statistics** 關閉此功能。

只有當您選擇雲端引擎（Gemini API 或 Google Cloud Speech-to-Text）或是自行連接遠端 AI 供應商時，音訊或轉錄文字才會被傳送出去。
**File → Work offline** 可以停止所有的網路連線。所有的連線細節皆列於
[../CONFIG.md](../CONFIG.md#network-use)。

## 說明文件 (Documentation)

[安裝說明](../INSTALL.md) · [設定與配置](../CONFIG.md) ·
[即時轉錄](../LIVE.md) · [區域網路模式與 API](../SERVER.md) ·
[雲端引擎](../CLOUD_STT.md) · [系統架構](../ARCHITECTURE.md) ·
[更新日誌](../CHANGELOG.md) · [所有文件](../README.md)

## 從原始碼編譯 (Build from source)

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

需要 Python 3.11 或更新版本。建置流程：[../BUILD.md](../BUILD.md)。測試與發送拉取請求 (pull requests)：
[../../CONTRIBUTING.md](../../CONTRIBUTING.md)。

## 貢獻與聯絡方式

- **錯誤回報與功能請求：** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **問題與想法討論：** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **其他所有事宜：** 請透過電子郵件，或網站的
  [聯絡區塊 (Contact section)](https://whisper-transcriber-suite.com/#contact) 聯繫
- **安全性通報：** [../../SECURITY.md](../../SECURITY.md)

本專案遵循 [貢獻者公約 (Contributor Covenant)](../../.github/CODE_OF_CONDUCT.md)。
如果這款應用程式節省了您的時間，在頁面頂端給予一顆星星 (Star) 將能幫助其他人更容易發現它。

## 本專案的開發方式

維護者在 AI 程式碼助手（主要是 Claude）的深度協助下開發此專案。每次提交 (commit) 前都必須通過型別檢查與單元測試，而且每次推送 (push) 後，CI 也會在 Windows 和 Linux 上再次執行測試。[發佈檢查清單](../RELEASE_PROCESS.md) 包含了在真實機器上的手動安裝測試。在 AI 協助下進行的提交現在會在 `Assisted-by:` 這一行中標明模型名稱；許多早期的提交則帶有 `Co-Authored-By: Claude` 標記。

## 授權條款 (License)

Copyright (c) 2026 translation-robot (co-author). 本專案託管於 GitHub，
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite)。
專案本身的原始碼採用 [BSD 3-Clause License](../../LICENSE) 授權。內建
工具、Python 執行環境及模型皆保留其各自的授權條款；詳見
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md)。
