<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**Transcription et sous-titres gratuits et hors ligne pour vos longs enregistrements, dans votre langue — sur un simple ordinateur portable, sans compte ni envoi audio.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Télécharger pour Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS et Linux : voir [Téléchargement](#download).

<!-- language-links:start -->

<p>
<a href="../../README.md">English</a> ·
<a href="README.de.md">Deutsch</a> ·
<b>Français</b> ·
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

## Pour qui est-ce fait

Sous-titreurs, traducteurs, chercheurs et journalistes qui transforment de longs
enregistrements (interviews, cours, conférences, vidéos) en texte ou en sous-titres.
Déposez un fichier audio ou vidéo et la transcription sera générée juste à côté. Le moteur de reconnaissance vocale tourne sur votre propre ordinateur : il n'y a donc
aucun coût à la minute et, une fois le modèle téléchargé, aucune connexion Internet
n'est nécessaire.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="L'onglet Transcribe : une zone de dépôt, des sélecteurs de moteur et de langue, des options d'étiquettes de locuteur et d'horodatage des mots" width="80%">
</div>

## Nouveautés de la version 2.0

- **Vitesse et temps restant :** l'onglet "Queue" (file d'attente) indique la vitesse de chaque tâche et une estimation du temps restant.
- **Vidéo sous-titrée à partir d'un lien :** téléchargez, transcrivez et incrustez les sous-titres en une seule tâche ([docs/SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Transcription au format page web :** un unique fichier `.html` avec fonction de recherche et lecture au clic, qui fonctionne hors ligne dans n'importe quel navigateur.
- **Un mode hors ligne vérifiable :** lorsque "Work offline" est activé, une ligne d'état indique si l'application ou l'un de ses processus dispose d'une connexion réseau.
- **Traduction vers l'anglais :** un discours non anglophone est converti en sous-titres anglais en une seule étape.
- **Démarrage rapide :** lors d'une nouvelle installation, l'application pose trois questions et un extrait audio de 18 secondes vous montre immédiatement un résultat.
- **Signaler un problème** directement depuis le menu Help (Aide), sans compte GitHub.
- **macOS :** menu d'application avec Settings (Commande-virgule), modes Clair et Sombre qui suivent les réglages du système, notifications. **Windows :** progression dans la barre des tâches et barres de titre sombres.

Liste complète : [CHANGELOG](../CHANGELOG.md).

## Fonctionnalités

- **Moteurs locaux :** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (par défaut), whisper.cpp et NVIDIA Parakeet, pour les nombreuses langues reconnues
  par Whisper. Utilise un GPU NVIDIA
  via CUDA lorsque cela est possible, sinon le processeur (CPU).
- **L'application dans votre langue :** Menus, boutons et messages en 42 langues
  (traduits automatiquement et signalés comme tels ; les corrections sont les
  bienvenues). Elle suit la langue de votre système, ou vous en choisissez une dans
  les Paramètres avancés. Le persan, l'arabe et l'hébreu sont proposés sous Windows
  pour l'instant.
- **14 formats de sortie :** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX et
  PDF, ainsi que les formats pour oTranscribe, ELAN, InqScribe et Express Scribe. DOCX
  et PDF gèrent tous les alphabets, et le persan, l'arabe et l'ourdou se lisent de droite à gauche
  en lettres attachées.
- **Page web partageable :** sauvegardez une transcription terminée sous la forme d'un unique fichier `.html` qui
  fonctionne hors ligne dans n'importe quel navigateur ; cliquez sur un mot pour l'écouter, recherchez et sautez
  de chapitre en chapitre.
- **Étiquettes de locuteurs** sans aucun compte Hugging Face, avec en plus l'horodatage mot à mot et
  le découpage par intervalles de temps.
- **Reprise des tâches interrompues :** elles redémarrent depuis leur dernière sauvegarde au lieu de recommencer
  depuis le début (moteur par défaut).
