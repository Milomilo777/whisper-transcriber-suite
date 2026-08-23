<div align="center">

<img src="../img/hero.png" alt="Whisper Project" width="100%">

# Whisper Project

### Audio- oder Videodatei hineinziehen. Heraus kommt ein **zeitcodiertes, formatiertes Transkript** — ohne dass die Datei je den Rechner verlässt.

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![downloads](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/total?color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases)
[![License: BSD-3](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)
[![Stars](https://img.shields.io/github/stars/Milomilo777/whisper-transcriber-suite?style=flat&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/stargazers)

### [⬇  Für Windows herunterladen](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

<p>
  <a href="../../README.md"><img src="https://flagcdn.com/16x12/us.png" alt="" width="16" height="12"> English</a> ∙
  <a href="README.zh-CN.md"><img src="https://flagcdn.com/16x12/cn.png" alt="" width="16" height="12"> 简体中文</a> ∙
  <a href="README.ja.md"><img src="https://flagcdn.com/16x12/jp.png" alt="" width="16" height="12"> 日本語</a> ∙
  <a href="README.ko.md"><img src="https://flagcdn.com/16x12/kr.png" alt="" width="16" height="12"> 한국어</a> ∙
  <img src="https://flagcdn.com/16x12/de.png" alt="" width="16" height="12">
  <b>Deutsch</b> ∙
  <a href="README.es.md"><img src="https://flagcdn.com/16x12/es.png" alt="" width="16" height="12"> Español</a> ∙
  <a href="README.fr.md"><img src="https://flagcdn.com/16x12/fr.png" alt="" width="16" height="12"> Français</a> ∙
  <a href="README.pt.md"><img src="https://flagcdn.com/16x12/pt.png" alt="" width="16" height="12"> Português</a> ∙
  <a href="README.fa.md"><img src="https://flagcdn.com/16x12/ir.png" alt="" width="16" height="12"> فارسی</a>
</p>

</div>

---

Eine Desktop-Anwendung, die OpenAI's Whisper-Modell **lokal** ausführt — über [faster-whisper](https://github.com/SYSTRAN/faster-whisper). Dadurch kostet die Transkription nichts pro Minute, funktioniert im Flugzeug und lädt Ihre Aufnahme niemals irgendwohin hoch. Datei hineinziehen, und `.srt`, `.vtt`, `.txt`, `.json`, `.docx`, `.pdf` und mehr landen direkt neben dem Original. Außerdem lädt sie von jeder Seite herunter, die `yt-dlp` unterstützt, erkennt Sprecher, arbeitet eine Warteschlange ab und kann sich in eine Transkriptionsseite für die anderen Geräte im Netzwerk verwandeln.

Kein Konto. Kein API-Schlüssel. Kein Abonnement. Ihre Dateien bleiben auf Ihrer Festplatte.

- 🔒 **Läuft auf Ihrem Rechner** — standardmäßig faster-whisper (CTranslate2), dazu whisper.cpp und NVIDIA Parakeet
- 📝 **14 Ausgabeformate** — `srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf`, dazu oTranscribe / ELAN / InqScribe / Express Scribe
- 🎙️ **Live-Transkription** — Mikrofon oder Systemton, während gesprochen wird → [LIVE.md](../LIVE.md)
- 🗣️ **Sprecherkennung** — offline, dazu wortgenaue Zeitstempel und Zeitbereichs-Zuschnitt
- 🎬 **Downloads** — alles, was `yt-dlp` kann, auf Wunsch mit Transkription direkt danach
- 🧹 **Adaptive Rauschreduktion** — misst das Audio und bereinigt nur, wenn das hilft → [DENOISE.md](../DENOISE.md)
- 🌐 **Lokaler Netzwerkmodus** — dieser Rechner wird zur Transkriptionsseite für Ihre anderen Geräte
- 💸 **Kostenlos und BSD-3-lizenziert** — keine Minutenkosten, kein Abo, standardmäßig keine Telemetrie

## Download

Die aktuelle Version gibt es auf der **[Releases-Seite](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**:

| Datei | Größe | Geeignet für |
|---|---|---|
| **`WhisperProject-…-Setup-Standard.exe`** | ~215 MB | **Die meisten Nutzer.** Ein normales Installationsprogramm: Startmenü-Verknüpfung, Upgrade über eine ältere Version hinweg, Dateien sichtbar auf der Festplatte. |
| **`WhisperProject-…-Portable.zip`** | ~330 MB | Entpacken und starten. Keine Installation, keine Administratorrechte, läuft auch vom USB-Stick. |
| **`WhisperProject-…-macOS-*.dmg`** | ~400 MB | macOS (x64 und arm64 werden getrennt veröffentlicht). |

Alles Nötige ist enthalten — ein mitgeliefertes Python, `ffmpeg`, `ffprobe` und `yt-dlp`. Nachgeladen wird einzig das Sprachmodell selbst (**ca. 1–3 GB, einmalig** beim ersten Start); danach arbeitet die Anwendung vollständig offline.

## Funktionen

<div align="center">

<img src="../img/features.png" alt="" width="100%">

</div>

| | |
|---|---|
| **Lokale Transkription** | Standardmäßig Whisper `large-v3`, dazu `large-v3-turbo` und `distil-large-v3.5`. |
| **Viele Ausgabeformate** | `srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf` — direkt neben der Eingabedatei. |
| **Live-Transkription** | Transkribiert ein Mikrofon — oder was dieser Rechner gerade abspielt — während es passiert. Geschnitten wird in natürlichen Pausen, damit keine Wörter zerteilt werden. |
| **Sprechertrennung** | Optionales „Sprecher erkennen“, dazu wortgenaue Zeitstempel und Zeitbereichs-Zuschnitt. |
| **Adaptive Rauschreduktion** | Misst jede Aufnahme zuerst und bereinigt nur, wenn die Messung das nahelegt; prüft das eigene Ergebnis und verwirft es, wenn Sprache entfernt wurde. |
| **Stapelverarbeitung** | Live-Status für jeden wartenden und laufenden Auftrag, mit **Pause / Fortsetzen / Abbrechen / Erneut / Entfernen** stets einen Klick entfernt. |
| **Downloads** | Alles, was `yt-dlp` beherrscht, dazu Supreme-Master-TV-Folgenlinks. Downloads werden fortgesetzt statt neu begonnen. |
| **Lokaler Netzwerkmodus** | Ein Webserver nur aus der Standardbibliothek, damit andere Geräte über diesen Rechner transkribieren — optionales Passwort, aus bis Sie ihn starten. |

## Funktionsweise

<div align="center">

<img src="../img/how-it-works.png" alt="" width="100%">

</div>

Die Tk-Oberfläche läuft im Hauptprozess. Jeder Transkriptionsauftrag läuft in einem langlebigen Worker-Subprozess, der das Whisper-Modell im Speicher hält und über zeilengetrenntes JSON auf stdin/stdout zurückspricht; `yt-dlp` bekommt pro Download einen eigenen Subprozess. Ein UUID-Token je Worker und ein 5-Sekunden-Heartbeat halten diese Zuordnung robust gegen wiederverwendete Prozess-IDs und lassen die Oberfläche einen hängenden Worker erkennen, statt mit ihm zu hängen.

## Standardmäßig offline

Alle Standard-Backends laufen auf Ihrem Rechner. Nichts wird hochgeladen, es gibt kein Konto, und nach dem Herunterladen des Modells funktioniert die Anwendung auch ohne Netzwerk.

> [!IMPORTANT]
> Zwei Backends, die Sie **ausdrücklich auswählen müssen**, durchbrechen diese Garantie. Sie sind aus, solange Sie sie nicht unter **Advanced → Backend** wählen. Nutzen Sie sie nur für Inhalte, die Sie an Dritte senden möchten.
>
> - **`cloud_stt`** — Google Gemini API → [CLOUD_STT.md](../CLOUD_STT.md)
> - **`google_cloud_stt`** — Google Cloud Speech-to-Text → [CLOUD_STT_GOOGLE.md](../CLOUD_STT_GOOGLE.md)

## Aus dem Quellcode bauen

```bash
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

## Dokumentation

| Dokument | Inhalt |
|---|---|
| [INSTALL.md](../INSTALL.md) | Installation und Fehlerbehebung |
| [LIVE.md](../LIVE.md) | Der Live-Tab |
| [DENOISE.md](../DENOISE.md) | Adaptive Rauschreduktion |
| [SERVER.md](../SERVER.md) | Lokaler Netzwerk-/Webserver-Modus |
| [CONFIG.md](../CONFIG.md) | Alle Konfigurationsschlüssel |
| [BUILD.md](../BUILD.md) | Selbst bauen |
| [CHANGELOG.md](../CHANGELOG.md) | Versionsverlauf |

> Die vollständige Dokumentation ist auf Englisch. Diese Seite ist eine Übersicht; Details finden Sie in den englischen Dokumenten.

## Lizenz

Der eigene Quellcode dieses Projekts steht unter der **BSD-3-Clause-Lizenz** — siehe [LICENSE](../../LICENSE). Die mitgelieferten Binärdateien (`ffmpeg`, `ffprobe`, `yt-dlp`), die mitgelieferte Python-Laufzeitumgebung samt Paketen und das Whisper-Modell selbst behalten ihre eigenen Lizenzen; [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) fasst sie zusammen.

---

<div align="center">
<sub>Offline-Spracherkennung · lokale Whisper-Oberfläche · Untertitel-Generator · Sprechertrennung · Windows · macOS</sub>
</div>
