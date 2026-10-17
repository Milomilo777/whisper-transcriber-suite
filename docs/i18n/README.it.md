<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**Trascrizione e sottotitoli offline e gratuiti per lunghe registrazioni nella tua lingua — su un computer portatile standard, senza account e senza caricare l'audio online.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Scarica per Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS e Linux: vedi [Download](#download).

<!-- language-links:start -->

<p>
<a href="../../README.md">English</a> ·
<a href="README.de.md">Deutsch</a> ·
<a href="README.fr.md">Français</a> ·
<a href="README.es.md">Español</a> ·
<b>Italiano</b> ·
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

</div>
<!-- translated from README.md at commit 66585d5 -->

## A chi si rivolge

Sottotitolatori, traduttori, ricercatori e giornalisti che trasformano lunghe
registrazioni (interviste, lezioni, discorsi, video) in testo o sottotitoli.
Trascina un file audio o video e la trascrizione verrà salvata accanto ad esso. Il motore vocale funziona sul tuo computer, per cui non ci sono
costi al minuto e, una volta scaricato il modello, non è necessaria alcuna
connessione a internet.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="La scheda Transcribe: un'area di rilascio, selettori di motore e lingua, opzioni per le etichette dei parlanti e i timestamp delle parole" width="80%">
</div>

## Novità della versione 2.0

- **Velocità e tempo rimanente:** la scheda Queue mostra la velocità di ciascun processo e una stima del tempo rimanente.
- **Video sottotitolato da un link:** scarica, trascrivi e integra i sottotitoli nel video in un'unica operazione ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Trascrizione come pagina web:** un unico file `.html` con ricerca e riproduzione al clic (click-to-play) che funziona offline in qualsiasi browser.
- **Lavoro offline verificabile:** con l'opzione Work offline attiva, una barra di stato indica se l'applicazione, o un processo da essa avviato, ha una connessione di rete.
- **Traduci in inglese:** il parlato non in inglese diventa sottotitoli in inglese in un solo passaggio.
- **Avvio rapido:** le nuove installazioni pongono tre domande, e una clip di prova di 18 secondi mostra immediatamente un risultato.
- **Segnala un problema** (Report a problem) da Help, senza bisogno di un account GitHub.
- **macOS:** menu dell'app con Settings (Command-virgola), tema Light e Dark che segue il sistema, notifiche. **Windows:** progresso nella barra delle applicazioni e barre del titolo scure.

Elenco completo: [CHANGELOG](../CHANGELOG.md).

## Funzionalità

- **Motori locali:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (predefinito), whisper.cpp e NVIDIA Parakeet, per le numerose lingue che Whisper
  riconosce. Utilizza una GPU NVIDIA
  tramite CUDA quando possibile, altrimenti la CPU.
- **L'app nella tua lingua:** Menu, pulsanti e messaggi in 42 lingue (tradotti
  automaticamente e indicati come tali; le correzioni sono benvenute). Segue la
  lingua del tuo sistema, oppure puoi sceglierne una nelle Impostazioni avanzate.
  Per ora persiano, arabo ed ebraico sono disponibili su Windows.
- **14 formati di output:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX e
  PDF, oltre ai formati per oTranscribe, ELAN, InqScribe ed Express Scribe. DOCX
  e PDF supportano ogni sistema di scrittura, e il persiano, l'arabo e l'urdu si leggono da destra a sinistra
  con caratteri legati.
- **Pagina web condivisibile:** salva una trascrizione completata come un unico file `.html` che
  funziona offline in qualsiasi browser; clicca su una parola per ascoltarla, cerca nel testo o salta ai
  capitoli.
- **Etichette dei parlanti (Speaker labels)** senza un account Hugging Face, più timestamp per parola e
  ritaglio di un intervallo di tempo.
- **I lavori interrotti riprendono** dal loro ultimo punto di salvataggio invece di ricominciare
  dall'inizio (motore predefinito).
