<div align="center">

<img src="../img/hero.png" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**Transcripció i subtítols fora de línia i gratuïts per a enregistraments llargs en el teu idioma — en un ordinador portàtil normal, sense compte i sense pujar l'àudio a internet.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Baixa per a Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS i Linux: vegeu [Download](#download).

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
<b>Català</b> ·
<a href="README.bn.md">বাংলা</a> ·
<a href="README.fil.md">Filipino</a>
</p>

<!-- language-links:end -->

</div>
<!-- translated from README.md at commit 66585d5 -->

## Per a qui és

Subtituladors, traductors, investigadors i periodistes que transformen enregistraments
llargs (entrevistes, classes, conferències, vídeos) en text o subtítols.
Arrossega un fitxer d'àudio o vídeo i la transcripció es desarà al seu costat. El motor de veu funciona al teu propi ordinador, de manera que
no hi ha cap cost per minut i, un cop descarregat el model, no cal
connexió a internet.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="La pestanya Transcribe: una zona per deixar-hi fitxers, selectors de motor i d'idioma, opcions d'etiquetes de parlant i de marques de temps per paraula" width="80%">
</div>

## Novetats de la versió 2.0

- **Velocitat i temps restant:** la pestanya Queue mostra la velocitat de cada feina i una estimació del temps restant.
- **Vídeo subtitulat des d'un enllaç:** baixa, transcriu i integra els subtítols al vídeo en una única feina ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Transcripció com a pàgina web:** un sol fitxer `.html` amb cerca i reproducció al clic que funciona fora de línia a qualsevol navegador.
- **Treball fora de línia verificable:** amb l'opció Work offline activada, una barra d'estat mostra si l'aplicació o algun procés que hagi iniciat té connexió a la xarxa.
- **Tradueix a l'anglès:** la veu en altres idiomes es converteix en subtítols en anglès en un sol pas.
- **Inici ràpid:** les noves instal·lacions fan tres preguntes i un clip de mostra de 18 segons en mostra el resultat immediatament.
- **Informa d'un problema** (Report a problem) des de Help, sense necessitat de tenir compte a GitHub.
- **macOS:** menú de l'aplicació amb Settings (Command-coma), temes Light i Dark que segueixen el sistema, notificacions. **Windows:** progrés a la barra de tasques i barres de títol fosques.

Llista completa: [CHANGELOG](../CHANGELOG.md).

## Funcionalitats

- **Motors locals:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (per defecte), whisper.cpp i NVIDIA Parakeet, per als molts idiomes que Whisper
  reconeix. Utilitza una GPU NVIDIA
  mitjançant CUDA quan pot; si no, la CPU.
- **L'aplicació en el teu idioma:** Menús, botons i missatges en 42 idiomes
  (traduïts automàticament i marcats com a tals; les correccions són benvingudes).
  Segueix l'idioma del teu sistema, o en pots triar un a Configuració avançada. De
  moment, el persa, l'àrab i l'hebreu s'ofereixen a Windows.
- **14 formats de sortida:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX i
  PDF, a més dels formats oTranscribe, ELAN, InqScribe i Express Scribe. DOCX
  i PDF renderitzen qualsevol sistema d'escriptura, i el persa, l'àrab i l'urdú es llegeixen de dreta a esquerra
  amb caràcters lligats.
- **Pàgina web per compartir:** desa una transcripció acabada com a un únic fitxer `.html` que
  funciona fora de línia a qualsevol navegador; fes clic a una paraula per escoltar-la, cerca, o salta als
  capítols.
- **Etiquetes dels parlants (Speaker labels)** sense compte de Hugging Face, a més de marques de temps (timestamps) per paraula i
  retall d'interval de temps.
- **Les feines interrompudes es reprenen** des del darrer punt de control (checkpoint) en comptes de començar
  de nou (motor per defecte).
- **Vídeos en línia:** baixa des de qualsevol lloc web que [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  admeti i transcriu just quan acabi la descàrrega.
- **Enllaç a vídeo subtitulat:** una sola marca transforma un enllaç en `<title>-subbed.mp4`
  amb els subtítols integrats: baixa, transcriu i integra-ho tot en una sola feina a la cua
  ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **En directe (Live):** transcriu un micròfon, o l'àudio del sistema a Windows, en temps
  real ([../LIVE.md](../LIVE.md)).
- **Cua per lots i carpeta supervisada** per a processar molts fitxers.
- **Mode de xarxa local:** una pàgina de transcripció i una API compatible amb OpenAI per
  als altres dispositius de la teva xarxa ([../SERVER.md](../SERVER.md)).
- **Opcional, desactivat per defecte:** eines d'IA per a una transcripció acabada (resum,
  preguntes, SRT bilingüe), i conversió de text a veu fora de línia amb clonació de veu.

