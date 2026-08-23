"""Generate the translated READMEs under ``docs/i18n/``.

Seven hand-maintained translations drift: a link gets fixed in one file
and not the other six, the language switcher loses an entry, a relative
path is right at the repo root and broken one directory down. So the
layout, every link and the switcher live here once, and only the prose
is per-language.

Run after changing the English README::

    python tools/make_i18n_readmes.py

Relative paths matter: these files live in ``docs/i18n/``, so repo-root
files are ``../../``, other docs are ``../`` and images are ``../img/``.
Getting that wrong is the single easiest way to ship a README full of
404s, which is why it is computed here rather than typed eight times.
"""
from __future__ import annotations

import io
import os
import sys

REPO = "https://github.com/Milomilo777/whisper-transcriber-suite"

# Flag images, not flag emoji: Windows renders regional-indicator pairs
# as letters ("KR") instead of a flag, which is a large share of readers.
LANGS: list[tuple[str, str, str]] = [
    # (code, flag country code, native name)
    ("en", "us", "English"),
    ("zh-CN", "cn", "简体中文"),
    ("ja", "jp", "日本語"),
    ("ko", "kr", "한국어"),
    ("de", "de", "Deutsch"),
    ("es", "es", "Español"),
    ("fr", "fr", "Français"),
    ("pt", "pt", "Português"),
]


def switcher(current: str) -> str:
    """The language row, with ``current`` shown as plain bold text."""
    parts: list[str] = []
    for code, flag, name in LANGS:
        img = (f'<img src="https://flagcdn.com/16x12/{flag}.png" '
               f'alt="" width="16" height="12">')
        if code == current:
            parts.append(f"  {img}\n  <b>{name}</b>")
        else:
            href = "../../README.md" if code == "en" else f"README.{code}.md"
            parts.append(f'  <a href="{href}">{img} {name}</a>')
    return "<p>\n" + " ∙\n".join(parts) + "\n</p>"


BADGES = f"""[![CI]({REPO}/actions/workflows/ci.yml/badge.svg)]({REPO}/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)]({REPO}/releases/latest)
[![downloads](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/total?color=207a80)]({REPO}/releases)
[![License: BSD-3](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)
[![Stars](https://img.shields.io/github/stars/Milomilo777/whisper-transcriber-suite?style=flat&color=207a80)]({REPO}/stargazers)"""


TEMPLATE = """<div align="center">

<img src="../img/hero.png" alt="Whisper Project" width="100%">

# Whisper Project

### {tagline}

{badges}

### [⬇  {download_btn}]({repo}/releases/latest)

{switcher}

</div>

---

{intro}

{bullets}

## {h_download}

{download_intro}

| {th_asset} | {th_size} | {th_best} |
|---|---|---|
| **`WhisperProject-…-Setup-Standard.exe`** | ~215 MB | {asset_standard} |
| **`WhisperProject-…-Portable.zip`** | ~330 MB | {asset_portable} |
| **`WhisperProject-…-macOS-*.dmg`** | ~400 MB | {asset_macos} |

{download_note}

## {h_features}

<div align="center">

<img src="../img/features.png" alt="" width="100%">

</div>

| | |
|---|---|
| **{f_local}** | {f_local_d} |
| **{f_formats}** | {f_formats_d} |
| **{f_live}** | {f_live_d} |
| **{f_speakers}** | {f_speakers_d} |
| **{f_denoise}** | {f_denoise_d} |
| **{f_queue}** | {f_queue_d} |
| **{f_download}** | {f_download_d} |
| **{f_lan}** | {f_lan_d} |

## {h_how}

<div align="center">

<img src="../img/how-it-works.png" alt="" width="100%">

</div>

{how_body}

## {h_offline}

{offline_body}

> [!IMPORTANT]
> {offline_warning}
>
> - **`cloud_stt`** — Google Gemini API → [CLOUD_STT.md](../CLOUD_STT.md)
> - **`google_cloud_stt`** — Google Cloud Speech-to-Text → [CLOUD_STT_GOOGLE.md](../CLOUD_STT_GOOGLE.md)

## {h_build}

```bash
git clone {repo}.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

## {h_docs}

| {th_doc} | {th_about} |
|---|---|
| [INSTALL.md](../INSTALL.md) | {d_install} |
| [LIVE.md](../LIVE.md) | {d_live} |
| [DENOISE.md](../DENOISE.md) | {d_denoise} |
| [SERVER.md](../SERVER.md) | {d_server} |
| [CONFIG.md](../CONFIG.md) | {d_config} |
| [BUILD.md](../BUILD.md) | {d_build} |
| [CHANGELOG.md](../CHANGELOG.md) | {d_changelog} |

> {docs_note}

## {h_license}

{license_body}

---

<div align="center">
<sub>{footer}</sub>
</div>
"""


T: dict[str, dict[str, str]] = {}