- **Vidéos en ligne :** téléchargez depuis n'importe quel site pris en charge par [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  et transcrivez le fichier une fois le téléchargement terminé.
- **Lien vers une vidéo sous-titrée :** une case à cocher transforme un lien en un fichier `<title>-subbed.mp4`
  avec les sous-titres incrustés : le téléchargement, la transcription et l'incrustation se font au sein d'une seule tâche
  ([docs/SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **En direct :** transcrivez le son de votre microphone, ou de votre système sous Windows, en temps
  réel ([docs/LIVE.md](../LIVE.md)).
- **File d'attente et dossier surveillé** pour traiter de nombreux fichiers à la chaîne.
- **Mode réseau local :** une page de transcription et une API compatible OpenAI pour
  les autres appareils de votre réseau ([docs/SERVER.md](../SERVER.md)).
- **Optionnel, désactivé par défaut :** des outils d'IA pour les transcriptions terminées (résumé,
  questions, SRT bilingue), et de la synthèse vocale hors ligne avec clonage de voix.

Comparatif avec Subtitle Edit, Vibe, Buzz, noScribe et aTrain,
y compris pour savoir dans quels cas une autre application serait un meilleur choix :
**[docs/COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Téléchargement

Dernière version : **[page des versions (releases)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| Fichier | Pour |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 ou 11, 64 bits. C'est le fichier qu'il vous faut dans la plupart des cas. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows sans installation : décompressez et lancez l'application. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Mac avec puce Apple (Apple Silicon), macOS 14 ou supérieur. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Mac Intel, macOS 10.15 ou supérieur. |

Pour Linux, exécutez depuis le code source : [platform/linux/README.md](../../platform/linux/README.md).

L'exécutable FFmpeg intégré est une compilation sous licence GPL. Son code source correspondant est joint à chaque version sous forme
de fichiers `WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*` ; les liens exacts se trouvent dans
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

ffmpeg et yt-dlp sont inclus. Au premier lancement, une fenêtre de démarrage rapide vous permet
de choisir le modèle vocal pour votre langue : Rapide (Small, environ 500 Mo) ou Meilleure
qualité (jusqu'à environ 3 Go) ; il se télécharge une seule fois lors de la première utilisation. Prévoyez 8 Go
de RAM ; sur un CPU, le modèle Large met un temps égal à 1.5–2.5 fois la durée de
l'audio et le modèle Small environ la moitié de ce temps. Un GPU NVIDIA est beaucoup plus rapide. Les versions Windows ne sont pas signées numériquement et les versions Mac ne sont pas
notariées, de sorte que SmartScreen et Gatekeeper afficheront un avertissement au premier lancement ;
[docs/INSTALL.md](../INSTALL.md) vous montre sur quoi cliquer. Pour effectuer une mise à jour, exécutez le
nouvel installateur par-dessus l'ancien ; vos paramètres seront conservés.

**Téléchargements par version** (chaque badge ne compte que la sortie de cette version — les anciennes versions restent publiées et leurs compteurs ne sont jamais remis à zéro) :

[![v2.1.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.1.0/total?label=v2.1.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.1.0)
[![v2.0.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.0.0/total?label=v2.0.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0)
[![v1.9.3](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.3/total?label=v1.9.3&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.3)
[![v1.9.1](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.1/total?label=v1.9.1&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.1)
[![v1.9.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.0/total?label=v1.9.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.0)
[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

## Ce qui quitte votre ordinateur

Avec les paramètres par défaut, votre audio et vos transcriptions restent sur votre ordinateur.
L'application utilise néanmoins le réseau pour :

- le téléchargement d'un modèle ou d'un composant optionnel la première fois qu'il est nécessaire ;
- ses paramètres en ligne au démarrage et la vérification quotidienne des mises à jour sur GitHub, ce qui
  sert uniquement à vous informer d'une nouvelle version ;
- les statistiques d'utilisation, activées par défaut, envoyées après chaque transcription terminée : modèle,
  langue, durées, nombre de mots, version de l'application, système d'exploitation, processeur (CPU), 
  quantité de RAM, et région, mais jamais le nom du fichier. Vous pouvez les désactiver sous
  **Help → Usage statistics**.

Le texte de la transcription ou le fichier audio ne sont envoyés que si vous choisissez un moteur dans le cloud (API Gemini
ou Google Cloud Speech-to-Text) ou si vous vous connectez vous-même à un fournisseur d'IA distant.
**File → Work offline** (Mode hors ligne) bloque l'ensemble de ces connexions. Chaque connexion est détaillée dans
[docs/CONFIG.md](../CONFIG.md#network-use).

## Documentation

[Installation](../INSTALL.md) · [Configuration](../CONFIG.md) ·
[Transcription en direct](../LIVE.md) · [Mode réseau local et API](../SERVER.md) ·
[Moteurs cloud](../CLOUD_STT.md) · [Architecture](../ARCHITECTURE.md) ·
[Changelog (Journal des modifications)](../CHANGELOG.md) · [Toute la documentation](../README.md)

## Compiler à partir du code source

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Nécessite Python 3.11 ou supérieur. Pipelines de compilation : [docs/BUILD.md](../BUILD.md). Tests et pull requests :
[CONTRIBUTING.md](../../CONTRIBUTING.md).

## Contribuer et contact

- **Signaler un bug et proposer une fonctionnalité :** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Questions et idées :** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Tout le reste :** par email, via la
  [section Contact du site web](https://whisper-transcriber-suite.com/#contact)
- **Rapports de sécurité :** [SECURITY.md](../../SECURITY.md)

Ce projet suit le code de conduite [Contributor Covenant](../../.github/CODE_OF_CONDUCT.md).
Si l'application vous fait gagner du temps, une étoile (Star) en haut de cette page aidera d'autres personnes
à la trouver.

## Comment ce projet est conçu

Le responsable (maintainer) développe le projet avec l'aide importante d'assistants de codage IA (principalement Claude). Les vérifications de typage
et les tests unitaires doivent réussir avant chaque commit, et l'intégration continue (CI) les exécute à nouveau sous Windows et Linux après
chaque push. La [liste de contrôle des versions](../RELEASE_PROCESS.md) comprend un test manuel d'installation sur une
machine réelle. Les commits effectués avec l'aide d'une IA mentionnent désormais le modèle dans une ligne `Assisted-by:` ; beaucoup d'anciens
commits comportent à la place une ligne `Co-Authored-By: Claude`.

## Licence

Copyright (c) 2026 translation-robot (co-auteur). Le projet est hébergé sur ce dépôt,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
Le code source propre au projet est sous [licence BSD 3-Clause](../../LICENSE). Les outils
intégrés, l'environnement d'exécution Python et les modèles conservent leurs propres licences ; voir
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