Com es compara amb Subtitle Edit, Vibe, Buzz, noScribe i aTrain,
incloent-hi quan una altra aplicació és la millor opció:
**[../COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Descàrrega

Darrer llançament: **[pàgina de llançaments (releases)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| Fitxer | Per a qui és |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 o 11, 64-bit. La majoria d'usuaris necessita aquest. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows sense instal·lar: descomprimeix i executa. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Macs amb Apple silicon, macOS 14 o més recent. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Macs Intel, macOS 10.15 o més recent. |

A Linux s'executa des del codi font: [../../platform/linux/README.md](../../platform/linux/README.md).

El FFmpeg inclòs és una compilació amb llicència GPL. El seu codi font corresponent s'adjunta a cada llançament com a
fitxers `WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*`; els enllaços exactes són a
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

ffmpeg i yt-dlp ja venen inclosos. A la primera execució, una finestra d'inici ràpid et fa triar
el model de veu per al teu idioma: Fast (Petit, uns 500 MB) o Best
quality (fins a uns 3 GB); es descarrega un sol cop, al primer ús. Pensa a tenir 8 GB
de RAM; en una CPU els models grans (Large) tarden entre 1,5 i 2,5 vegades la durada
de l'àudio i els petits (Small) aproximadament la meitat; una GPU NVIDIA és molt més ràpida. Les compilacions per a Windows no estan signades i les de Mac no estan
notaritzades, per la qual cosa SmartScreen i Gatekeeper mostraran un avís a la primera execució;
[../INSTALL.md](../INSTALL.md) mostra on has de fer clic. Per actualitzar, només cal executar el
nou instal·lador per sobre de l'antic; les opcions es mantindran.

**Descàrregues per versió** (cada insígnia compta només les d'aquesta
versió en concret — les versions anteriors segueixen publicades i els seus recomptes no es
reinicien mai):

[![v2.1.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.1.0/total?label=v2.1.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.1.0)
[![v2.0.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.0.0/total?label=v2.0.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0)
[![v1.9.3](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.3/total?label=v1.9.3&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.3)
[![v1.9.1](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.1/total?label=v1.9.1&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.1)
[![v1.9.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.0/total?label=v1.9.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.0)
[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

## Què surt del teu ordinador

Amb les opcions per defecte l'àudio i les transcripcions es queden al teu ordinador.
L'aplicació només fa servir la xarxa per a:

- descarregar un model o un component opcional el primer cop que es necessita;
- la configuració en línia a l'inici i una comprovació diària d'actualitzacions a GitHub, que
  només t'avisa si hi ha una versió nova;
- estadístiques d'ús, activades per defecte, després de cada transcripció acabada: model,
  idioma, durades, recompte de paraules, versió de l'aplicació, sistema operatiu, CPU i
  mida de memòria, a més de la regió, però mai el nom del fitxer. Pots desactivar-ho a
  **Help → Usage statistics**.

L'àudio o el text de la transcripció s'envien només si tries un motor al núvol (Gemini API
o Google Cloud Speech-to-Text) o si connectes un proveïdor remot d'IA pel teu compte.
L'opció **File → Work offline** atura tot això. Totes les connexions es detallen a
[../CONFIG.md](../CONFIG.md#network-use).

## Documentació

[Instal·lació (Install)](../INSTALL.md) · [Configuració (Configuration)](../CONFIG.md) ·
[Transcripció en directe (Live transcription)](../LIVE.md) · [Mode de xarxa local i API (Local-network mode and API)](../SERVER.md) ·
[Motors al núvol (Cloud engines)](../CLOUD_STT.md) · [Arquitectura (Architecture)](../ARCHITECTURE.md) ·
[Changelog](../CHANGELOG.md) · [Tota la documentació (All docs)](../README.md)

## Compilar des del codi font

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Requereix Python 3.11 o posterior. Processos de compilació (pipelines): [../BUILD.md](../BUILD.md). Proves i pull requests:
[../../CONTRIBUTING.md](../../CONTRIBUTING.md).

## Contribucions i contacte

- **Errors i peticions de funcionalitats:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Dubtes i idees:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Tota la resta:** per correu electrònic, a través de la
  [secció Contact del lloc web](https://whisper-transcriber-suite.pages.dev/#contact)
- **Informes de seguretat:** [../../SECURITY.md](../../SECURITY.md)

Aquest projecte segueix el [Contributor Covenant](../../.github/CODE_OF_CONDUCT.md).
Si l'aplicació t'estalvia temps, deixar una Estrella (Star) a la part superior d'aquesta pàgina ajudarà altres persones a
trobar-la.

## Com es desenvolupa aquest projecte

El mantenidor desenvolupa aquest programari amb una gran ajuda per part d'assistents d'IA per a la programació (principalment Claude). Les comprovacions de tipus
i les proves unitàries (unit tests) han de passar abans de cada commit, i la CI els torna a executar a Windows i Linux després
de cada push. La [llista de comprovació de llançaments (release checklist)](../RELEASE_PROCESS.md) inclou una prova d'instal·lació manual en un
ordinador real. Els commits fets amb ajuda de la IA ara inclouen el nom del model en una línia `Assisted-by:`; molts dels
més antics contenen en canvi la línia `Co-Authored-By: Claude`.

## Llicència

Copyright (c) 2026 translation-robot (co-author). El projecte s'allotja en aquest repositori,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
El codi font del projecte està subjecte a la llicència [BSD 3-Clause License](../../LICENSE). Les eines
incloses, el runtime de Python i els models mantenen les seves pròpies llicències; vegeu
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
