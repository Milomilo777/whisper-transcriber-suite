<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**일반 노트북에서도 계정 가입이나 오디오 업로드 없이 한국어 등 다양한 언어의 긴 녹음을 무료로 오프라인에서 텍스트와 자막으로 변환해주는 도구입니다.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Windows용 다운로드](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS 및 Linux: [다운로드](#download) 섹션을 참조하세요.

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
<b>한국어</b> ·
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

## 대상 사용자

이 도구는 긴 녹음 자료(인터뷰, 강의, 강연, 동영상)를 텍스트나 자막으로 변환해야 하는 자막 제작자, 번역가, 연구원 및 언론인에게 최적화되어 있습니다. 오디오나 동영상 파일을 끌어다 놓기만 하면, 원본 파일 바로 옆에 변환된 텍스트 파일이 생성됩니다. 음성 엔진은 사용자의 컴퓨터에서 직접 실행되므로 분당 사용료가 발생하지 않으며, 모델을 한 번 다운로드한 후에는 인터넷 연결도 필요 없습니다.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="Transcribe 탭: 파일을 끌어다 놓는 영역, 엔진 및 언어 선택, 화자 레이블과 단어 타임스탬프 옵션" width="80%">
</div>

## 버전 2.0의 새로운 기능

- **속도 및 남은 시간:** Queue 탭에 각 작업의 처리 속도와 대략적인 남은 시간이 표시됩니다.
- **링크에서 자막 있는 동영상 만들기:** 다운로드, 트랜스크립션(텍스트 변환), 자막 입히기 과정을 단 하나의 작업으로 처리할 수 있습니다([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **웹 페이지 형태의 트랜스크립트:** 오프라인 상태에서도 모든 브라우저에서 작동하는 검색과 클릭 재생이 가능한 단일 `.html` 파일로 생성됩니다.
- **연결 상태 확인이 가능한 오프라인 모드:** Work offline이 켜져 있을 때 앱이나 앱에서 시작한 프로세스의 네트워크 연결 상태를 상태 줄에 표시합니다.
- **영어로 번역:** 영어 외의 음성을 한 번의 처리만으로 즉시 영어 자막으로 변환합니다.
- **빠른 시작:** 새로 설치 시 3가지 질문을 받고, 18초짜리 샘플 클립으로 결과를 즉시 보여줍니다.
- **문제 신고:** GitHub 계정 없이 Help 메뉴에서 바로 문제를 신고할 수 있습니다.
- **macOS:** Settings(Command+쉼표)가 포함된 앱 메뉴, 시스템 설정에 따르는 라이트/다크 모드, 알림 기능 제공. **Windows:** 작업 표시줄 진행 상태 표시 및 어두운 제목 표시줄.

전체 목록: [CHANGELOG](../CHANGELOG.md).

## 주요 기능

- **로컬 엔진:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (기본값), whisper.cpp, NVIDIA Parakeet이 Whisper가 인식하는 다양한 언어를 지원합니다. 가능하다면 CUDA를 통해 NVIDIA GPU를 사용하고, 그렇지 않으면 CPU를 사용합니다.
- **내 언어로 쓰는 앱:** 메뉴, 버튼, 메시지를 42개 언어로 제공합니다 (기계 번역이며 그렇게 표시되어 있습니다. 수정 제안을 환영합니다).
  시스템 언어를 따르며, 고급 설정에서 직접 선택할 수도 있습니다. 페르시아어, 아랍어, 히브리어는 현재 Windows에서 제공됩니다.
- **14가지 출력 형식:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX, PDF에 더해 oTranscribe, ELAN, InqScribe, Express Scribe 형식을 지원합니다. DOCX와 PDF는 모든 문자를 그려내며, 페르시아어, 아랍어, 우르두어 등 문자가 이어지는 우측에서 좌측으로 쓰는 언어(RTL)도 정확히 처리합니다.
- **공유하기 쉬운 웹 페이지:** 완료된 트랜스크립트를 모든 브라우저에서 오프라인으로 작동하는 단일 `.html` 파일로 저장할 수 있습니다. 단어를 클릭해 소리를 듣고, 검색하고, 각 챕터로 바로 이동할 수 있습니다.
- **화자 라벨링(Speaker labels):** Hugging Face 계정 없이도 단어별 타임스탬프와 시간 범위 자르기 기능을 사용할 수 있습니다.
- **중단된 작업 다시 시작:** 처음부터 다시 시작하는 대신 마지막 체크포인트부터 다시 시작합니다 (기본 엔진).
- **온라인 동영상:** [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  가 지원하는 어떤 사이트에서든 다운로드하고, 다운로드가 끝나면 자동으로 텍스트 변환을 시작합니다.
- **자막 동영상 링크:** 옵션을 체크하기만 하면 링크된 동영상을 자막이 입혀진 `<title>-subbed.mp4` 로 바꿔줍니다. 다운로드, 텍스트 변환, 자막 입히기 등 모든 과정을 큐(queue)에 들어간 단 하나의 작업으로 끝냅니다([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **라이브(Live):** 마이크 소리를 실시간으로 텍스트로 변환하거나, Windows에서는 시스템 오디오를 즉시 변환합니다([../LIVE.md](../LIVE.md)).
- **일괄 처리(Batch) 큐 및 감시 폴더(Watched folder):** 수많은 파일을 한 번에 처리합니다.
- **로컬 네트워크 모드:** 네트워크에 있는 다른 기기를 위한 텍스트 변환 페이지 및 OpenAI 호환 API를 제공합니다([../SERVER.md](../SERVER.md)).
- **선택 사항(기본적으로 꺼짐):** 완료된 트랜스크립트를 위한 AI 도구(요약, 질문, 2개 국어 SRT), 그리고 음성 복제가 포함된 오프라인 TTS(텍스트 음성 변환).

Subtitle Edit, Vibe, Buzz, noScribe, aTrain과의 비교. 다른 앱을 선택하는 것이 더 나을 때를 포함합니다:
**[../COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## 다운로드

최신 릴리스: **[릴리스 페이지](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| 파일 | 대상 |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 또는 11, 64비트. 대부분의 사용자가 필요로 하는 파일입니다. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | 설치 없이 사용하는 Windows 버전: 압축을 풀고 바로 실행. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Apple Silicon이 탑재된 Mac, macOS 14 이상. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Intel Mac, macOS 10.15 이상. |

Linux는 소스에서 실행합니다: [../platform/linux/README.md](../../platform/linux/README.md).

내장된 FFmpeg는 GPL 빌드입니다. 이에 해당하는 소스는 각 릴리스에
`WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*` 파일로 첨부되어 있습니다. 정확한 링크는
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md)에 있습니다.

ffmpeg와 yt-dlp가 앱에 기본 포함되어 있습니다. 앱을 처음 실행하면 퀵 스타트(Quick start) 창이 열리며 사용 언어에 맞는 음성 모델을 선택하게 됩니다: 속도가 빠른 모델(Small, 약 500 MB) 또는 최고의 품질(최대 약 3 GB)을 제공하는 모델 중 고를 수 있습니다. 모델 다운로드는 처음 사용할 때 한 번만 진행됩니다. 8 GB RAM을 준비하시기를 권장합니다. CPU 사용 시, Large 모델은 오디오 길이의 약 1.5배에서 2.5배 시간이 소요되며, Small 모델은 절반 정도 걸립니다. NVIDIA GPU를 사용하면 훨씬 빨라집니다. Windows 빌드는 코드 서명(Code-sign)이 되어 있지 않고, Mac 빌드는 공증(Notarized)을 받지 않았기 때문에 처음 실행 시 SmartScreen과 Gatekeeper가 경고를 표시합니다. [../INSTALL.md](../INSTALL.md)에서 클릭해야 할 항목을 확인하세요. 업데이트 시에는 새 설치 프로그램을 이전 버전 위에 그대로 덮어쓰면 됩니다. 설정은 그대로 유지됩니다.

**버전별 다운로드 횟수** (각 배지는 해당 버전 자체의 릴리스만 집계합니다. 이전 버전은 그대로 공개 유지되며 횟수가 초기화되지 않습니다):

[![v2.1.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.1.0/total?label=v2.1.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.1.0)
[![v2.0.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.0.0/total?label=v2.0.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0)
[![v1.9.3](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.3/total?label=v1.9.3&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.3)
[![v1.9.1](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.1/total?label=v1.9.1&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.1)
[![v1.9.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.0/total?label=v1.9.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.0)
[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

## 내 컴퓨터 밖으로 전송되는 정보

기본 설정을 사용할 경우, 오디오와 트랜스크립트는 전적으로 컴퓨터 내부에 보관됩니다.
앱이 네트워크를 사용하는 경우는 다음과 같습니다:

- 처음 필요할 때 모델 또는 선택적 구성 요소를 다운로드합니다.
- 시작 시 온라인 설정을 가져오고 매일 한 번씩 GitHub에서 업데이트를 확인하지만, 이는 새 버전을 알려주기 위한 용도일 뿐입니다.
- 기본적으로 활성화되어 있는 사용 통계(Usage statistics)는 변환 작업이 완료될 때마다 다음을 전송합니다: 모델, 언어, 오디오 길이, 단어 수, 앱 버전, 운영 체제, CPU 및 메모리 크기, 지역. 파일 이름은 절대로 전송되지 않습니다. **Help → Usage statistics**에서 끌 수 있습니다.

오디오나 트랜스크립트 텍스트는 클라우드 엔진(Gemini API 또는 Google Cloud Speech-to-Text)을 선택하거나 사용자가 직접 원격 AI 제공 업체에 연결했을 때만 전송됩니다.
**File → Work offline**을 선택하면 이 모든 통신이 차단됩니다. 모든 네트워크 연결 목록은
[../CONFIG.md](../CONFIG.md#network-use)에 나와 있습니다.

## 문서

[Install](../INSTALL.md) · [Configuration](../CONFIG.md) ·
[Live transcription](../LIVE.md) · [Local-network mode and API](../SERVER.md) ·
[Cloud engines](../CLOUD_STT.md) · [Architecture](../ARCHITECTURE.md) ·
[Changelog](../CHANGELOG.md) · [All docs](../README.md)

## 소스에서 빌드하기

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Python 3.11 이상이 필요합니다. 빌드 파이프라인: [../BUILD.md](../BUILD.md). 테스트 및 풀 리퀘스트(Pull requests):
[../../CONTRIBUTING.md](../../CONTRIBUTING.md).

## 기여 및 문의

- **버그 및 기능 요청:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **질문 및 아이디어:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **그 외 모든 문의:** 이메일이나
  [웹사이트의 연락처 섹션](https://whisper-transcriber-suite.com/#contact)
- **보안 보고서:** [../../SECURITY.md](../../SECURITY.md)

이 프로젝트는 [Contributor Covenant](../../.github/CODE_OF_CONDUCT.md)를 따릅니다.
이 앱이 유용했다면 이 페이지 상단에 별(Star)을 남겨 다른 사람들이 쉽게 찾을 수 있도록 도와주세요.

## 프로젝트 제작 과정

유지 보수 담당자는 AI 코딩 어시스턴트(주로 Claude)의 큰 도움을 받아 앱을 개발하고 있습니다. 매 커밋마다 타입 검사와 단위 테스트를 통과해야 하며, 푸시(push) 후에는 CI(지속적 통합) 시스템이 Windows 및 Linux에서 이를 다시 실행합니다. [릴리스 체크리스트](../RELEASE_PROCESS.md)에는 실제 기기에서의 수동 설치 테스트가 포함되어 있습니다. 최근 AI의 지원을 받아 작성된 커밋에는 `Assisted-by:` 줄에 해당 모델을 명시하며, 오래된 커밋에는 `Co-Authored-By: Claude`가 적혀 있습니다.

## 라이선스

Copyright (c) 2026 translation-robot (co-author). 프로젝트는 이 저장소에서 확인할 수 있습니다
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
프로젝트의 소스 자체는 [BSD 3-Clause License](../../LICENSE)를 따릅니다. 내장된 도구, Python 런타임, 그리고 모델은 각자의 고유한 라이선스를 따르며 자세한 내용은
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md)를 참조하세요.
