<div align="center">

<img src="../img/hero.png" alt="Whisper Project" width="100%">

# Whisper Project

### 音声・動画ファイルをドロップするだけ。**タイムコード付きの整形済み文字起こし**が、ファイルを外に出さずに手に入ります。

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![downloads](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/total?color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases)
[![License: BSD-3](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)
[![Stars](https://img.shields.io/github/stars/Milomilo777/whisper-transcriber-suite?style=flat&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/stargazers)

### [⬇  Windows 版をダウンロード](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

<p>
  <a href="../../README.md"><img src="https://flagcdn.com/16x12/us.png" alt="" width="16" height="12"> English</a> ∙
  <a href="README.zh-CN.md"><img src="https://flagcdn.com/16x12/cn.png" alt="" width="16" height="12"> 简体中文</a> ∙
  <img src="https://flagcdn.com/16x12/jp.png" alt="" width="16" height="12">
  <b>日本語</b> ∙
  <a href="README.ko.md"><img src="https://flagcdn.com/16x12/kr.png" alt="" width="16" height="12"> 한국어</a> ∙
  <a href="README.de.md"><img src="https://flagcdn.com/16x12/de.png" alt="" width="16" height="12"> Deutsch</a> ∙
  <a href="README.es.md"><img src="https://flagcdn.com/16x12/es.png" alt="" width="16" height="12"> Español</a> ∙
  <a href="README.fr.md"><img src="https://flagcdn.com/16x12/fr.png" alt="" width="16" height="12"> Français</a> ∙
  <a href="README.pt.md"><img src="https://flagcdn.com/16x12/pt.png" alt="" width="16" height="12"> Português</a> ∙
  <a href="README.fa.md"><img src="https://flagcdn.com/16x12/ir.png" alt="" width="16" height="12"> فارسی</a>
</p>

</div>

---

OpenAI の Whisper モデルを**ローカルで**動かすデスクトップアプリです（[faster-whisper](https://github.com/SYSTRAN/faster-whisper) を使用）。分単位の課金がなく、機内でも動作し、録音が誰かにアップロードされることはありません。ファイルをドロップすると、元ファイルの隣に `.srt`、`.vtt`、`.txt`、`.json`、`.docx`、`.pdf` などを書き出します。`yt-dlp` が対応するサイトからのダウンロード、話者の識別、ジョブのバッチ処理、そして同じネットワーク上の他の端末向けの文字起こしページ化にも対応しています。

アカウント不要。API キー不要。サブスクリプション不要。ファイルはあなたのディスクに留まります。

- 🔒 **自分のマシンで動作** —— 既定は faster-whisper（CTranslate2）、ほかに whisper.cpp と NVIDIA Parakeet
- 📝 **14 の出力形式** —— `srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf`、さらに oTranscribe / ELAN / InqScribe / Express Scribe
- 🎙️ **リアルタイム文字起こし** —— マイクやシステム音声をその場で → [LIVE.md](../LIVE.md)
- 🗣️ **話者ラベル** —— オフラインの話者分離、単語単位のタイムスタンプ、時間範囲の切り出し
- 🎬 **ダウンロード** —— `yt-dlp` 対応サイト全般、完了後の自動文字起こしも可能
- 🧹 **適応型ノイズ除去** —— 音声を計測し、効果がある場合にだけ処理 → [DENOISE.md](../DENOISE.md)
- 🌐 **ローカルネットワークモード** —— このマシンを他の端末用の文字起こしページにできます
- 💸 **無料・BSD-3 ライセンス** —— 従量課金なし、サブスクなし、既定でテレメトリなし

## ダウンロード

最新版は **[リリースページ](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)** から入手できます:

| ファイル | サイズ | 向いている人 |
|---|---|---|
| **`WhisperProject-…-Setup-Standard.exe`** | ~215 MB | **ほとんどの方に。** 通常のインストーラー：スタートメニューのショートカット、旧版への上書き更新、ディスク上でファイルが見える形式。 |
| **`WhisperProject-…-Portable.zip`** | ~330 MB | 展開して実行するだけ。インストール不要、管理者権限不要、USB メモリでも動作します。 |
| **`WhisperProject-…-macOS-*.dmg`** | ~400 MB | macOS（x64 と arm64 は別々に配布）。 |

必要なものはすべて同梱されています —— Python 本体、`ffmpeg`、`ffprobe`、`yt-dlp`。あとから取得するのは音声モデルだけです（**約 1〜3 GB、初回起動時に一度だけ**）。それ以降はアプリは完全にオフラインで動作します。

## 機能

<div align="center">

<img src="../img/features.png" alt="" width="100%">

</div>

| | |
|---|---|
| **ローカル文字起こし** | 既定は Whisper `large-v3`、ほかに `large-v3-turbo` と `distil-large-v3.5`。 |
| **豊富な出力形式** | `srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf` —— 入力ファイルの隣に書き出します。 |
| **リアルタイム文字起こし** | マイク、またはこのマシンが再生している音声をその場で文字起こし。自然な間で区切るため、単語が途中で切れません。 |
| **話者分離** | 任意の「話者を識別」機能、単語単位のタイムスタンプ、時間範囲の切り出し。 |
| **適応型ノイズ除去** | まず録音を計測し、効果があると判断したときだけ処理します。処理結果も検証し、音声を削ってしまった場合は元に戻します。 |
| **バッチキュー** | 待機中・実行中のすべてのジョブの状態を表示。**一時停止 / 再開 / 取消 / 再実行 / 削除** が常にワンクリック。 |
| **ダウンロード** | `yt-dlp` が扱えるものすべてと Supreme Master TV のエピソードリンク。中断時は最初からではなく再開します。 |
| **ローカルネットワークモード** | 標準ライブラリのみの Web サーバーで、他の端末がこのマシン経由で文字起こしできます —— パスワード設定可、起動するまでは無効。 |

## 仕組み

<div align="center">

<img src="../img/how-it-works.png" alt="" width="100%">

</div>

Tk の GUI はメインプロセスで動作します。各文字起こしジョブは、Whisper モデルをメモリに保持し続けるワーカーサブプロセスで実行され、stdin/stdout 上の改行区切り JSON でやり取りします。`yt-dlp` はダウンロードごとに専用のサブプロセスを使います。ワーカーごとの UUID トークンと 5 秒ごとのハートビートにより、PID の再利用があっても取り違えが起きず、固まったワーカーを GUI が検知できます。

## 既定でオフライン

既定のバックエンドはすべて手元のマシンで動作します。何もアップロードされず、アカウントも存在せず、モデルのダウンロード後はネットワークを抜いても動作します。

> [!IMPORTANT]
> **明示的に選んだ場合のみ**有効になる 2 つのバックエンドは、この保証の対象外です。**Advanced → Backend** で選択しない限り有効になりません。第三者に送信してよい内容にのみ使用してください。
>
> - **`cloud_stt`** — Google Gemini API → [CLOUD_STT.md](../CLOUD_STT.md)
> - **`google_cloud_stt`** — Google Cloud Speech-to-Text → [CLOUD_STT_GOOGLE.md](../CLOUD_STT_GOOGLE.md)

## ソースからビルド

```bash
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

## ドキュメント

| ドキュメント | 内容 |
|---|---|
| [INSTALL.md](../INSTALL.md) | インストールとトラブルシューティング |
| [LIVE.md](../LIVE.md) | ライブタブ |
| [DENOISE.md](../DENOISE.md) | 適応型ノイズ除去 |
| [SERVER.md](../SERVER.md) | ローカルネットワーク / Web サーバーモード |
| [CONFIG.md](../CONFIG.md) | すべての設定キー |
| [BUILD.md](../BUILD.md) | 自分でビルドする |
| [CHANGELOG.md](../CHANGELOG.md) | 変更履歴 |

> 詳細なドキュメントは英語です。このページは概要であり、詳細は英語版を参照してください。

## ライセンス

本プロジェクトのソースは **BSD 3-Clause ライセンス** です —— [LICENSE](../../LICENSE) を参照。同梱のバイナリ（`ffmpeg`、`ffprobe`、`yt-dlp`）、同梱の Python ランタイムとパッケージ、および Whisper モデル自体はそれぞれ元のライセンスに従います。[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) にまとめてあります。

---

<div align="center">
<sub>オフライン音声認識 · ローカル Whisper GUI · 字幕生成 · 話者分離 · Windows · macOS</sub>
</div>