T["zh-CN"] = dict(
    tagline="拖入音频或视频文件，得到**带时间轴、已排版的文字稿** —— 文件全程不离开你的电脑。",
    download_btn="下载 Windows 版",
    intro=(
        "一款在**本地**运行 OpenAI Whisper 模型的桌面应用（基于 "
        "[faster-whisper](https://github.com/SYSTRAN/faster-whisper)）。转写不按分钟计费，"
        "断网也能用，录音永远不会被上传给任何人。把文件拖进来，它会在原文件旁边写出 "
        "`.srt`、`.vtt`、`.txt`、`.json`、`.docx`、`.pdf` 等格式。"
        "它还能从 `yt-dlp` 支持的任意网站下载视频、区分说话人、批量处理队列，"
        "并可变成局域网内其他设备的转写页面。\n\n"
        "无需账号，无需 API 密钥，无需订阅。文件始终留在你的磁盘上。"
    ),
    bullets=(
        "- 🔒 **在本机运行** —— 默认 faster-whisper（CTranslate2），另有 whisper.cpp 与 NVIDIA Parakeet\n"
        "- 📝 **14 种输出格式** —— `srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf`，以及 oTranscribe / ELAN / InqScribe / Express Scribe\n"
        "- 🎙️ **实时转写** —— 麦克风或系统声音，边说边出字 → [LIVE.md](../LIVE.md)\n"
        "- 🗣️ **说话人标注** —— 离线声纹分离、逐词时间戳、时间段裁剪\n"
        "- 🎬 **视频下载** —— 支持 `yt-dlp` 的所有站点，可下载完成后自动转写\n"
        "- 🧹 **自适应降噪** —— 先测量音频，只在确有帮助时才处理 → [DENOISE.md](../DENOISE.md)\n"
        "- 🌐 **局域网模式** —— 让这台机器成为其他设备的转写服务页\n"
        "- 💸 **免费、BSD-3 许可** —— 无按分钟收费、无订阅、默认不发送任何遥测数据"
    ),
    h_download="下载", h_features="功能", h_how="工作原理",
    h_offline="默认离线", h_build="从源码构建", h_docs="文档", h_license="许可证",
    download_intro="从 **[发布页]({repo}/releases/latest)** 获取最新版本：",
    th_asset="文件", th_size="大小", th_best="适合",
    asset_standard="**大多数人。** 常规安装程序：开始菜单快捷方式、可覆盖旧版本升级、文件在磁盘上可见。",
    asset_portable="解压即用。无需安装、无需管理员权限，可放在 U 盘里。",
    asset_macos="macOS（x64 与 arm64 分别发布）。",
    download_note=(
        "运行所需的一切都已内置 —— 内置 Python、`ffmpeg`、`ffprobe` 和 `yt-dlp`。"
        "唯一需要后续下载的是语音模型本身（**约 1–3 GB，仅首次启动时一次**）；"
        "此后应用完全离线运行。"
    ),
    f_local="本地转写", f_local_d="默认 Whisper `large-v3`，另有 `large-v3-turbo` 与 `distil-large-v3.5`。",
    f_formats="多种输出格式", f_formats_d="`srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf` —— 直接写在源文件旁边。",
    f_live="实时转写", f_live_d="转写麦克风或本机正在播放的声音。切分点落在自然停顿处，不会把词切成两半。",
    f_speakers="说话人分离", f_speakers_d="可选的「识别说话人」，另有逐词时间戳与时间段裁剪。",
    f_denoise="自适应降噪", f_denoise_d="先测量每段录音，只在测量结果表明有效时才降噪；并会复核自身输出，若削掉了语音则自动还原。",
    f_queue="批量队列", f_queue_d="每个任务都有实时状态，**暂停 / 继续 / 取消 / 重跑 / 移除** 随时一键可用。",
    f_download="视频下载", f_download_d="`yt-dlp` 支持的一切，另加 Supreme Master TV 剧集链接。下载可续传而非重来。",
    f_lan="局域网模式", f_lan_d="仅用标准库实现的网页服务，让其他设备通过这台机器转写 —— 可设访问密码，未启动前不开放。",
    how_body=(
        "Tk 图形界面运行在主进程。每个转写任务运行在长期存活的子进程中，"
        "该子进程把 Whisper 模型常驻内存，并通过 stdin/stdout 上的换行分隔 JSON 与主进程通信；"
        "`yt-dlp` 每次下载各用一个子进程。每个子进程的 UUID 令牌加上 5 秒心跳，"
        "使得进程号被系统回收也不会串线，并能让界面发现卡死的子进程而不是跟着一起卡住。"
    ),
    offline_body=(
        "所有默认后端都在你的机器上运行。没有任何内容被上传，不存在账号；"
        "模型下载完成后，拔掉网线也能正常使用。"
    ),
    offline_warning=(
        "有两个**需要主动选择**的后端会打破这一保证，除非你进入 "
        "**Advanced → Backend** 手动选中，否则它们不会启用。"
        "只在你愿意把内容发送给第三方时才使用它们。"
    ),
    th_doc="文档", th_about="内容",
    d_install="安装与故障排查", d_live="实时转写标签页", d_denoise="自适应降噪",
    d_server="局域网 / 网页服务模式", d_config="全部配置项", d_build="自行构建",
    d_changelog="版本历史",
    docs_note="完整文档为英文。本页面是概览；细节请参阅英文文档。",
    license_body=(
        "本项目源码采用 **BSD 3-Clause 许可证** —— 见 [LICENSE](../../LICENSE)。"
        "内置的二进制程序（`ffmpeg`、`ffprobe`、`yt-dlp`）、内置的 Python 运行时与依赖包，"
        "以及 Whisper 模型本身各自保留其上游许可证；"
        "[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) 汇总了这些内容。"
    ),
    footer="离线语音转文字 · 本地 Whisper 图形界面 · 字幕生成 · 说话人分离 · Windows · macOS",
)

