<div align="center">

<img src="../img/hero.png" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**免费、离线的长录音与长视频转写及字幕生成工具，支持你的语言 —— 在普通的笔记本电脑上即可运行，无需账号，也无需上传音频。**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [下载 Windows 版](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS 与 Linux：请参阅 [下载](#download)。

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
<b>简体中文</b> ·
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

## 适用人群

专为需要将长录音（采访、讲座、演讲、视频）转换为文字或字幕的字幕组、翻译人员、研究人员和记者而设计。将音频或视频文件拖入其中，即可在旁边生成转写稿。语音引擎在你的电脑上本地运行，因此没有按分钟计费的开销，一旦模型下载完成，就不再需要网络连接。

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="Transcribe 选项卡：文件拖放区、引擎和语言选择器、说话人标签和逐词时间戳选项" width="80%">
</div>

## 2.0 版本的新功能

- **速度与剩余时间：** 队列标签页显示每个任务的转写速度和大致的剩余时间。
- **通过链接下载带字幕的视频：** 下载、转写并将字幕烧录为一个任务（[../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)）。
- **网页版转写稿：** 生成带有搜索和点击播放功能的单一 `.html` 文件，支持在任何浏览器中离线查看。
- **离线工作状态检查：** 开启 Work offline 时，状态栏会直观显示应用或其后台进程是否正在连接网络。
- **翻译成英文：** 将非英语语音一步转换为英文字幕。
- **快速入门：** 全新安装会询问三个问题，并提供一个 18 秒的样例片段即刻展示结果。
- **报告问题：** 可直接从 Help 菜单报告，无需 GitHub 账号。
- **macOS：** 包含 Settings（Command-逗号）、跟随系统的浅色和深色模式、系统通知的应用菜单。**Windows：** 任务栏进度条和深色标题栏。

完整列表：[CHANGELOG](../CHANGELOG.md)。

## 功能特性

- **本地引擎：** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  （默认）、whisper.cpp 和 NVIDIA Parakeet，支持 Whisper 所识别的众多语言。尽可能通过 CUDA 优先使用 NVIDIA GPU，否则使用 CPU。
- **应用使用您的语言：** 菜单、按钮和消息支持 42 种语言（机器翻译，并已如实标注；欢迎提出修正）。它会跟随系统语言，也可以在高级设置中自行选择。波斯语、阿拉伯语和希伯来语目前在 Windows 上提供。
- **14 种输出格式：** SRT、VTT、ASS、TSV、TXT、JSON、LRC、Markdown、DOCX 和 PDF，以及 oTranscribe、ELAN、InqScribe 与 Express Scribe 格式。DOCX 与 PDF 能渲染任何文字脚本，并能正确处理波斯语、阿拉伯语与乌尔都语的从右至左（RTL）书写连字。
- **便于分享的网页：** 将完成的文字稿保存为单一的 `.html` 文件，支持在任何浏览器中离线查看；点击词语即可播放对应音频，支持全文搜索和章节跳转。
- **说话人标签** 无需 Hugging Face 账号，附带逐词时间戳与时间段裁剪功能。
- **中断的任务可恢复**：从最后的检查点恢复任务，而不是从头开始（默认引擎）。
- **在线视频：** 下载任何 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 支持网站的视频，并在下载完成后自动转写。
- **带字幕的视频链接：** 只需勾选即可将链接转换为内嵌字幕的 `<title>-subbed.mp4` 文件：下载、转写和烧录字幕，整个过程在队列中作为一个任务完成（[../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)）。
- **实时：** 转写麦克风输入，或在 Windows 上实时转写系统音频（[../LIVE.md](../LIVE.md)）。
- **批量队列和监控文件夹** 适合处理大量文件。
- **局域网模式：** 为网络中的其他设备提供转写页面和兼容 OpenAI 格式的 API（[../SERVER.md](../SERVER.md)）。
- **可选（默认关闭）：** 针对已完成转写的 AI 工具（总结、问答、双语 SRT），及附带声音克隆的离线文本转语音功能。

它与 Subtitle Edit、Vibe、Buzz、noScribe 及 aTrain 的对比，包括在哪些情况下其他应用可能会是更好的选择：
**[../COMPARISON.md](../COMPARISON.md)**。

<a id="download"></a>

## 下载

最新版本：**[发布页](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**。

| 文件 | 适合 |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 或 11，64 位。大多数人需要这个。 |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | 免安装版 Windows：解压即用。 |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | 搭载 Apple 芯片的 Mac，macOS 14 或更新系统。 |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | 搭载 Intel 处理器的 Mac，macOS 10.15 或更新系统。 |

Linux 从源码运行：[../platform/linux/README.md](../../platform/linux/README.md)。

内置的 FFmpeg 是在 GPL 下构建的。对应的源代码附加在各个版本的发行说明中，文件名如
`WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*`；确切的链接在
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) 中。

ffmpeg 与 yt-dlp 已内置。首次启动时，一个快速入门窗口会为你的语言选择语音模型：速度快（Small 规模，大约 500 MB）或质量最佳（最高约 3 GB）；模型在首次使用时只需下载一次。建议准备 8 GB 内存；在 CPU 上，Large 模型的耗时约为音频长度的 1.5 到 2.5 倍，Small 模型约是一半时间，配备 NVIDIA GPU 速度将大幅提升。Windows 版本没有经过代码签名，Mac 版本也未经公证验证，因此 SmartScreen 和 Gatekeeper 会在第一次启动时弹出警告；
[../INSTALL.md](../INSTALL.md) 说明了点击哪些选项。如需更新，请直接用新版安装程序覆盖旧版本；设置将会保留。

**各版本下载量**（每个徽章仅计算该特定版本自身的发布数 —— 旧版本始终保留且计数永不清零）：

[![v2.1.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.1.0/total?label=v2.1.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.1.0)
[![v2.0.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.0.0/total?label=v2.0.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0)
[![v1.9.3](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.3/total?label=v1.9.3&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.3)
[![v1.9.1](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.1/total?label=v1.9.1&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.1)
[![v1.9.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.0/total?label=v1.9.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.0)
[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

## 有什么信息会离开你的电脑

在默认设置下，你的音频和文字稿都会保留在你的电脑上。
应用只会在以下情况连接网络：

- 首次需要时下载某个模型或可选组件；
- 启动时读取在线设置，并每天向 GitHub 检查一次更新，它只是提醒你新版本的到来；
- 开启默认的使用统计功能后，在每次转写完成时发送：模型名称、语言、时长信息、字数统计、应用版本、操作系统类型、CPU及内存信息、以及所在区域，不会发送文件名称。你可以在 **Help → Usage statistics** 下关闭它。

唯有在你选择了云端引擎（Gemini API 或 Google Cloud Speech-to-Text）或是自主连接到远程 AI 供应商时，才会发送音频或转写文本。
**File → Work offline** 可切断全部网络连接。每一个连接都在
[../CONFIG.md](../CONFIG.md#network-use) 中详细列出。

## 文档

[Install](../INSTALL.md) · [Configuration](../CONFIG.md) ·
[Live transcription](../LIVE.md) · [Local-network mode and API](../SERVER.md) ·
[Cloud engines](../CLOUD_STT.md) · [Architecture](../ARCHITECTURE.md) ·
[Changelog](../CHANGELOG.md) · [All docs](../README.md)

## 从源码构建

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

需要 Python 3.11 或更新版本。构建流程：[../BUILD.md](../BUILD.md)。测试及拉取请求：
[../../CONTRIBUTING.md](../../CONTRIBUTING.md)。

## 参与贡献与联系

- **程序错误与功能建议：** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **疑问与想法讨论：** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **其他一切事宜：** 请发邮件或通过
  [网站上的联系区](https://whisper-transcriber-suite.pages.dev/#contact) 联络。
- **安全问题报告：** [../../SECURITY.md](../../SECURITY.md)

本项目遵守 [Contributor Covenant（贡献者公约）](../../.github/CODE_OF_CONDUCT.md)。
如果这款应用为您节省了时间，在页面顶端点亮一颗星星（Star）能帮助其他有需要的人找到它。

## 本项目是如何构建的

维护者在人工智能编程助手（主要是 Claude）的大力协助下进行开发。类型检查和单元测试必须在每次提交前通过，并且 CI 系统会在每次推送后在 Windows 和 Linux 上再次运行它们。[发布检查清单](../RELEASE_PROCESS.md)包含在真实设备上进行的手工安装测试。带有 AI 辅助的新近提交会在 `Assisted-by:` 标注上指明了使用的模型；许多早期提交则带有 `Co-Authored-By: Claude` 字样。

## 许可证

版权所有 (c) 2026 translation-robot (共同作者)。项目代码库为
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite)。
本项目源码遵循 [BSD 3-Clause 许可证](../../LICENSE)。内置工具、Python 运行时以及各个模型保留各自的原许可证；详见
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md)。
