<div align="center">

<img src="../img/hero.png" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**長時間の音声や動画のための、無料でオフライン動作する文字起こしおよび字幕生成ツール。一般的なノートPCで動き、アカウント登録や音声のアップロードは不要です。**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Windows 版をダウンロード](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS と Linux: [ダウンロード](#download) をご覧ください。

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
<b>日本語</b> ·
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

## 対象ユーザー

本ツールは、長時間の録音や動画（インタビュー、講義、トークなど）をテキストや字幕に変換する必要がある、字幕制作者、翻訳者、研究者、ジャーナリストに最適です。音声や動画ファイルをドロップするだけで、その横に文字起こしファイルが出力されます。音声認識エンジンはご自身のコンピュータ上でローカルに実行されるため、1分ごとの課金は一切かかりません。さらに、一度モデルをダウンロードすればインターネット接続も不要になります。

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="Transcribe タブ：ファイルのドロップ領域、エンジンと言語の選択、話者ラベルと単語タイムスタンプのオプション" width="80%">
</div>

## バージョン 2.0 の新機能

- **速度と残り時間：** Queue（キュー）タブに、各ジョブの処理速度とおおよその残り時間が表示されます。
- **リンクからの字幕付き動画の生成：** 動画のダウンロード、文字起こし、字幕の焼き付けを一連のジョブとして一括で実行できます（[../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)）。
- **Webページとしての文字起こし：** オフラインでもあらゆるブラウザで動作し、検索やクリック再生が可能な単一の `.html` ファイルを出力します。
- **接続状態がわかるオフラインモード：** Work offline がオンの場合、アプリやそれが起動したプロセスがネットワークに接続しているかどうかをステータスバーに表示します。
- **英語への翻訳：** 英語以外の音声を、一度の処理で直接英語字幕に変換します。
- **クイックスタート：** 新規インストール時に3つの質問があり、18秒のサンプルクリップで即座に結果を確認できます。
- **問題の報告：** GitHubアカウントなしで Help メニューから問題を報告できます。
- **macOS：** Settings（Command+カンマ）を含むアプリメニュー、システムに連動するライト/ダークモード、通知。**Windows：** タスクバーの進捗表示とダークなタイトルバー。

完全なリスト：[CHANGELOG](../CHANGELOG.md)。

## 機能

- **ローカルエンジン：** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  （デフォルト）、whisper.cpp、NVIDIA Parakeet を搭載し、Whisper が認識できる多数の言語に対応しています。可能であれば CUDA を通じて NVIDIA GPU を使用し、それ以外の場合は CPU を使用します。
- **あなたの言語で使えるアプリ：** メニュー、ボタン、メッセージが42言語に対応しています（機械翻訳で、その旨を表示しています。修正のご提案を歓迎します）。システムの言語に従うほか、詳細設定で言語を選ぶこともできます。ペルシア語、アラビア語、ヘブライ語は、現時点ではWindowsで利用できます。
- **14種類の出力フォーマット：** SRT、VTT、ASS、TSV、TXT、JSON、LRC、Markdown、DOCX、PDF に加え、oTranscribe、ELAN、InqScribe、Express Scribe フォーマット。DOCX と PDF はすべての文字スクリプトを描画し、ペルシア語、アラビア語、ウルドゥー語では右から左へ文字を繋げて正しく表示します。
- **共有可能なWebページ：** 完成した文字起こしを、あらゆるブラウザでオフライン動作する単一の `.html` ファイルとして保存できます。単語をクリックして音声を再生したり、検索したり、各チャプターにジャンプしたりできます。
- **話者ラベル**：Hugging Face のアカウント不要。さらに単語レベルのタイムスタンプや時間範囲の切り出し機能も搭載。
- **中断されたジョブの再開**：最初からやり直すのではなく、最後のチェックポイントから再開します（デフォルトエンジン）。
- **オンライン動画：** [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  がサポートするあらゆるサイトからダウンロードし、ダウンロードが完了した時点で自動的に文字起こしを実行します。
- **字幕付き動画リンク：** チェックを入れるだけで、リンク先の動画を字幕焼き付け済みの `<title>-subbed.mp4` に変換します。ダウンロードから文字起こし、字幕の焼き付けまでを1つのキュージョブとして完了します（[../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)）。
- **リアルタイム文字起こし（Live）：** マイク入力や、Windows ではシステム音声をリアルタイムで文字起こしします（[../LIVE.md](../LIVE.md)）。
- **バッチキューと監視フォルダ：** 大量のファイルを処理するための機能。
- **ローカルネットワークモード：** ネットワーク上の他のデバイス向けに、文字起こしページや OpenAI 互換の API を提供します（[../SERVER.md](../SERVER.md)）。
- **オプション（デフォルトではオフ）：** 完成した文字起こし用の AI ツール（要約、質問、2言語併記 SRT）、および音声クローン対応のオフラインテキスト読み上げ機能。

Subtitle Edit、Vibe、Buzz、noScribe、aTrain との比較。他のアプリを選んだ方がよいケースも含めて：
**[../COMPARISON.md](../COMPARISON.md)**。

<a id="download"></a>

## ダウンロード

最新リリース：**[リリースページ](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**。

| ファイル | 対象 |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 または 11、64ビット。ほとんどの方はこちらをお選びください。 |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | インストール不要の Windows 版：解凍して実行。 |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Apple シリコン搭載 Mac、macOS 14 以降。 |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Intel Mac、macOS 10.15 以降。 |

Linux はソースから実行します：[../platform/linux/README.md](../../platform/linux/README.md)。

同梱されている FFmpeg は GPL ビルドです。対応するソースは各リリースに
`WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*` ファイルとして添付されています。正確なリンクは
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) にあります。

ffmpeg と yt-dlp は同梱されています。初回起動時にクイックスタートウィンドウが開き、使用する言語の音声モデルを選択します。Fast（Small、約 500 MB）または Best quality（最大約 3 GB）があり、モデルのダウンロードは初回使用時の1回のみです。8 GB の RAM を想定してください。CPUを使用する場合、Large モデルは音声の長さの約 1.5 ～ 2.5 倍の時間がかかり、Small モデルは約半分の時間で済みます。NVIDIA GPU を使用すると非常に高速になります。Windows 版はコード署名されておらず、Mac 版は公証（Notarization）されていないため、初回起動時に SmartScreen や Gatekeeper の警告が出ます。[../INSTALL.md](../INSTALL.md) でクリックする手順を説明しています。アップデートする場合は、古いバージョンの上に新しいインストーラーを実行してください。設定は保持されます。

**バージョンごとのダウンロード数**（各バッジはそのバージョン独自のリリースのみをカウントしています。古いバージョンは公開されたままであり、カウントがリセットされることはありません）：

[![v2.1.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.1.0/total?label=v2.1.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.1.0)
[![v2.0.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.0.0/total?label=v2.0.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0)
[![v1.9.3](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.3/total?label=v1.9.3&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.3)
[![v1.9.1](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.1/total?label=v1.9.1&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.1)
[![v1.9.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.0/total?label=v1.9.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.0)
[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

## コンピュータの外部に送信される情報

デフォルトの設定では、音声や文字起こしのテキストは自分のコンピュータ内に留まります。
アプリは以下の目的でネットワークを使用します：

- モデルやオプションのコンポーネントを初めて必要とするときにダウンロードするため。
- 起動時のオンライン設定の取得と、GitHub での1日1回の更新確認（新しいバージョンがあることをお知らせする目的のみ）。
- 利用統計（デフォルトでオン）。文字起こし完了後に送信されます：モデル、言語、継続時間、単語数、アプリのバージョン、オペレーティングシステム、CPU とメモリサイズ、地域が含まれます。ファイル名が送信されることは絶対にありません。**Help → Usage statistics** でオフにできます。

音声や文字起こしテキストが送信されるのは、クラウドエンジン（Gemini API または Google Cloud Speech-to-Text）を選択するか、自身でリモートの AI プロバイダに接続した場合のみです。
**File → Work offline** を選択すると、すべての通信が停止します。すべての通信内容は [../CONFIG.md](../CONFIG.md#network-use) に記載されています。

## ドキュメント

[Install](../INSTALL.md) · [Configuration](../CONFIG.md) ·
[Live transcription](../LIVE.md) · [Local-network mode and API](../SERVER.md) ·
[Cloud engines](../CLOUD_STT.md) · [Architecture](../ARCHITECTURE.md) ·
[Changelog](../CHANGELOG.md) · [All docs](../README.md)

## ソースからのビルド

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Python 3.11 以降が必要です。ビルドパイプライン：[../BUILD.md](../BUILD.md)。テストおよびプルリクエスト：
[../../CONTRIBUTING.md](../../CONTRIBUTING.md)。

## コントリビューションと連絡先

- **バグや機能リクエスト：** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **質問やアイデア：** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **その他すべて：** メール、または
  [ウェブサイトの連絡先セクション（Contact）](https://whisper-transcriber-suite.pages.dev/#contact) から
- **セキュリティの報告：** [../../SECURITY.md](../../SECURITY.md)

このプロジェクトは [Contributor Covenant（行動規範）](../../.github/CODE_OF_CONDUCT.md) に従っています。
もしこのアプリがあなたの時間を節約できたなら、このページ上部にある Star を押していただけると、他の人が見つけやすくなります。

## このプロジェクトが作られた方法

メンテナは AI コーディングアシスタント（主に Claude）の多大な支援を受けて開発を行っています。コミット前には型チェックとユニットテストが通過する必要があり、プッシュ後には CI が Windows と Linux で再実行します。[リリースチェックリスト](../RELEASE_PROCESS.md) には、実機での手動インストールテストが含まれています。AI の支援を受けた最近のコミットには `Assisted-by:` 行でモデル名が記載されており、古いものの多くには代わりに `Co-Authored-By: Claude` の行が含まれています。

## ライセンス

Copyright (c) 2026 translation-robot (co-author). プロジェクトはこのリポジトリ
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite) にあります。
プロジェクト自身のソースは [BSD 3-Clause License](../../LICENSE) の下で提供されています。同梱されているツール、Python ランタイム、およびモデルは、それぞれのライセンスを保持しています。詳細は
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) をご覧ください。