T["ja"] = dict(
    tagline="音声・動画ファイルをドロップするだけ。**タイムコード付きの整形済み文字起こし**が、ファイルを外に出さずに手に入ります。",
    download_btn="Windows 版をダウンロード",
    intro=(
        "OpenAI の Whisper モデルを**ローカルで**動かすデスクトップアプリです"
        "（[faster-whisper](https://github.com/SYSTRAN/faster-whisper) を使用）。"
        "分単位の課金がなく、機内でも動作し、録音が誰かにアップロードされることはありません。"
        "ファイルをドロップすると、元ファイルの隣に `.srt`、`.vtt`、`.txt`、`.json`、"
        "`.docx`、`.pdf` などを書き出します。`yt-dlp` が対応するサイトからのダウンロード、"
        "話者の識別、ジョブのバッチ処理、そして同じネットワーク上の他の端末向けの"
        "文字起こしページ化にも対応しています。\n\n"
        "アカウント不要。API キー不要。サブスクリプション不要。ファイルはあなたのディスクに留まります。"
    ),
    bullets=(
        "- 🔒 **自分のマシンで動作** —— 既定は faster-whisper（CTranslate2）、ほかに whisper.cpp と NVIDIA Parakeet\n"
        "- 📝 **14 の出力形式** —— `srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf`、さらに oTranscribe / ELAN / InqScribe / Express Scribe\n"
        "- 🎙️ **リアルタイム文字起こし** —— マイクやシステム音声をその場で → [LIVE.md](../LIVE.md)\n"
        "- 🗣️ **話者ラベル** —— オフラインの話者分離、単語単位のタイムスタンプ、時間範囲の切り出し\n"
        "- 🎬 **ダウンロード** —— `yt-dlp` 対応サイト全般、完了後の自動文字起こしも可能\n"
        "- 🧹 **適応型ノイズ除去** —— 音声を計測し、効果がある場合にだけ処理 → [DENOISE.md](../DENOISE.md)\n"
        "- 🌐 **ローカルネットワークモード** —— このマシンを他の端末用の文字起こしページにできます\n"
        "- 💸 **無料・BSD-3 ライセンス** —— 従量課金なし、サブスクなし、既定でテレメトリなし"
    ),
    h_download="ダウンロード", h_features="機能", h_how="仕組み",
    h_offline="既定でオフライン", h_build="ソースからビルド", h_docs="ドキュメント",
    h_license="ライセンス",
    download_intro="最新版は **[リリースページ]({repo}/releases/latest)** から入手できます:",
    th_asset="ファイル", th_size="サイズ", th_best="向いている人",
    asset_standard="**ほとんどの方に。** 通常のインストーラー：スタートメニューのショートカット、旧版への上書き更新、ディスク上でファイルが見える形式。",
    asset_portable="展開して実行するだけ。インストール不要、管理者権限不要、USB メモリでも動作します。",
    asset_macos="macOS（x64 と arm64 は別々に配布）。",
    download_note=(
        "必要なものはすべて同梱されています —— Python 本体、`ffmpeg`、`ffprobe`、`yt-dlp`。"
        "あとから取得するのは音声モデルだけです（**約 1〜3 GB、初回起動時に一度だけ**）。"
        "それ以降はアプリは完全にオフラインで動作します。"
    ),
    f_local="ローカル文字起こし", f_local_d="既定は Whisper `large-v3`、ほかに `large-v3-turbo` と `distil-large-v3.5`。",
    f_formats="豊富な出力形式", f_formats_d="`srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf` —— 入力ファイルの隣に書き出します。",
    f_live="リアルタイム文字起こし", f_live_d="マイク、またはこのマシンが再生している音声をその場で文字起こし。自然な間で区切るため、単語が途中で切れません。",
    f_speakers="話者分離", f_speakers_d="任意の「話者を識別」機能、単語単位のタイムスタンプ、時間範囲の切り出し。",
    f_denoise="適応型ノイズ除去", f_denoise_d="まず録音を計測し、効果があると判断したときだけ処理します。処理結果も検証し、音声を削ってしまった場合は元に戻します。",
    f_queue="バッチキュー", f_queue_d="待機中・実行中のすべてのジョブの状態を表示。**一時停止 / 再開 / 取消 / 再実行 / 削除** が常にワンクリック。",
    f_download="ダウンロード", f_download_d="`yt-dlp` が扱えるものすべてと Supreme Master TV のエピソードリンク。中断時は最初からではなく再開します。",
    f_lan="ローカルネットワークモード", f_lan_d="標準ライブラリのみの Web サーバーで、他の端末がこのマシン経由で文字起こしできます —— パスワード設定可、起動するまでは無効。",
    how_body=(
        "Tk の GUI はメインプロセスで動作します。各文字起こしジョブは、"
        "Whisper モデルをメモリに保持し続けるワーカーサブプロセスで実行され、"
        "stdin/stdout 上の改行区切り JSON でやり取りします。`yt-dlp` はダウンロードごとに"
        "専用のサブプロセスを使います。ワーカーごとの UUID トークンと 5 秒ごとの"
        "ハートビートにより、PID の再利用があっても取り違えが起きず、"
        "固まったワーカーを GUI が検知できます。"
    ),
    offline_body=(
        "既定のバックエンドはすべて手元のマシンで動作します。何もアップロードされず、"
        "アカウントも存在せず、モデルのダウンロード後はネットワークを抜いても動作します。"
    ),
    offline_warning=(
        "**明示的に選んだ場合のみ**有効になる 2 つのバックエンドは、この保証の対象外です。"
        "**Advanced → Backend** で選択しない限り有効になりません。"
        "第三者に送信してよい内容にのみ使用してください。"
    ),
    th_doc="ドキュメント", th_about="内容",
    d_install="インストールとトラブルシューティング", d_live="ライブタブ",
    d_denoise="適応型ノイズ除去", d_server="ローカルネットワーク / Web サーバーモード",
    d_config="すべての設定キー", d_build="自分でビルドする", d_changelog="変更履歴",
    docs_note="詳細なドキュメントは英語です。このページは概要であり、詳細は英語版を参照してください。",
    license_body=(
        "本プロジェクトのソースは **BSD 3-Clause ライセンス** です —— [LICENSE](../../LICENSE) を参照。"
        "同梱のバイナリ（`ffmpeg`、`ffprobe`、`yt-dlp`）、同梱の Python ランタイムとパッケージ、"
        "および Whisper モデル自体はそれぞれ元のライセンスに従います。"
        "[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) にまとめてあります。"
    ),
    footer="オフライン音声認識 · ローカル Whisper GUI · 字幕生成 · 話者分離 · Windows · macOS",
)

