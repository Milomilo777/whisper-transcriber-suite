<div align="center">

<img src="../img/hero.png" alt="Whisper Project" width="100%">

# Whisper Project

### Arrastre un archivo de audio o vídeo. Obtenga una **transcripción con marcas de tiempo y formato** — sin que el archivo salga nunca de su ordenador.

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![downloads](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/total?color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases)
[![License: BSD-3](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)
[![Stars](https://img.shields.io/github/stars/Milomilo777/whisper-transcriber-suite?style=flat&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/stargazers)

### [⬇  Descargar para Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

<p>
  <a href="../../README.md"><img src="https://flagcdn.com/16x12/us.png" alt="" width="16" height="12"> English</a> ∙
  <a href="README.zh-CN.md"><img src="https://flagcdn.com/16x12/cn.png" alt="" width="16" height="12"> 简体中文</a> ∙
  <a href="README.ja.md"><img src="https://flagcdn.com/16x12/jp.png" alt="" width="16" height="12"> 日本語</a> ∙
  <a href="README.ko.md"><img src="https://flagcdn.com/16x12/kr.png" alt="" width="16" height="12"> 한국어</a> ∙
  <a href="README.de.md"><img src="https://flagcdn.com/16x12/de.png" alt="" width="16" height="12"> Deutsch</a> ∙
  <img src="https://flagcdn.com/16x12/es.png" alt="" width="16" height="12">
  <b>Español</b> ∙
  <a href="README.fr.md"><img src="https://flagcdn.com/16x12/fr.png" alt="" width="16" height="12"> Français</a> ∙
  <a href="README.pt.md"><img src="https://flagcdn.com/16x12/pt.png" alt="" width="16" height="12"> Português</a> ∙
  <a href="README.fa.md"><img src="https://flagcdn.com/16x12/ir.png" alt="" width="16" height="12"> فارسی</a>
</p>

</div>

---

Una aplicación de escritorio que ejecuta el modelo Whisper de OpenAI **en local**, mediante [faster-whisper](https://github.com/SYSTRAN/faster-whisper), de modo que transcribir no cuesta nada por minuto, funciona en un avión y nunca sube su grabación a ninguna parte. Suelte un archivo y escribirá `.srt`, `.vtt`, `.txt`, `.json`, `.docx`, `.pdf` y más, junto al original. También descarga de cualquier sitio compatible con `yt-dlp`, identifica a los hablantes, procesa una cola de trabajos y puede convertirse en una página de transcripción para los demás dispositivos de su red.

Sin cuenta. Sin clave de API. Sin suscripción. Sus archivos permanecen en su disco.

- 🔒 **Se ejecuta en su equipo** — faster-whisper (CTranslate2) por defecto, además de whisper.cpp y NVIDIA Parakeet
- 📝 **14 formatos de salida** — `srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf`, más oTranscribe / ELAN / InqScribe / Express Scribe
- 🎙️ **Transcripción en directo** — micrófono o sonido del sistema, mientras se habla → [LIVE.md](../LIVE.md)
- 🗣️ **Etiquetas de hablante** — diarización sin conexión, marcas de tiempo por palabra y recorte por intervalos
- 🎬 **Descargas** — cualquier sitio compatible con `yt-dlp`, con transcripción automática al terminar si lo desea
- 🧹 **Reducción de ruido adaptativa** — mide el audio y solo lo limpia cuando eso ayuda → [DENOISE.md](../DENOISE.md)
- 🌐 **Modo de red local** — convierta este equipo en una página de transcripción para sus otros dispositivos
- 💸 **Gratis y con licencia BSD-3** — sin coste por minuto, sin suscripción, sin telemetría por defecto

## Descarga

Obtenga la última versión en la **[página de releases](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**:

| Archivo | Tamaño | Recomendado para |
|---|---|---|
| **`WhisperProject-…-Setup-Standard.exe`** | ~215 MB | **La mayoría de la gente.** Un instalador normal: acceso directo en el menú Inicio, actualiza sobre una versión anterior, archivos visibles en el disco. |
| **`WhisperProject-…-Portable.zip`** | ~330 MB | Descomprimir y ejecutar. Sin instalación, sin permisos de administrador, funciona desde una memoria USB. |
| **`WhisperProject-…-macOS-*.dmg`** | ~400 MB | macOS (x64 y arm64 se publican por separado). |

Todo lo necesario va incluido: un Python integrado, `ffmpeg`, `ffprobe` y `yt-dlp`. Lo único que se descarga después es el propio modelo de voz (**1–3 GB, una sola vez**, en el primer inicio); a partir de ahí la aplicación funciona totalmente sin conexión.

## Funciones

<div align="center">

<img src="../img/features.png" alt="" width="100%">

</div>

| | |
|---|---|
| **Transcripción local** | Whisper `large-v3` por defecto, además de `large-v3-turbo` y `distil-large-v3.5`. |
| **Muchos formatos de salida** | `srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf` — escritos junto al archivo de entrada. |
| **Transcripción en directo** | Transcribe un micrófono —o lo que este equipo esté reproduciendo— en el momento. Los cortes caen en pausas naturales, así que las palabras nunca se parten. |
| **Diarización de hablantes** | «Identificar hablantes» opcional, además de marcas de tiempo por palabra y recorte por intervalos. |
| **Reducción de ruido adaptativa** | Mide cada grabación antes de actuar y solo la limpia cuando la medición lo justifica; comprueba su propio resultado y lo descarta si ha eliminado voz. |
| **Cola por lotes** | Estado en vivo de cada trabajo pendiente y en curso, con **Pausar / Reanudar / Cancelar / Repetir / Quitar** siempre a un clic. |
| **Descargas** | Todo lo que maneja `yt-dlp`, más los enlaces de episodios de Supreme Master TV. Las descargas se reanudan en lugar de reiniciarse. |
| **Modo de red local** | Un servidor web hecho solo con la biblioteca estándar para que otros dispositivos transcriban a través de este equipo — contraseña opcional, apagado hasta que usted lo inicie. |

## Cómo funciona

<div align="center">

<img src="../img/how-it-works.png" alt="" width="100%">

</div>

La interfaz Tk se ejecuta en el proceso principal. Cada trabajo de transcripción corre en un subproceso de larga vida que mantiene el modelo Whisper en memoria y responde mediante JSON delimitado por saltos de línea en stdin/stdout; `yt-dlp` recibe su propio subproceso por descarga. Un token UUID por trabajador y un latido de 5 segundos hacen que ese enrutado resista la reutilización de identificadores de proceso y permiten a la interfaz detectar un trabajador bloqueado en lugar de bloquearse con él.

## Sin conexión por defecto

Todos los backends por defecto se ejecutan en su máquina. No se sube nada, no existe ninguna cuenta y, una vez descargado el modelo, la aplicación funciona con la red desconectada.

> [!IMPORTANT]
> Dos backends **opcionales** rompen esa garantía y ambos están desactivados salvo que entre en **Advanced → Backend** y los elija. Úselos solo con contenido que esté dispuesto a enviar a un tercero.
>
> - **`cloud_stt`** — Google Gemini API → [CLOUD_STT.md](../CLOUD_STT.md)
> - **`google_cloud_stt`** — Google Cloud Speech-to-Text → [CLOUD_STT_GOOGLE.md](../CLOUD_STT_GOOGLE.md)

## Compilar desde el código fuente

```bash
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

## Documentación

| Documento | Contenido |
|---|---|
| [INSTALL.md](../INSTALL.md) | Instalación y resolución de problemas |
| [LIVE.md](../LIVE.md) | La pestaña Live |
| [DENOISE.md](../DENOISE.md) | Reducción de ruido adaptativa |
| [SERVER.md](../SERVER.md) | Modo servidor web / red local |
| [CONFIG.md](../CONFIG.md) | Todas las claves de configuración |
| [BUILD.md](../BUILD.md) | Compilarlo usted mismo |
| [CHANGELOG.md](../CHANGELOG.md) | Historial de versiones |

> La documentación completa está en inglés. Esta página es un resumen; consulte los documentos en inglés para los detalles.

## Licencia

El código propio de este proyecto se publica bajo la **licencia BSD 3-Clause** — véase [LICENSE](../../LICENSE). Los binarios incluidos (`ffmpeg`, `ffprobe`, `yt-dlp`), el entorno de ejecución de Python y sus paquetes, y el propio modelo Whisper conservan sus licencias originales; [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) las resume.

---

<div align="center">
<sub>transcripción sin conexión · Whisper local con interfaz gráfica · generador de subtítulos · diarización · Windows · macOS</sub>
</div>
