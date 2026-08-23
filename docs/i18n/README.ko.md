<div align="center">

<img src="../img/hero.png" alt="Whisper Project" width="100%">

# Whisper Project

### 오디오나 영상 파일을 끌어다 놓으세요. **시간 정보가 붙은 정돈된 자막·전사본**이 나옵니다 — 파일은 컴퓨터를 벗어나지 않습니다.

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![downloads](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/total?color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases)
[![License: BSD-3](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)
[![Stars](https://img.shields.io/github/stars/Milomilo777/whisper-transcriber-suite?style=flat&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/stargazers)

### [⬇  Windows용 다운로드](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

<p>
  <a href="../../README.md"><img src="https://flagcdn.com/16x12/us.png" alt="" width="16" height="12"> English</a> ∙
  <a href="README.zh-CN.md"><img src="https://flagcdn.com/16x12/cn.png" alt="" width="16" height="12"> 简体中文</a> ∙
  <a href="README.ja.md"><img src="https://flagcdn.com/16x12/jp.png" alt="" width="16" height="12"> 日本語</a> ∙
  <img src="https://flagcdn.com/16x12/kr.png" alt="" width="16" height="12">
  <b>한국어</b> ∙
  <a href="README.de.md"><img src="https://flagcdn.com/16x12/de.png" alt="" width="16" height="12"> Deutsch</a> ∙
  <a href="README.es.md"><img src="https://flagcdn.com/16x12/es.png" alt="" width="16" height="12"> Español</a> ∙
  <a href="README.fr.md"><img src="https://flagcdn.com/16x12/fr.png" alt="" width="16" height="12"> Français</a> ∙
  <a href="README.pt.md"><img src="https://flagcdn.com/16x12/pt.png" alt="" width="16" height="12"> Português</a> ∙
  <a href="README.fa.md"><img src="https://flagcdn.com/16x12/ir.png" alt="" width="16" height="12"> فارسی</a>
</p>

</div>

---

OpenAI Whisper 모델을 **로컬에서** 실행하는 데스크톱 앱입니다([faster-whisper](https://github.com/SYSTRAN/faster-whisper) 기반). 분 단위 과금이 없고, 비행기 안에서도 동작하며, 녹음이 어디로도 업로드되지 않습니다. 파일을 끌어다 놓으면 원본 옆에 `.srt`, `.vtt`, `.txt`, `.json`, `.docx`, `.pdf` 등을 만들어 줍니다. `yt-dlp`가 지원하는 모든 사이트에서 내려받고, 화자를 구분하고, 여러 작업을 큐로 처리하며, 같은 네트워크의 다른 기기를 위한 전사 페이지가 될 수도 있습니다.

계정 불필요. API 키 불필요. 구독 불필요. 파일은 내 디스크에 그대로 남습니다.

- 🔒 **내 컴퓨터에서 실행** —— 기본은 faster-whisper(CTranslate2), 그 외 whisper.cpp와 NVIDIA Parakeet
- 📝 **14가지 출력 형식** —— `srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf`, 그리고 oTranscribe / ELAN / InqScribe / Express Scribe
- 🎙️ **실시간 전사** —— 마이크나 시스템 소리를 말하는 즉시 → [LIVE.md](../LIVE.md)
- 🗣️ **화자 구분** —— 오프라인 화자 분리, 단어 단위 타임스탬프, 구간 자르기
- 🎬 **다운로드** —— `yt-dlp`가 지원하는 모든 사이트, 완료 후 자동 전사 선택 가능
- 🧹 **적응형 노이즈 제거** —— 먼저 측정하고, 도움이 될 때만 처리 → [DENOISE.md](../DENOISE.md)
- 🌐 **로컬 네트워크 모드** —— 이 컴퓨터를 다른 기기용 전사 페이지로
- 💸 **무료, BSD-3 라이선스** —— 분당 요금 없음, 구독 없음, 기본값으로 원격 수집 없음

## 다운로드

최신 빌드는 **[릴리스 페이지](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)** 에서 받으세요:

| 파일 | 크기 | 추천 대상 |
|---|---|---|
| **`WhisperProject-…-Setup-Standard.exe`** | ~215 MB | **대부분의 사용자.** 일반 설치 프로그램: 시작 메뉴 바로 가기, 기존 버전 위에 덮어쓰기 업그레이드, 디스크에서 파일 확인 가능. |
| **`WhisperProject-…-Portable.zip`** | ~330 MB | 압축을 풀고 실행만 하면 됩니다. 설치 불필요, 관리자 권한 불필요, USB에 넣어 다닐 수 있습니다. |
| **`WhisperProject-…-macOS-*.dmg`** | ~400 MB | macOS (x64와 arm64는 각각 배포). |

필요한 것은 모두 들어 있습니다 —— 내장 Python, `ffmpeg`, `ffprobe`, `yt-dlp`. 나중에 받는 것은 음성 모델뿐입니다(**약 1~3 GB, 첫 실행 시 한 번**). 그 이후로는 완전히 오프라인으로 동작합니다.

## 기능

<div align="center">

<img src="../img/features.png" alt="" width="100%">

</div>

| | |
|---|---|
| **로컬 전사** | 기본값은 Whisper `large-v3`, 그 외 `large-v3-turbo`와 `distil-large-v3.5`. |
| **다양한 출력 형식** | `srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf` —— 입력 파일 옆에 저장됩니다. |
| **실시간 전사** | 마이크 또는 이 컴퓨터가 재생 중인 소리를 실시간으로 전사합니다. 자연스러운 쉼에서 끊기 때문에 단어가 반으로 잘리지 않습니다. |
| **화자 분리** | 선택적 '화자 식별' 기능과 단어 단위 타임스탬프, 구간 자르기. |
| **적응형 노이즈 제거** | 녹음을 먼저 측정해 도움이 될 때만 처리하고, 결과를 다시 검사해 음성을 깎아냈다면 원본으로 되돌립니다. |
| **일괄 큐** | 대기·실행 중인 모든 작업의 상태를 실시간 표시. **일시정지 / 재개 / 취소 / 다시 실행 / 제거** 가 항상 한 번의 클릭. |
| **다운로드** | `yt-dlp`가 처리하는 모든 것과 Supreme Master TV 에피소드 링크. 중단되면 처음부터가 아니라 이어받습니다. |
| **로컬 네트워크 모드** | 표준 라이브러리만으로 만든 웹 서버로 다른 기기가 이 컴퓨터를 통해 전사할 수 있습니다 —— 비밀번호 설정 가능, 시작하기 전에는 꺼져 있습니다. |

## 작동 방식

<div align="center">

<img src="../img/how-it-works.png" alt="" width="100%">

</div>

Tk GUI는 메인 프로세스에서 돌아갑니다. 각 전사 작업은 Whisper 모델을 메모리에 계속 올려 둔 장기 실행 워커 서브프로세스에서 실행되며, stdin/stdout의 줄 단위 JSON으로 통신합니다. `yt-dlp`는 다운로드마다 별도의 서브프로세스를 사용합니다. 워커별 UUID 토큰과 5초 하트비트 덕분에 PID가 재사용되어도 신호가 뒤섞이지 않고, GUI가 멈춘 워커를 감지할 수 있습니다.

## 기본은 오프라인

모든 기본 백엔드는 내 컴퓨터에서 동작합니다. 아무것도 업로드되지 않고, 계정도 없으며, 모델을 한 번 내려받은 뒤에는 네트워크를 뽑아도 동작합니다.

> [!IMPORTANT]
> **직접 선택해야만** 켜지는 두 백엔드는 이 보장에서 예외입니다. **Advanced → Backend** 에서 고르지 않는 한 꺼져 있습니다. 제3자에게 보내도 괜찮은 내용에만 사용하세요.
>
> - **`cloud_stt`** — Google Gemini API → [CLOUD_STT.md](../CLOUD_STT.md)
> - **`google_cloud_stt`** — Google Cloud Speech-to-Text → [CLOUD_STT_GOOGLE.md](../CLOUD_STT_GOOGLE.md)

## 소스에서 빌드

```bash
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

## 문서

| 문서 | 내용 |
|---|---|
| [INSTALL.md](../INSTALL.md) | 설치 및 문제 해결 |
| [LIVE.md](../LIVE.md) | Live 탭 |
| [DENOISE.md](../DENOISE.md) | 적응형 노이즈 제거 |
| [SERVER.md](../SERVER.md) | 로컬 네트워크 / 웹 서버 모드 |
| [CONFIG.md](../CONFIG.md) | 모든 설정 키 |
| [BUILD.md](../BUILD.md) | 직접 빌드하기 |
| [CHANGELOG.md](../CHANGELOG.md) | 버전 기록 |

> 전체 문서는 영어로 되어 있습니다. 이 페이지는 요약이며, 자세한 내용은 영어 문서를 참고하세요.

## 라이선스

이 프로젝트의 소스는 **BSD 3-Clause 라이선스** 입니다 —— [LICENSE](../../LICENSE) 참고. 함께 배포되는 바이너리(`ffmpeg`, `ffprobe`, `yt-dlp`), 내장 Python 런타임과 패키지, 그리고 Whisper 모델 자체는 각자의 원래 라이선스를 따릅니다. [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) 에 정리되어 있습니다.

---

<div align="center">
<sub>오프라인 음성 인식 · 로컬 Whisper GUI · 자막 생성 · 화자 분리 · Windows · macOS</sub>
</div>