T["ko"] = dict(
    tagline="오디오나 영상 파일을 끌어다 놓으세요. **시간 정보가 붙은 정돈된 자막·전사본**이 나옵니다 — 파일은 컴퓨터를 벗어나지 않습니다.",
    download_btn="Windows용 다운로드",
    intro=(
        "OpenAI Whisper 모델을 **로컬에서** 실행하는 데스크톱 앱입니다"
        "([faster-whisper](https://github.com/SYSTRAN/faster-whisper) 기반). "
        "분 단위 과금이 없고, 비행기 안에서도 동작하며, 녹음이 어디로도 업로드되지 않습니다. "
        "파일을 끌어다 놓으면 원본 옆에 `.srt`, `.vtt`, `.txt`, `.json`, `.docx`, `.pdf` 등을 만들어 줍니다. "
        "`yt-dlp`가 지원하는 모든 사이트에서 내려받고, 화자를 구분하고, 여러 작업을 큐로 처리하며, "
        "같은 네트워크의 다른 기기를 위한 전사 페이지가 될 수도 있습니다.\n\n"
        "계정 불필요. API 키 불필요. 구독 불필요. 파일은 내 디스크에 그대로 남습니다."
    ),
    bullets=(
        "- 🔒 **내 컴퓨터에서 실행** —— 기본은 faster-whisper(CTranslate2), 그 외 whisper.cpp와 NVIDIA Parakeet\n"
        "- 📝 **14가지 출력 형식** —— `srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf`, 그리고 oTranscribe / ELAN / InqScribe / Express Scribe\n"
        "- 🎙️ **실시간 전사** —— 마이크나 시스템 소리를 말하는 즉시 → [LIVE.md](../LIVE.md)\n"
        "- 🗣️ **화자 구분** —— 오프라인 화자 분리, 단어 단위 타임스탬프, 구간 자르기\n"
        "- 🎬 **다운로드** —— `yt-dlp`가 지원하는 모든 사이트, 완료 후 자동 전사 선택 가능\n"
        "- 🧹 **적응형 노이즈 제거** —— 먼저 측정하고, 도움이 될 때만 처리 → [DENOISE.md](../DENOISE.md)\n"
        "- 🌐 **로컬 네트워크 모드** —— 이 컴퓨터를 다른 기기용 전사 페이지로\n"
        "- 💸 **무료, BSD-3 라이선스** —— 분당 요금 없음, 구독 없음, 기본값으로 원격 수집 없음"
    ),
    h_download="다운로드", h_features="기능", h_how="작동 방식",
    h_offline="기본은 오프라인", h_build="소스에서 빌드", h_docs="문서",
    h_license="라이선스",
    download_intro="최신 빌드는 **[릴리스 페이지]({repo}/releases/latest)** 에서 받으세요:",
    th_asset="파일", th_size="크기", th_best="추천 대상",
    asset_standard="**대부분의 사용자.** 일반 설치 프로그램: 시작 메뉴 바로 가기, 기존 버전 위에 덮어쓰기 업그레이드, 디스크에서 파일 확인 가능.",
    asset_portable="압축을 풀고 실행만 하면 됩니다. 설치 불필요, 관리자 권한 불필요, USB에 넣어 다닐 수 있습니다.",
    asset_macos="macOS (x64와 arm64는 각각 배포).",
    download_note=(
        "필요한 것은 모두 들어 있습니다 —— 내장 Python, `ffmpeg`, `ffprobe`, `yt-dlp`. "
        "나중에 받는 것은 음성 모델뿐입니다(**약 1~3 GB, 첫 실행 시 한 번**). "
        "그 이후로는 완전히 오프라인으로 동작합니다."
    ),
    f_local="로컬 전사", f_local_d="기본값은 Whisper `large-v3`, 그 외 `large-v3-turbo`와 `distil-large-v3.5`.",
    f_formats="다양한 출력 형식", f_formats_d="`srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf` —— 입력 파일 옆에 저장됩니다.",
    f_live="실시간 전사", f_live_d="마이크 또는 이 컴퓨터가 재생 중인 소리를 실시간으로 전사합니다. 자연스러운 쉼에서 끊기 때문에 단어가 반으로 잘리지 않습니다.",
    f_speakers="화자 분리", f_speakers_d="선택적 '화자 식별' 기능과 단어 단위 타임스탬프, 구간 자르기.",
    f_denoise="적응형 노이즈 제거", f_denoise_d="녹음을 먼저 측정해 도움이 될 때만 처리하고, 결과를 다시 검사해 음성을 깎아냈다면 원본으로 되돌립니다.",
    f_queue="일괄 큐", f_queue_d="대기·실행 중인 모든 작업의 상태를 실시간 표시. **일시정지 / 재개 / 취소 / 다시 실행 / 제거** 가 항상 한 번의 클릭.",
    f_download="다운로드", f_download_d="`yt-dlp`가 처리하는 모든 것과 Supreme Master TV 에피소드 링크. 중단되면 처음부터가 아니라 이어받습니다.",
    f_lan="로컬 네트워크 모드", f_lan_d="표준 라이브러리만으로 만든 웹 서버로 다른 기기가 이 컴퓨터를 통해 전사할 수 있습니다 —— 비밀번호 설정 가능, 시작하기 전에는 꺼져 있습니다.",
    how_body=(
        "Tk GUI는 메인 프로세스에서 돌아갑니다. 각 전사 작업은 Whisper 모델을 메모리에 "
        "계속 올려 둔 장기 실행 워커 서브프로세스에서 실행되며, stdin/stdout의 줄 단위 JSON으로 "
        "통신합니다. `yt-dlp`는 다운로드마다 별도의 서브프로세스를 사용합니다. "
        "워커별 UUID 토큰과 5초 하트비트 덕분에 PID가 재사용되어도 신호가 뒤섞이지 않고, "
        "GUI가 멈춘 워커를 감지할 수 있습니다."
    ),
    offline_body=(
        "모든 기본 백엔드는 내 컴퓨터에서 동작합니다. 아무것도 업로드되지 않고, 계정도 없으며, "
        "모델을 한 번 내려받은 뒤에는 네트워크를 뽑아도 동작합니다."
    ),
    offline_warning=(
        "**직접 선택해야만** 켜지는 두 백엔드는 이 보장에서 예외입니다. "
        "**Advanced → Backend** 에서 고르지 않는 한 꺼져 있습니다. "
        "제3자에게 보내도 괜찮은 내용에만 사용하세요."
    ),
    th_doc="문서", th_about="내용",
    d_install="설치 및 문제 해결", d_live="Live 탭", d_denoise="적응형 노이즈 제거",
    d_server="로컬 네트워크 / 웹 서버 모드", d_config="모든 설정 키",
    d_build="직접 빌드하기", d_changelog="버전 기록",
    docs_note="전체 문서는 영어로 되어 있습니다. 이 페이지는 요약이며, 자세한 내용은 영어 문서를 참고하세요.",
    license_body=(
        "이 프로젝트의 소스는 **BSD 3-Clause 라이선스** 입니다 —— [LICENSE](../../LICENSE) 참고. "
        "함께 배포되는 바이너리(`ffmpeg`, `ffprobe`, `yt-dlp`), 내장 Python 런타임과 패키지, "
        "그리고 Whisper 모델 자체는 각자의 원래 라이선스를 따릅니다. "
        "[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) 에 정리되어 있습니다."
    ),
    footer="오프라인 음성 인식 · 로컬 Whisper GUI · 자막 생성 · 화자 분리 · Windows · macOS",
)