- **Video online:** scarica da qualsiasi sito supportato da [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  e trascrivi non appena il download è completato.
- **Link a video sottotitolato:** una spunta trasforma un link in `<title>-subbed.mp4`
  con i sottotitoli impressi nel video: scarica, trascrivi e integra in un solo lavoro in coda
  ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Live:** trascrivi un microfono, o l'audio di sistema su Windows, in tempo
  reale ([../LIVE.md](../LIVE.md)).
- **Coda batch e cartella monitorata** per gestire molti file.
- **Modalità rete locale:** una pagina di trascrizione e un'API compatibile con OpenAI per
  gli altri dispositivi sulla tua rete ([../SERVER.md](../SERVER.md)).
- **Opzionali, disattivati per impostazione predefinita:** strumenti IA per una trascrizione completata (riassunto,
  domande, SRT bilingue) e sintesi vocale (text-to-voice) offline con clonazione della voce.

Come si confronta con Subtitle Edit, Vibe, Buzz, noScribe e aTrain,
inclusi i casi in cui un'altra app potrebbe essere la scelta migliore:
**[../COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Download

Versione più recente: **[pagina delle release (releases page)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| File | Per chi è |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 o 11, 64-bit. La maggior parte degli utenti dovrebbe scegliere questo. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows senza installazione: decomprimi ed esegui. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Mac con processori Apple Silicon, macOS 14 o successivo. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Mac Intel, macOS 10.15 o successivo. |

Su Linux l'esecuzione avviene dal codice sorgente: [../../platform/linux/README.md](../../platform/linux/README.md).

L'FFmpeg integrato è una build GPL. Il relativo codice sorgente è allegato a ciascuna release come
file `WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*`; i link esatti si trovano in
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

ffmpeg e yt-dlp sono inclusi. Al primo avvio, una finestra di configurazione rapida ti fa scegliere
il modello vocale per la tua lingua: Fast (Small, circa 500 MB) o Best
quality (fino a circa 3 GB); si scarica una sola volta, al primo utilizzo. Sono consigliati 8 GB
di RAM; su una CPU i modelli Large impiegano circa 1.5–2.5 volte la durata
dell'audio e i modelli Small circa la metà; una GPU NVIDIA è molto più veloce. Le build per Windows non sono firmate digitalmente e le build per Mac non sono
autenticate, per cui SmartScreen e Gatekeeper mostreranno un avviso al primo avvio;
[../INSTALL.md](../INSTALL.md) spiega cosa cliccare. Per aggiornare, basta eseguire il
nuovo programma di installazione sopra a quello vecchio; le impostazioni verranno mantenute.

**Download per versione** (ogni badge conteggia solo la specifica
versione — le versioni precedenti rimangono pubblicate e i loro conteggi non vengono mai
azzerati):

[![v2.1.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.1.0/total?label=v2.1.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.1.0)
[![v2.0.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.0.0/total?label=v2.0.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0)
[![v1.9.3](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.3/total?label=v1.9.3&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.3)
[![v1.9.1](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.1/total?label=v1.9.1&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.1)
[![v1.9.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.0/total?label=v1.9.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.0)
[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

## Cosa lascia il tuo computer

Con le impostazioni predefinite l'audio e le trascrizioni rimangono sul tuo computer.
L'app utilizza la rete per:

- scaricare un modello o un componente opzionale la prima volta che è necessario;
- le impostazioni online all'avvio e per un controllo quotidiano degli aggiornamenti su GitHub, che
  serve unicamente ad avvisarti della presenza di una nuova versione;
- statistiche di utilizzo, attive per impostazione predefinita, dopo ogni trascrizione completata: modello,
  lingua, durata, conteggio delle parole, versione dell'app, sistema operativo, CPU e
  dimensione della memoria e area geografica, ma mai il nome del file. Puoi disattivarle in
  **Help → Usage statistics**.

L'audio o il testo della trascrizione vengono inviati solo se scegli un motore cloud (Gemini API
o Google Cloud Speech-to-Text) o se colleghi un fornitore di IA remoto.
L'opzione **File → Work offline** blocca del tutto queste connessioni. Tutte le connessioni sono elencate in
[../CONFIG.md](../CONFIG.md#network-use).

## Documentazione

[Installazione (Install)](../INSTALL.md) · [Configurazione (Configuration)](../CONFIG.md) ·
[Trascrizione in tempo reale (Live transcription)](../LIVE.md) · [Modalità rete locale e API (Local-network mode and API)](../SERVER.md) ·
[Motori cloud (Cloud engines)](../CLOUD_STT.md) · [Architettura (Architecture)](../ARCHITECTURE.md) ·
[Changelog](../CHANGELOG.md) · [Tutta la documentazione (All docs)](../README.md)

## Compilazione dal codice sorgente

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Richiede Python 3.11 o versioni successive. Pipeline di compilazione: [../BUILD.md](../BUILD.md). Test e pull request:
[../../CONTRIBUTING.md](../../CONTRIBUTING.md).

## Contributi e contatti

- **Segnalazioni di bug e richieste di funzionalità:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Domande e idee:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Tutto il resto:** via email, tramite la
  [sezione Contact del sito web](https://whisper-transcriber-suite.pages.dev/#contact)
- **Segnalazioni di sicurezza:** [../../SECURITY.md](../../SECURITY.md)

Questo progetto segue il [Contributor Covenant](../../.github/CODE_OF_CONDUCT.md).
Se l'app ti fa risparmiare tempo, una Stella (Star) in cima a questa pagina aiuta le altre persone a
trovarla.

## Come viene sviluppato questo progetto

Il manutentore sviluppa questo software con un forte aiuto da parte di assistenti IA alla programmazione (principalmente Claude). I controlli sui tipi
e gli unit test devono passare prima di ogni commit, e la CI li esegue nuovamente su Windows e Linux dopo
ogni push. La [checklist di rilascio](../RELEASE_PROCESS.md) include un test manuale di installazione su una
macchina reale. I commit realizzati con l'aiuto dell'IA riportano ora il nome del modello in una riga `Assisted-by:`; molti
di quelli più vecchi contengono invece la riga `Co-Authored-By: Claude`.

## Licenza

Copyright (c) 2026 translation-robot (co-author). Il progetto è ospitato in questa repository,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
Il codice sorgente di questo progetto è rilasciato sotto licenza [BSD 3-Clause License](../../LICENSE). Gli
strumenti integrati, il runtime di Python e i modelli mantengono le proprie licenze; vedi
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
