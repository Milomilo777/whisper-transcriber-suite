<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**Transcripción y subtítulos gratuitos y sin conexión para grabaciones largas en su idioma — en una computadora portátil común, sin cuenta y sin subir el audio.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Descargar para Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS y Linux: consulte [Descargar](#download).

<!-- language-links:start -->

<p>
<a href="../../README.md">English</a> ·
<a href="README.de.md">Deutsch</a> ·
<a href="README.fr.md">Français</a> ·
<b>Español</b> ·
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

## Para quién es

Subtituladores, traductores, investigadores y periodistas que convierten
grabaciones largas (entrevistas, conferencias, charlas, videos) en texto o subtítulos.
Arrastre un archivo de audio o video y la transcripción se escribirá junto a él. El motor de voz se ejecuta en su propia computadora, por lo que no hay
costos por minuto y, una vez descargado el modelo, no se requiere conexión
a Internet.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="La pestaña Transcribe: una zona para soltar archivos, selectores de motor e idioma, y opciones de etiquetas de hablante y marcas de tiempo por palabra" width="80%">
</div>

## Novedades en 2.0

- **Velocidad y tiempo restante:** la pestaña "Queue" muestra la velocidad de cada trabajo y un tiempo restante aproximado.
- **Video subtitulado desde un enlace:** descargue, transcriba y grabe los subtítulos como un solo trabajo ([docs/SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Transcripción como página web:** un archivo `.html` con búsqueda y reproducción al hacer clic que funciona sin conexión en cualquier navegador.
- **Trabajo sin conexión verificable:** con "Work offline" activado, una línea de estado muestra si la aplicación o un proceso iniciado por ella tiene conexión a la red.
- **Traducir al inglés:** la voz en otro idioma se convierte en subtítulos en inglés en un solo paso.
- **Inicio rápido:** las nuevas instalaciones hacen tres preguntas, y un clip de muestra de 18 segundos muestra un resultado al instante.
- **Reportar un problema** desde el menú Help, sin necesidad de una cuenta de GitHub.
- **macOS:** menú de la aplicación con Settings (Comando-coma), modo claro y oscuro que sigue al sistema, notificaciones. **Windows:** progreso en la barra de tareas y barras de título oscuras.

Lista completa: [CHANGELOG](../CHANGELOG.md).

## Funciones

- **Motores locales:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (predeterminado), whisper.cpp y NVIDIA Parakeet, para los muchos idiomas que Whisper
  reconoce. Usa una GPU NVIDIA
  a través de CUDA cuando es posible, de lo contrario la CPU.
- **La aplicación en su idioma:** Menús, botones y mensajes en 42 idiomas
  (traducidos automáticamente y marcados como tales; se agradecen las correcciones).
  Sigue el idioma de su sistema, o puede elegir uno en Configuración avanzada. Por
  ahora, el persa, el árabe y el hebreo se ofrecen en Windows.
- **14 formatos de salida:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX y
  PDF, además de los formatos oTranscribe, ELAN, InqScribe y Express Scribe. DOCX
  y PDF dibujan cada escritura correctamente, y el persa, árabe y urdu se leen de derecha a izquierda
  con letras unidas.
- **Página web para compartir:** guarde una transcripción terminada como un archivo `.html` que
  funciona sin conexión en cualquier navegador; haga clic en una palabra para escucharla, busque, salte a
  los capítulos.
- **Etiquetas de hablantes** sin una cuenta de Hugging Face, además de marcas de tiempo precisas por palabra y
  recorte de rango de tiempo.
- **Los trabajos interrumpidos se reanudan** desde su último punto de control en lugar de comenzar
  de nuevo (motor predeterminado).
- **Videos en línea:** descargue de cualquier sitio que [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  admita y transcriba cuando finalice la descarga.
- **Enlace a video subtitulado:** una sola marca convierte un enlace en `<title>-subbed.mp4`
  con los subtítulos grabados: descargue, transcriba y grabe en un trabajo en cola
  ([docs/SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **En vivo:** transcriba un micrófono, o el audio del sistema en Windows, mientras
  sucede ([docs/LIVE.md](../LIVE.md)).
- **Cola por lotes y carpeta vigilada** para muchos archivos.
- **Modo de red local:** una página de transcripción y una API compatible con OpenAI para
  los otros dispositivos de su red ([docs/SERVER.md](../SERVER.md)).
- **Opcional, desactivado por defecto:** herramientas de IA para una transcripción terminada (resumen,
  preguntas, SRT bilingüe), y texto a voz sin conexión con clonación de voz.

Cómo se compara con Subtitle Edit, Vibe, Buzz, noScribe y aTrain,
incluyendo cuándo es mejor usar otra aplicación:
**[docs/COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Descargar

Última versión: **[página de releases](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| Archivo | Para |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 u 11, 64 bits. La mayoría de la gente necesita este. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows sin instalación: descomprimir y ejecutar. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Macs con Apple Silicon, macOS 14 o más reciente. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Macs con Intel, macOS 10.15 o más reciente. |

Linux se ejecuta desde el código fuente: [platform/linux/README.md](../../platform/linux/README.md).

El FFmpeg incluido es una compilación GPL. Su código fuente correspondiente se adjunta a cada versión como
archivos `WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*`; los enlaces exactos están en
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

ffmpeg y yt-dlp están incluidos. En el primer inicio, una ventana de inicio rápido elige
el modelo de voz para su idioma: Rápido (Small, aprox. 500 MB) o Mejor
calidad (hasta aprox. 3 GB); se descarga una vez, en el primer uso. Considere tener unos 8 GB
de RAM; en una CPU, los modelos Large toman de 1.5 a 2.5 veces la duración del
audio y Small aproximadamente la mitad. Una GPU NVIDIA es mucho más rápida. Las compilaciones de Windows no están firmadas digitalmente y las de Mac no están
notariadas, por lo que SmartScreen y Gatekeeper emitirán una advertencia en el primer inicio;
[docs/INSTALL.md](../INSTALL.md) muestra dónde debe hacer clic. Para actualizar, ejecute el
nuevo instalador sobre el anterior; su configuración se mantendrá.

**Descargas por versión** (cada insignia cuenta únicamente el lanzamiento de esa versión — las versiones anteriores siguen publicadas y sus conteos nunca se reinician):

[![v2.1.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.1.0/total?label=v2.1.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.1.0)
[![v2.0.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.0.0/total?label=v2.0.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0)
[![v1.9.3](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.3/total?label=v1.9.3&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.3)
[![v1.9.1](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.1/total?label=v1.9.1&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.1)
[![v1.9.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.0/total?label=v1.9.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.0)
[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

## Qué sale de su computadora

Con la configuración predeterminada, su audio y sus transcripciones se quedan en su computadora.
La aplicación usa la red para:

- descargar un modelo o un componente opcional la primera vez que se necesita;
- su configuración en línea al inicio y una verificación de actualización diaria en GitHub, que
  solo le avisa de una nueva versión;
- estadísticas de uso, activadas por defecto, después de cada transcripción finalizada: modelo,
  idioma, duraciones, recuento de palabras, versión de la aplicación, sistema operativo, CPU y
  tamaño de la memoria, y región, nunca el nombre del archivo. Desactívelas en
  **Help → Usage statistics**.

El audio o el texto de la transcripción se envían únicamente si elige un motor en la nube (Gemini API
o Google Cloud Speech-to-Text) o conecta un proveedor de IA remoto usted mismo.
**File → Work offline** detiene todo esto. Cada conexión se detalla en
[docs/CONFIG.md](../CONFIG.md#network-use).

## Documentación

[Instalación](../INSTALL.md) · [Configuración](../CONFIG.md) ·
[Transcripción en vivo](../LIVE.md) · [Modo red local y API](../SERVER.md) ·
[Motores en la nube](../CLOUD_STT.md) · [Arquitectura](../ARCHITECTURE.md) ·
[Changelog](../CHANGELOG.md) · [Todos los documentos](../README.md)

## Construir desde el código fuente

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Requiere Python 3.11 o más reciente. Tuberías de construcción: [docs/BUILD.md](../BUILD.md). Pruebas y solicitudes de extracción (pull requests):
[CONTRIBUTING.md](../../CONTRIBUTING.md).

## Contribuir y contacto

- **Errores y solicitudes de funciones:** [Problemas en GitHub](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Preguntas e ideas:** [Discusiones en GitHub](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Todo lo demás:** por correo electrónico, a través de la
  [sección de contacto de la página web](https://whisper-transcriber-suite.com/#contact)
- **Informes de seguridad:** [SECURITY.md](../../SECURITY.md)

Este proyecto sigue el [Pacto del Colaborador (Contributor Covenant)](../../.github/CODE_OF_CONDUCT.md).
Si la aplicación le ahorra tiempo, una estrella en la parte superior de esta página ayuda a que
otras personas la encuentren.

## Cómo se construye este proyecto

El responsable lo desarrolla con una gran ayuda de asistentes de programación de IA (principalmente Claude). Las comprobaciones de tipo
y las pruebas unitarias deben aprobarse antes de cada envío (commit), y la integración continua (CI) vuelve a ejecutarlas en Windows y Linux después
de cada inserción (push). La [lista de verificación de lanzamientos](../RELEASE_PROCESS.md) incluye una prueba de instalación manual en un
equipo real. Los envíos realizados con ayuda de IA ahora nombran el modelo en una línea `Assisted-by:`; muchos de los más antiguos
llevan una línea `Co-Authored-By: Claude` en su lugar.

## Licencia

Copyright (c) 2026 translation-robot (coautor). El proyecto vive en este repositorio,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
El propio código fuente del proyecto se rige por la [Licencia BSD de 3 cláusulas](../../LICENSE). Las herramientas
incorporadas, el entorno de ejecución de Python y los modelos mantienen sus propias licencias; véase
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