T["de"] = dict(
    tagline="Audio- oder Videodatei hineinziehen. Heraus kommt ein **zeitcodiertes, formatiertes Transkript** — ohne dass die Datei je den Rechner verlässt.",
    download_btn="Für Windows herunterladen",
    intro=(
        "Eine Desktop-Anwendung, die OpenAI's Whisper-Modell **lokal** ausführt — über "
        "[faster-whisper](https://github.com/SYSTRAN/faster-whisper). Dadurch kostet die "
        "Transkription nichts pro Minute, funktioniert im Flugzeug und lädt Ihre Aufnahme "
        "niemals irgendwohin hoch. Datei hineinziehen, und `.srt`, `.vtt`, `.txt`, `.json`, "
        "`.docx`, `.pdf` und mehr landen direkt neben dem Original. Außerdem lädt sie von "
        "jeder Seite herunter, die `yt-dlp` unterstützt, erkennt Sprecher, arbeitet eine "
        "Warteschlange ab und kann sich in eine Transkriptionsseite für die anderen Geräte "
        "im Netzwerk verwandeln.\n\n"
        "Kein Konto. Kein API-Schlüssel. Kein Abonnement. Ihre Dateien bleiben auf Ihrer Festplatte."
    ),
    bullets=(
        "- 🔒 **Läuft auf Ihrem Rechner** — standardmäßig faster-whisper (CTranslate2), dazu whisper.cpp und NVIDIA Parakeet\n"
        "- 📝 **14 Ausgabeformate** — `srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf`, dazu oTranscribe / ELAN / InqScribe / Express Scribe\n"
        "- 🎙️ **Live-Transkription** — Mikrofon oder Systemton, während gesprochen wird → [LIVE.md](../LIVE.md)\n"
        "- 🗣️ **Sprecherkennung** — offline, dazu wortgenaue Zeitstempel und Zeitbereichs-Zuschnitt\n"
        "- 🎬 **Downloads** — alles, was `yt-dlp` kann, auf Wunsch mit Transkription direkt danach\n"
        "- 🧹 **Adaptive Rauschreduktion** — misst das Audio und bereinigt nur, wenn das hilft → [DENOISE.md](../DENOISE.md)\n"
        "- 🌐 **Lokaler Netzwerkmodus** — dieser Rechner wird zur Transkriptionsseite für Ihre anderen Geräte\n"
        "- 💸 **Kostenlos und BSD-3-lizenziert** — keine Minutenkosten, kein Abo, standardmäßig keine Telemetrie"
    ),
    h_download="Download", h_features="Funktionen", h_how="Funktionsweise",
    h_offline="Standardmäßig offline", h_build="Aus dem Quellcode bauen",
    h_docs="Dokumentation", h_license="Lizenz",
    download_intro="Die aktuelle Version gibt es auf der **[Releases-Seite]({repo}/releases/latest)**:",
    th_asset="Datei", th_size="Größe", th_best="Geeignet für",
    asset_standard="**Die meisten Nutzer.** Ein normales Installationsprogramm: Startmenü-Verknüpfung, Upgrade über eine ältere Version hinweg, Dateien sichtbar auf der Festplatte.",
    asset_portable="Entpacken und starten. Keine Installation, keine Administratorrechte, läuft auch vom USB-Stick.",
    asset_macos="macOS (x64 und arm64 werden getrennt veröffentlicht).",
    download_note=(
        "Alles Nötige ist enthalten — ein mitgeliefertes Python, `ffmpeg`, `ffprobe` und `yt-dlp`. "
        "Nachgeladen wird einzig das Sprachmodell selbst (**ca. 1–3 GB, einmalig** beim ersten Start); "
        "danach arbeitet die Anwendung vollständig offline."
    ),
    f_local="Lokale Transkription", f_local_d="Standardmäßig Whisper `large-v3`, dazu `large-v3-turbo` und `distil-large-v3.5`.",
    f_formats="Viele Ausgabeformate", f_formats_d="`srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf` — direkt neben der Eingabedatei.",
    f_live="Live-Transkription", f_live_d="Transkribiert ein Mikrofon — oder was dieser Rechner gerade abspielt — während es passiert. Geschnitten wird in natürlichen Pausen, damit keine Wörter zerteilt werden.",
    f_speakers="Sprechertrennung", f_speakers_d="Optionales „Sprecher erkennen“, dazu wortgenaue Zeitstempel und Zeitbereichs-Zuschnitt.",
    f_denoise="Adaptive Rauschreduktion", f_denoise_d="Misst jede Aufnahme zuerst und bereinigt nur, wenn die Messung das nahelegt; prüft das eigene Ergebnis und verwirft es, wenn Sprache entfernt wurde.",
    f_queue="Stapelverarbeitung", f_queue_d="Live-Status für jeden wartenden und laufenden Auftrag, mit **Pause / Fortsetzen / Abbrechen / Erneut / Entfernen** stets einen Klick entfernt.",
    f_download="Downloads", f_download_d="Alles, was `yt-dlp` beherrscht, dazu Supreme-Master-TV-Folgenlinks. Downloads werden fortgesetzt statt neu begonnen.",
    f_lan="Lokaler Netzwerkmodus", f_lan_d="Ein Webserver nur aus der Standardbibliothek, damit andere Geräte über diesen Rechner transkribieren — optionales Passwort, aus bis Sie ihn starten.",
    how_body=(
        "Die Tk-Oberfläche läuft im Hauptprozess. Jeder Transkriptionsauftrag läuft in einem "
        "langlebigen Worker-Subprozess, der das Whisper-Modell im Speicher hält und über "
        "zeilengetrenntes JSON auf stdin/stdout zurückspricht; `yt-dlp` bekommt pro Download "
        "einen eigenen Subprozess. Ein UUID-Token je Worker und ein 5-Sekunden-Heartbeat halten "
        "diese Zuordnung robust gegen wiederverwendete Prozess-IDs und lassen die Oberfläche "
        "einen hängenden Worker erkennen, statt mit ihm zu hängen."
    ),
    offline_body=(
        "Alle Standard-Backends laufen auf Ihrem Rechner. Nichts wird hochgeladen, es gibt kein "
        "Konto, und nach dem Herunterladen des Modells funktioniert die Anwendung auch ohne Netzwerk."
    ),
    offline_warning=(
        "Zwei Backends, die Sie **ausdrücklich auswählen müssen**, durchbrechen diese Garantie. "
        "Sie sind aus, solange Sie sie nicht unter **Advanced → Backend** wählen. "
        "Nutzen Sie sie nur für Inhalte, die Sie an Dritte senden möchten."
    ),
    th_doc="Dokument", th_about="Inhalt",
    d_install="Installation und Fehlerbehebung", d_live="Der Live-Tab",
    d_denoise="Adaptive Rauschreduktion", d_server="Lokaler Netzwerk-/Webserver-Modus",
    d_config="Alle Konfigurationsschlüssel", d_build="Selbst bauen",
    d_changelog="Versionsverlauf",
    docs_note="Die vollständige Dokumentation ist auf Englisch. Diese Seite ist eine Übersicht; Details finden Sie in den englischen Dokumenten.",
    license_body=(
        "Der eigene Quellcode dieses Projekts steht unter der **BSD-3-Clause-Lizenz** — siehe "
        "[LICENSE](../../LICENSE). Die mitgelieferten Binärdateien (`ffmpeg`, `ffprobe`, `yt-dlp`), "
        "die mitgelieferte Python-Laufzeitumgebung samt Paketen und das Whisper-Modell selbst "
        "behalten ihre eigenen Lizenzen; [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) "
        "fasst sie zusammen."
    ),
    footer="Offline-Spracherkennung · lokale Whisper-Oberfläche · Untertitel-Generator · Sprechertrennung · Windows · macOS",
)

