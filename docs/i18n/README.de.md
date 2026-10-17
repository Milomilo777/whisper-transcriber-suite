<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**Kostenlose Offline-Transkription und Untertitel für lange Aufnahmen in Ihrer Sprache — auf einem normalen Laptop, ohne Konto und ohne Audio-Upload.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Download für Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS und Linux: siehe [Download](#download).

<!-- language-links:start -->

<p>
<a href="../../README.md">English</a> ·
<b>Deutsch</b> ·
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

## Für wen es ist

Untertitel-Ersteller, Übersetzer, Forscher und Journalisten, die lange
Aufnahmen (Interviews, Vorlesungen, Vorträge, Videos) in Text oder Untertitel umwandeln.
Ziehen Sie eine Audio- oder Videodatei hinein, und das Transkript wird direkt daneben geschrieben. Die Spracherkennung läuft auf Ihrem eigenen Computer, es gibt also
keine Kosten pro Minute und nach dem Herunterladen des Modells ist keine Internetverbindung
mehr erforderlich.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="Der Tab Transcribe: ein Ablagebereich, Auswahl für Engine und Sprache, Optionen für Sprecherkennzeichnung und Wort-Zeitstempel" width="80%">
</div>

## Was ist neu in 2.0

- **Geschwindigkeit und verbleibende Zeit:** Der Reiter "Queue" zeigt die Geschwindigkeit jedes Auftrags und eine geschätzte verbleibende Zeit an.
- **Untertitelte Videos per Link:** Herunterladen, transkribieren und Untertitel einbrennen als ein Auftrag ([docs/SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Transkript als Webseite:** Eine `.html`-Datei mit Suche und Click-to-Play, die offline in jedem Browser funktioniert.
- **Überprüfbares Offline-Arbeiten:** Wenn "Work offline" aktiviert ist, zeigt eine Statuszeile an, ob die App oder ein von ihr gestarteter Prozess eine Netzwerkverbindung hat.
- **Übersetzung ins Englische:** Nicht-englische Sprache wird in einem Durchgang zu englischen Untertiteln.
- **Schnellstart:** Bei Neuinstallationen werden drei Fragen gestellt, und ein 18-sekündiger Beispielclip zeigt sofort ein Ergebnis.
- **Problem melden:** Aus dem Help-Menü, ohne ein GitHub-Konto.
- **macOS:** App-Menü mit Settings (Command-Komma), Light und Dark passend zum System, Benachrichtigungen. **Windows:** Taskleisten-Fortschritt und dunkle Titelleisten.

Vollständige Liste: [CHANGELOG](../CHANGELOG.md).

## Funktionen

- **Lokale Engines:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (Standard), whisper.cpp und NVIDIA Parakeet, für die vielen Sprachen, die Whisper
  erkennt. Nutzt eine NVIDIA-GPU
  über CUDA, wenn möglich, andernfalls die CPU.
- **Die App in Ihrer Sprache:** Menüs, Schaltflächen und Meldungen in 42 Sprachen
  (maschinell übersetzt und als solche gekennzeichnet; Korrekturen sind willkommen).
  Die Sprache folgt Ihrem System, oder Sie wählen sie in den erweiterten
  Einstellungen. Persisch, Arabisch und Hebräisch werden vorerst unter Windows
  angeboten.
- **14 Ausgabeformate:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX und
  PDF, plus die Formate oTranscribe, ELAN, InqScribe und Express Scribe. DOCX
  und PDF zeichnen jede Schrift korrekt, und Persisch, Arabisch und Urdu werden von rechts nach links
  mit verbundenen Buchstaben gelesen.
- **Teilbare Webseite:** Speichern Sie ein fertiges Transkript als eine `.html`-Datei, die
  offline in jedem Browser funktioniert; klicken Sie auf ein Wort, um es zu hören, suchen Sie, springen Sie zu
  Kapiteln.
- **Sprecher-Labels** ohne Hugging Face-Konto, plus wortgenaue Zeitstempel und
  Zuschnitt von Zeitbereichen.
- **Unterbrochene Aufträge werden fortgesetzt** ab ihrem letzten Speicherpunkt, anstatt von vorne
  zu beginnen (Standard-Engine).
- **Online-Videos:** Herunterladen von jeder Seite, die [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  unterstützt, und transkribieren, sobald der Download abgeschlossen ist.
- **Link zum untertitelten Video:** Ein Häkchen verwandelt einen Link in `<title>-subbed.mp4`
  mit eingebrannten Untertiteln: Herunterladen, Transkribieren und Einbrennen in einem Warteschlangen-Auftrag
  ([docs/SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Live:** Transkribieren Sie ein Mikrofon oder den Systemton unter Windows, während es
  passiert ([docs/LIVE.md](../LIVE.md)).
- **Stapel-Warteschlange und überwachter Ordner** für viele Dateien.
- **Lokaler Netzwerkmodus:** Eine Transkriptionsseite und eine OpenAI-kompatible API für
  die anderen Geräte in Ihrem Netzwerk ([docs/SERVER.md](../SERVER.md)).
- **Optional, standardmäßig aus:** KI-Werkzeuge für ein fertiges Transkript (Zusammenfassung,
  Fragen, zweisprachiges SRT) und Offline-Text-zu-Sprache mit Stimmenklonen.

Wie es sich im Vergleich zu Subtitle Edit, Vibe, Buzz, noScribe und aTrain schlägt,
einschließlich der Fälle, in denen eine andere App die bessere Wahl ist:
**[docs/COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Download

Aktuelle Version: **[Releases-Seite](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| Datei | Für |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 oder 11, 64-Bit. Die meisten Nutzer benötigen diese. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows ohne Installation: Entpacken und starten. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Macs mit Apple Silicon, macOS 14 oder neuer. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Intel-Macs, macOS 10.15 oder neuer. |

Linux läuft aus dem Quellcode: [platform/linux/README.md](../../platform/linux/README.md).

Das mitgelieferte FFmpeg ist ein GPL-Build. Der dazugehörige Quellcode ist an jedem Release als
`WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*`-Dateien angehängt; die genauen Links finden Sie in
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

ffmpeg und yt-dlp sind enthalten. Beim ersten Start wählen Sie in einem Schnellstart-Fenster
das Sprachmodell für Ihre Sprache: Fast (Small, ca. 500 MB) oder Best
quality (bis zu ca. 3 GB); es wird einmalig bei der ersten Nutzung heruntergeladen. Planen Sie 8 GB
RAM ein; auf einer CPU benötigen die Large-Modelle etwa die 1.5- bis 2.5-fache Dauer der
Audiodatei, Small etwa die Hälfte. Eine NVIDIA-GPU ist deutlich schneller. Die Windows-Builds sind nicht signiert und die Mac-Builds nicht
notarisiert, weshalb SmartScreen und Gatekeeper beim ersten Start warnen;
[docs/INSTALL.md](../INSTALL.md) zeigt, was anzuklicken ist. Für ein Update führen Sie einfach das
neue Installationsprogramm über dem alten aus; Einstellungen bleiben erhalten.

**Downloads nach Version** (jedes Badge zählt nur das eigene Release der jeweiligen Version — ältere Versionen bleiben veröffentlicht und ihre Zähler werden nie zurückgesetzt):

[![v2.1.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.1.0/total?label=v2.1.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.1.0)
[![v2.0.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.0.0/total?label=v2.0.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0)
[![v1.9.3](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.3/total?label=v1.9.3&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.3)
[![v1.9.1](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.1/total?label=v1.9.1&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.1)
[![v1.9.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.0/total?label=v1.9.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.0)
[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

## Was Ihren Computer verlässt

Mit den Standardeinstellungen bleiben Ihre Audiodaten und Transkripte auf Ihrem Computer.
Die App nutzt das Netzwerk für:

- das Herunterladen eines Modells oder einer optionalen Komponente, wenn diese zum ersten Mal benötigt wird;
- ihre Online-Einstellungen beim Start und eine tägliche Update-Prüfung auf GitHub, die
  Ihnen nur mitteilt, ob eine neue Version vorliegt;
- Nutzungsstatistiken, standardmäßig aktiviert, nach jeder abgeschlossenen Transkription: Modell,
  Sprache, Dauer, Wortanzahl, App-Version, Betriebssystem, CPU und
  Speichergröße sowie Region, aber niemals den Dateinamen. Schalten Sie diese unter
  **Help → Usage statistics** ab.

Audio- oder Transkripttexte werden nur gesendet, wenn Sie eine Cloud-Engine (Gemini API
oder Google Cloud Speech-to-Text) auswählen oder selbst einen entfernten KI-Anbieter anbinden.
**File → Work offline** stoppt all dies. Jede Verbindung ist in
[docs/CONFIG.md](../CONFIG.md#network-use) aufgelistet.

## Dokumentation

[Installation](../INSTALL.md) · [Konfiguration](../CONFIG.md) ·
[Live-Transkription](../LIVE.md) · [Lokaler Netzwerkmodus und API](../SERVER.md) ·
[Cloud-Engines](../CLOUD_STT.md) · [Architektur](../ARCHITECTURE.md) ·
[Changelog](../CHANGELOG.md) · [Alle Dokumente](../README.md)

## Aus dem Quellcode kompilieren

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Benötigt Python 3.11 oder neuer. Build-Pipelines: [docs/BUILD.md](../BUILD.md). Tests und Pull-Requests:
[CONTRIBUTING.md](../../CONTRIBUTING.md).

## Mitwirken und Kontakt

- **Bugs und Funktionsanfragen:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Fragen und Ideen:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Alles andere:** per E-Mail, über den
  [Kontaktbereich der Website](https://whisper-transcriber-suite.pages.dev/#contact)
- **Sicherheitsberichte:** [SECURITY.md](../../SECURITY.md)

Dieses Projekt befolgt den [Contributor Covenant](../../.github/CODE_OF_CONDUCT.md).
Wenn die App Ihnen Zeit spart, hilft ein Stern oben auf dieser Seite anderen Leuten,
sie zu finden.

## Wie dieses Projekt entsteht

Der Maintainer entwickelt es mit starker Unterstützung von KI-Programmierassistenten (hauptsächlich Claude). Typprüfungen
und die Unit-Tests müssen vor jedem Commit erfolgreich durchlaufen, und die CI führt sie nach
jedem Push auf Windows und Linux erneut aus. Die [Release-Checkliste](../RELEASE_PROCESS.md) enthält einen manuellen Installationstest auf einem
echten Rechner. Commits, die mit KI-Hilfe erstellt wurden, nennen das Modell nun in einer `Assisted-by:`-Zeile; viele ältere
tragen stattdessen eine `Co-Authored-By: Claude`-Zeile.

## Lizenz

Copyright (c) 2026 translation-robot (Co-Autor). Das Projekt befindet sich in diesem Repository,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
Der eigene Quellcode des Projekts steht unter der [BSD 3-Clause License](../../LICENSE). Mitgelieferte
Tools, die Python-Laufzeitumgebung und die Modelle behalten ihre eigenen Lizenzen; siehe
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