T["es"] = dict(
    tagline="Arrastre un archivo de audio o vídeo. Obtenga una **transcripción con marcas de tiempo y formato** — sin que el archivo salga nunca de su ordenador.",
    download_btn="Descargar para Windows",
    intro=(
        "Una aplicación de escritorio que ejecuta el modelo Whisper de OpenAI **en local**, "
        "mediante [faster-whisper](https://github.com/SYSTRAN/faster-whisper), de modo que "
        "transcribir no cuesta nada por minuto, funciona en un avión y nunca sube su grabación "
        "a ninguna parte. Suelte un archivo y escribirá `.srt`, `.vtt`, `.txt`, `.json`, "
        "`.docx`, `.pdf` y más, junto al original. También descarga de cualquier sitio "
        "compatible con `yt-dlp`, identifica a los hablantes, procesa una cola de trabajos y "
        "puede convertirse en una página de transcripción para los demás dispositivos de su red.\n\n"
        "Sin cuenta. Sin clave de API. Sin suscripción. Sus archivos permanecen en su disco."
    ),
    bullets=(
        "- 🔒 **Se ejecuta en su equipo** — faster-whisper (CTranslate2) por defecto, además de whisper.cpp y NVIDIA Parakeet\n"
        "- 📝 **14 formatos de salida** — `srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf`, más oTranscribe / ELAN / InqScribe / Express Scribe\n"
        "- 🎙️ **Transcripción en directo** — micrófono o sonido del sistema, mientras se habla → [LIVE.md](../LIVE.md)\n"
        "- 🗣️ **Etiquetas de hablante** — diarización sin conexión, marcas de tiempo por palabra y recorte por intervalos\n"
        "- 🎬 **Descargas** — cualquier sitio compatible con `yt-dlp`, con transcripción automática al terminar si lo desea\n"
        "- 🧹 **Reducción de ruido adaptativa** — mide el audio y solo lo limpia cuando eso ayuda → [DENOISE.md](../DENOISE.md)\n"
        "- 🌐 **Modo de red local** — convierta este equipo en una página de transcripción para sus otros dispositivos\n"
        "- 💸 **Gratis y con licencia BSD-3** — sin coste por minuto, sin suscripción, sin telemetría por defecto"
    ),
    h_download="Descarga", h_features="Funciones", h_how="Cómo funciona",
    h_offline="Sin conexión por defecto", h_build="Compilar desde el código fuente",
    h_docs="Documentación", h_license="Licencia",
    download_intro="Obtenga la última versión en la **[página de releases]({repo}/releases/latest)**:",
    th_asset="Archivo", th_size="Tamaño", th_best="Recomendado para",
    asset_standard="**La mayoría de la gente.** Un instalador normal: acceso directo en el menú Inicio, actualiza sobre una versión anterior, archivos visibles en el disco.",
    asset_portable="Descomprimir y ejecutar. Sin instalación, sin permisos de administrador, funciona desde una memoria USB.",
    asset_macos="macOS (x64 y arm64 se publican por separado).",
    download_note=(
        "Todo lo necesario va incluido: un Python integrado, `ffmpeg`, `ffprobe` y `yt-dlp`. "
        "Lo único que se descarga después es el propio modelo de voz (**1–3 GB, una sola vez**, "
        "en el primer inicio); a partir de ahí la aplicación funciona totalmente sin conexión."
    ),
    f_local="Transcripción local", f_local_d="Whisper `large-v3` por defecto, además de `large-v3-turbo` y `distil-large-v3.5`.",
    f_formats="Muchos formatos de salida", f_formats_d="`srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf` — escritos junto al archivo de entrada.",
    f_live="Transcripción en directo", f_live_d="Transcribe un micrófono —o lo que este equipo esté reproduciendo— en el momento. Los cortes caen en pausas naturales, así que las palabras nunca se parten.",
    f_speakers="Diarización de hablantes", f_speakers_d="«Identificar hablantes» opcional, además de marcas de tiempo por palabra y recorte por intervalos.",
    f_denoise="Reducción de ruido adaptativa", f_denoise_d="Mide cada grabación antes de actuar y solo la limpia cuando la medición lo justifica; comprueba su propio resultado y lo descarta si ha eliminado voz.",
    f_queue="Cola por lotes", f_queue_d="Estado en vivo de cada trabajo pendiente y en curso, con **Pausar / Reanudar / Cancelar / Repetir / Quitar** siempre a un clic.",
    f_download="Descargas", f_download_d="Todo lo que maneja `yt-dlp`, más los enlaces de episodios de Supreme Master TV. Las descargas se reanudan en lugar de reiniciarse.",
    f_lan="Modo de red local", f_lan_d="Un servidor web hecho solo con la biblioteca estándar para que otros dispositivos transcriban a través de este equipo — contraseña opcional, apagado hasta que usted lo inicie.",
    how_body=(
        "La interfaz Tk se ejecuta en el proceso principal. Cada trabajo de transcripción corre "
        "en un subproceso de larga vida que mantiene el modelo Whisper en memoria y responde "
        "mediante JSON delimitado por saltos de línea en stdin/stdout; `yt-dlp` recibe su propio "
        "subproceso por descarga. Un token UUID por trabajador y un latido de 5 segundos hacen "
        "que ese enrutado resista la reutilización de identificadores de proceso y permiten a la "
        "interfaz detectar un trabajador bloqueado en lugar de bloquearse con él."
    ),
    offline_body=(
        "Todos los backends por defecto se ejecutan en su máquina. No se sube nada, no existe "
        "ninguna cuenta y, una vez descargado el modelo, la aplicación funciona con la red desconectada."
    ),
    offline_warning=(
        "Dos backends **opcionales** rompen esa garantía y ambos están desactivados salvo que "
        "entre en **Advanced → Backend** y los elija. Úselos solo con contenido que esté "
        "dispuesto a enviar a un tercero."
    ),
    th_doc="Documento", th_about="Contenido",
    d_install="Instalación y resolución de problemas", d_live="La pestaña Live",
    d_denoise="Reducción de ruido adaptativa", d_server="Modo servidor web / red local",
    d_config="Todas las claves de configuración", d_build="Compilarlo usted mismo",
    d_changelog="Historial de versiones",
    docs_note="La documentación completa está en inglés. Esta página es un resumen; consulte los documentos en inglés para los detalles.",
    license_body=(
        "El código propio de este proyecto se publica bajo la **licencia BSD 3-Clause** — véase "
        "[LICENSE](../../LICENSE). Los binarios incluidos (`ffmpeg`, `ffprobe`, `yt-dlp`), el "
        "entorno de ejecución de Python y sus paquetes, y el propio modelo Whisper conservan sus "
        "licencias originales; [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) las resume."
    ),
    footer="transcripción sin conexión · Whisper local con interfaz gráfica · generador de subtítulos · diarización · Windows · macOS",
)

T["fr"] = dict(
    tagline="Déposez un fichier audio ou vidéo. Récupérez une **transcription horodatée et mise en forme** — sans que le fichier quitte jamais votre ordinateur.",
    download_btn="Télécharger pour Windows",
    intro=(
        "Une application de bureau qui exécute le modèle Whisper d'OpenAI **en local**, via "
        "[faster-whisper](https://github.com/SYSTRAN/faster-whisper) : la transcription ne coûte "
        "rien à la minute, fonctionne en avion et n'envoie jamais votre enregistrement à qui que "
        "ce soit. Déposez un fichier et l'application écrit `.srt`, `.vtt`, `.txt`, `.json`, "
        "`.docx`, `.pdf` et d'autres formats, juste à côté de l'original. Elle télécharge aussi "
        "depuis tous les sites pris en charge par `yt-dlp`, identifie les locuteurs, traite une "
        "file d'attente et peut se transformer en page de transcription pour les autres appareils "
        "de votre réseau.\n\n"
        "Pas de compte. Pas de clé d'API. Pas d'abonnement. Vos fichiers restent sur votre disque."
    ),
    bullets=(
        "- 🔒 **S'exécute sur votre machine** — faster-whisper (CTranslate2) par défaut, plus whisper.cpp et NVIDIA Parakeet\n"
        "- 📝 **14 formats de sortie** — `srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf`, plus oTranscribe / ELAN / InqScribe / Express Scribe\n"
        "- 🎙️ **Transcription en direct** — micro ou son du système, pendant que ça se dit → [LIVE.md](../LIVE.md)\n"
        "- 🗣️ **Étiquettes de locuteur** — diarisation hors ligne, horodatage par mot, découpe par intervalle\n"
        "- 🎬 **Téléchargements** — tous les sites gérés par `yt-dlp`, avec transcription automatique à la fin si vous le souhaitez\n"
        "- 🧹 **Débruitage adaptatif** — mesure l'audio et ne le nettoie que si cela aide → [DENOISE.md](../DENOISE.md)\n"
        "- 🌐 **Mode réseau local** — transformez cette machine en page de transcription pour vos autres appareils\n"
        "- 💸 **Gratuit et sous licence BSD-3** — aucun coût à la minute, aucun abonnement, aucune télémétrie par défaut"
    ),
    h_download="Téléchargement", h_features="Fonctionnalités",
    h_how="Fonctionnement", h_offline="Hors ligne par défaut",
    h_build="Compiler depuis les sources", h_docs="Documentation", h_license="Licence",
    download_intro="Récupérez la dernière version sur la **[page des releases]({repo}/releases/latest)** :",
    th_asset="Fichier", th_size="Taille", th_best="Recommandé pour",
    asset_standard="**La plupart des gens.** Un installateur classique : raccourci dans le menu Démarrer, mise à niveau par-dessus une version antérieure, fichiers visibles sur le disque.",
    asset_portable="Décompressez et lancez. Aucune installation, aucun droit administrateur, fonctionne depuis une clé USB.",
    asset_macos="macOS (x64 et arm64 sont publiés séparément).",
    download_note=(
        "Tout le nécessaire est inclus : un Python embarqué, `ffmpeg`, `ffprobe` et `yt-dlp`. "
        "Seul le modèle de reconnaissance vocale est téléchargé ensuite (**1 à 3 Go, une seule "
        "fois**, au premier lancement) ; après quoi l'application fonctionne entièrement hors ligne."
    ),
    f_local="Transcription locale", f_local_d="Whisper `large-v3` par défaut, plus `large-v3-turbo` et `distil-large-v3.5`.",
    f_formats="De nombreux formats", f_formats_d="`srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf` — écrits à côté du fichier d'entrée.",
    f_live="Transcription en direct", f_live_d="Transcrit un micro — ou ce que cette machine est en train de jouer — au fil de l'eau. Les coupures tombent dans les pauses naturelles, les mots ne sont donc jamais coupés en deux.",
    f_speakers="Diarisation des locuteurs", f_speakers_d="« Identifier les locuteurs » en option, plus l'horodatage par mot et la découpe par intervalle.",
    f_denoise="Débruitage adaptatif", f_denoise_d="Mesure chaque enregistrement d'abord et ne le nettoie que si la mesure le justifie ; vérifie son propre résultat et l'abandonne s'il a supprimé de la parole.",
    f_queue="File de traitement", f_queue_d="État en direct de chaque tâche en attente ou en cours, avec **Pause / Reprendre / Annuler / Relancer / Retirer** toujours à un clic.",
    f_download="Téléchargements", f_download_d="Tout ce que `yt-dlp` sait faire, plus les liens d'épisodes Supreme Master TV. Les téléchargements reprennent au lieu de recommencer.",
    f_lan="Mode réseau local", f_lan_d="Un serveur web fait uniquement avec la bibliothèque standard, pour que d'autres appareils transcrivent via cette machine — mot de passe facultatif, éteint tant que vous ne le démarrez pas.",
    how_body=(
        "L'interface Tk s'exécute dans le processus principal. Chaque tâche de transcription "
        "tourne dans un sous-processus de longue durée qui garde le modèle Whisper en mémoire et "
        "répond en JSON délimité par des sauts de ligne sur stdin/stdout ; `yt-dlp` reçoit son "
        "propre sous-processus par téléchargement. Un jeton UUID par worker et un battement de "
        "cœur toutes les 5 secondes rendent ce routage robuste face au recyclage des "
        "identifiants de processus et permettent à l'interface de détecter un worker bloqué au "
        "lieu de se bloquer avec lui."
    ),
    offline_body=(
        "Tous les moteurs par défaut s'exécutent sur votre machine. Rien n'est envoyé, aucun "
        "compte n'existe, et une fois le modèle téléchargé l'application fonctionne réseau débranché."
    ),
    offline_warning=(
        "Deux moteurs **optionnels** rompent cette garantie, et tous deux restent désactivés tant "
        "que vous n'allez pas les choisir dans **Advanced → Backend**. Ne les utilisez que pour "
        "du contenu que vous acceptez d'envoyer à un tiers."
    ),
    th_doc="Document", th_about="Contenu",
    d_install="Installation et dépannage", d_live="L'onglet Live",
    d_denoise="Débruitage adaptatif", d_server="Mode serveur web / réseau local",
    d_config="Toutes les clés de configuration", d_build="Compiler soi-même",
    d_changelog="Historique des versions",
    docs_note="La documentation complète est en anglais. Cette page est un aperçu ; reportez-vous aux documents anglais pour le détail.",
    license_body=(
        "Le code propre à ce projet est publié sous **licence BSD 3-Clause** — voir "
        "[LICENSE](../../LICENSE). Les binaires embarqués (`ffmpeg`, `ffprobe`, `yt-dlp`), "
        "l'environnement Python fourni et ses paquets, ainsi que le modèle Whisper lui-même "
        "conservent leurs licences d'origine ; "
        "[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) les récapitule."
    ),
    footer="transcription hors ligne · Whisper local avec interface · générateur de sous-titres · diarisation · Windows · macOS",
)

T["pt"] = dict(
    tagline="Arraste um ficheiro de áudio ou vídeo. Receba uma **transcrição com marcação de tempo e formatada** — sem que o ficheiro saia do seu computador.",
    download_btn="Transferir para Windows",
    intro=(
        "Uma aplicação de ambiente de trabalho que executa o modelo Whisper da OpenAI "
        "**localmente**, através do [faster-whisper](https://github.com/SYSTRAN/faster-whisper), "
        "pelo que transcrever não custa nada por minuto, funciona num avião e nunca envia a sua "
        "gravação para ninguém. Largue um ficheiro e serão escritos `.srt`, `.vtt`, `.txt`, "
        "`.json`, `.docx`, `.pdf` e mais, ao lado do original. Também descarrega de qualquer site "
        "suportado pelo `yt-dlp`, identifica oradores, processa uma fila de trabalhos e pode "
        "transformar-se numa página de transcrição para os outros dispositivos da sua rede.\n\n"
        "Sem conta. Sem chave de API. Sem subscrição. Os seus ficheiros ficam no seu disco."
    ),
    bullets=(
        "- 🔒 **Corre na sua máquina** — faster-whisper (CTranslate2) por omissão, mais whisper.cpp e NVIDIA Parakeet\n"
        "- 📝 **14 formatos de saída** — `srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf`, mais oTranscribe / ELAN / InqScribe / Express Scribe\n"
        "- 🎙️ **Transcrição em direto** — microfone ou som do sistema, enquanto se fala → [LIVE.md](../LIVE.md)\n"
        "- 🗣️ **Identificação de oradores** — diarização offline, marcação de tempo por palavra e corte por intervalo\n"
        "- 🎬 **Descargas** — qualquer site suportado pelo `yt-dlp`, com transcrição automática no fim se quiser\n"
        "- 🧹 **Redução de ruído adaptativa** — mede o áudio e só o limpa quando isso ajuda → [DENOISE.md](../DENOISE.md)\n"
        "- 🌐 **Modo de rede local** — torne esta máquina numa página de transcrição para os seus outros dispositivos\n"
        "- 💸 **Gratuito e com licença BSD-3** — sem custo por minuto, sem subscrição, sem telemetria por omissão"
    ),
    h_download="Transferência", h_features="Funcionalidades",
    h_how="Como funciona", h_offline="Offline por omissão",
    h_build="Compilar a partir do código", h_docs="Documentação", h_license="Licença",
    download_intro="Obtenha a versão mais recente na **[página de releases]({repo}/releases/latest)**:",
    th_asset="Ficheiro", th_size="Tamanho", th_best="Indicado para",
    asset_standard="**A maioria das pessoas.** Um instalador normal: atalho no menu Iniciar, atualiza por cima de uma versão anterior, ficheiros visíveis no disco.",
    asset_portable="Descompactar e executar. Sem instalação, sem permissões de administrador, funciona numa pen USB.",
    asset_macos="macOS (x64 e arm64 são publicados em separado).",
    download_note=(
        "Está tudo incluído — um Python integrado, `ffmpeg`, `ffprobe` e `yt-dlp`. "
        "A única coisa transferida depois é o próprio modelo de voz (**1–3 GB, uma só vez**, "
        "no primeiro arranque); a partir daí a aplicação funciona totalmente offline."
    ),
    f_local="Transcrição local", f_local_d="Whisper `large-v3` por omissão, mais `large-v3-turbo` e `distil-large-v3.5`.",
    f_formats="Muitos formatos de saída", f_formats_d="`srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf` — escritos ao lado do ficheiro de entrada.",
    f_live="Transcrição em direto", f_live_d="Transcreve um microfone — ou o que esta máquina estiver a reproduzir — em tempo real. Os cortes caem em pausas naturais, pelo que as palavras nunca ficam partidas ao meio.",
    f_speakers="Diarização de oradores", f_speakers_d="«Identificar oradores» opcional, mais marcação de tempo por palavra e corte por intervalo.",
    f_denoise="Redução de ruído adaptativa", f_denoise_d="Mede cada gravação primeiro e só a limpa quando a medição o justifica; verifica o próprio resultado e descarta-o se tiver removido voz.",
    f_queue="Fila de processamento", f_queue_d="Estado em direto de cada trabalho pendente e em curso, com **Pausar / Retomar / Cancelar / Repetir / Remover** sempre a um clique.",
    f_download="Descargas", f_download_d="Tudo o que o `yt-dlp` consegue, mais ligações de episódios da Supreme Master TV. As descargas retomam em vez de recomeçar.",
    f_lan="Modo de rede local", f_lan_d="Um servidor web feito só com a biblioteca padrão, para que outros dispositivos transcrevam através desta máquina — palavra-passe opcional, desligado até o iniciar.",
    how_body=(
        "A interface Tk corre no processo principal. Cada trabalho de transcrição corre num "
        "subprocesso de longa duração que mantém o modelo Whisper em memória e responde por JSON "
        "delimitado por linhas em stdin/stdout; o `yt-dlp` recebe um subprocesso próprio por "
        "descarga. Um token UUID por worker e um sinal de vida de 5 segundos tornam esse "
        "encaminhamento robusto face à reutilização de identificadores de processo e permitem à "
        "interface detetar um worker bloqueado em vez de bloquear com ele."
    ),
    offline_body=(
        "Todos os backends por omissão correm na sua máquina. Nada é enviado, não existe conta e, "
        "depois de o modelo ser transferido, a aplicação funciona com a rede desligada."
    ),
    offline_warning=(
        "Dois backends **opcionais** quebram essa garantia e ambos estão desligados a menos que "
        "vá a **Advanced → Backend** e os escolha. Use-os apenas com conteúdo que esteja "
        "disposto a enviar a terceiros."
    ),
    th_doc="Documento", th_about="Conteúdo",
    d_install="Instalação e resolução de problemas", d_live="O separador Live",
    d_denoise="Redução de ruído adaptativa", d_server="Modo servidor web / rede local",
    d_config="Todas as chaves de configuração", d_build="Compilar por si próprio",
    d_changelog="Histórico de versões",
    docs_note="A documentação completa está em inglês. Esta página é um resumo; consulte os documentos em inglês para os detalhes.",
    license_body=(
        "O código próprio deste projeto está sob a **licença BSD 3-Clause** — ver "
        "[LICENSE](../../LICENSE). Os binários incluídos (`ffmpeg`, `ffprobe`, `yt-dlp`), o "
        "ambiente Python fornecido e os seus pacotes, e o próprio modelo Whisper mantêm as suas "
        "licenças originais; [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) resume-as."
    ),
    footer="transcrição offline · Whisper local com interface · gerador de legendas · diarização · Windows · macOS",
)


def render(code: str) -> str:
    strings = dict(T[code])
    strings["download_intro"] = strings["download_intro"].format(repo=REPO)
    return TEMPLATE.format(
        badges=BADGES, switcher=switcher(code), repo=REPO, **strings
    )


def main(argv: list[str]) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(os.path.dirname(here), "docs", "i18n")
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for code in T:
        path = os.path.join(out_dir, f"README.{code}.md")
        with io.open(path, "w", encoding="utf-8", newline="\n") as fp:
            fp.write(render(code))
        written.append(os.path.basename(path))
    print(f"wrote {len(written)} translated READMEs into docs/i18n/:")
    for name in written:
        print(f"  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
