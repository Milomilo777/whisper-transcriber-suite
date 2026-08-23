<div align="center">

<img src="../img/hero.png" alt="Whisper Transcriber Suite" width="100%">

# Whisper Transcriber Suite

### Déposez un fichier audio ou vidéo. Récupérez une **transcription horodatée et mise en forme** — sans que le fichier quitte jamais votre ordinateur.

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![downloads](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/total?color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases)
[![License: BSD-3](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)
[![Stars](https://img.shields.io/github/stars/Milomilo777/whisper-transcriber-suite?style=flat&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/stargazers)

### [⬇  Télécharger pour Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

<p>
  <a href="../../README.md"><img src="https://flagcdn.com/16x12/us.png" alt="" width="16" height="12"> English</a> ∙
  <a href="README.zh-CN.md"><img src="https://flagcdn.com/16x12/cn.png" alt="" width="16" height="12"> 简体中文</a> ∙
  <a href="README.ja.md"><img src="https://flagcdn.com/16x12/jp.png" alt="" width="16" height="12"> 日本語</a> ∙
  <a href="README.ko.md"><img src="https://flagcdn.com/16x12/kr.png" alt="" width="16" height="12"> 한국어</a> ∙
  <a href="README.de.md"><img src="https://flagcdn.com/16x12/de.png" alt="" width="16" height="12"> Deutsch</a> ∙
  <a href="README.es.md"><img src="https://flagcdn.com/16x12/es.png" alt="" width="16" height="12"> Español</a> ∙
  <img src="https://flagcdn.com/16x12/fr.png" alt="" width="16" height="12">
  <b>Français</b> ∙
  <a href="README.pt.md"><img src="https://flagcdn.com/16x12/pt.png" alt="" width="16" height="12"> Português</a> ∙
  <a href="README.fa.md"><img src="https://flagcdn.com/16x12/ir.png" alt="" width="16" height="12"> فارسی</a>
</p>

</div>

---

Une application de bureau qui exécute le modèle Whisper d'OpenAI **en local**, via [faster-whisper](https://github.com/SYSTRAN/faster-whisper) : la transcription ne coûte rien à la minute, fonctionne en avion et n'envoie jamais votre enregistrement à qui que ce soit. Déposez un fichier et l'application écrit `.srt`, `.vtt`, `.txt`, `.json`, `.docx`, `.pdf` et d'autres formats, juste à côté de l'original. Elle télécharge aussi depuis tous les sites pris en charge par `yt-dlp`, identifie les locuteurs, traite une file d'attente et peut se transformer en page de transcription pour les autres appareils de votre réseau.

Pas de compte. Pas de clé d'API. Pas d'abonnement. Vos fichiers restent sur votre disque.

- 🔒 **S'exécute sur votre machine** — faster-whisper (CTranslate2) par défaut, plus whisper.cpp et NVIDIA Parakeet
- 📝 **14 formats de sortie** — `srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf`, plus oTranscribe / ELAN / InqScribe / Express Scribe
- 🎙️ **Transcription en direct** — micro ou son du système, pendant que ça se dit → [LIVE.md](../LIVE.md)
- 🗣️ **Étiquettes de locuteur** — diarisation hors ligne, horodatage par mot, découpe par intervalle
- 🎬 **Téléchargements** — tous les sites gérés par `yt-dlp`, avec transcription automatique à la fin si vous le souhaitez
- 🧹 **Débruitage adaptatif** — mesure l'audio et ne le nettoie que si cela aide → [DENOISE.md](../DENOISE.md)
- 🌐 **Mode réseau local** — transformez cette machine en page de transcription pour vos autres appareils
- 💸 **Gratuit et sous licence BSD-3** — aucun coût à la minute, aucun abonnement, aucune télémétrie par défaut

## Téléchargement

Récupérez la dernière version sur la **[page des releases](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)** :

| Fichier | Taille | Recommandé pour |
|---|---|---|
| **`WhisperTranscriberSuite-…-Setup-Standard.exe`** | ~215 MB | **La plupart des gens.** Un installateur classique : raccourci dans le menu Démarrer, mise à niveau par-dessus une version antérieure, fichiers visibles sur le disque. |
| **`WhisperTranscriberSuite-…-Portable.zip`** | ~330 MB | Décompressez et lancez. Aucune installation, aucun droit administrateur, fonctionne depuis une clé USB. |
| **`WhisperTranscriberSuite-…-macOS-*.dmg`** | ~400 MB | macOS (x64 et arm64 sont publiés séparément). |

Tout le nécessaire est inclus : un Python embarqué, `ffmpeg`, `ffprobe` et `yt-dlp`. Seul le modèle de reconnaissance vocale est téléchargé ensuite (**1 à 3 Go, une seule fois**, au premier lancement) ; après quoi l'application fonctionne entièrement hors ligne.

## Fonctionnalités

<div align="center">

<img src="../img/features.png" alt="" width="100%">

</div>

| | |
|---|---|
| **Transcription locale** | Whisper `large-v3` par défaut, plus `large-v3-turbo` et `distil-large-v3.5`. |
| **De nombreux formats** | `srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf` — écrits à côté du fichier d'entrée. |
| **Transcription en direct** | Transcrit un micro — ou ce que cette machine est en train de jouer — au fil de l'eau. Les coupures tombent dans les pauses naturelles, les mots ne sont donc jamais coupés en deux. |
| **Diarisation des locuteurs** | « Identifier les locuteurs » en option, plus l'horodatage par mot et la découpe par intervalle. |
| **Débruitage adaptatif** | Mesure chaque enregistrement d'abord et ne le nettoie que si la mesure le justifie ; vérifie son propre résultat et l'abandonne s'il a supprimé de la parole. |
| **File de traitement** | État en direct de chaque tâche en attente ou en cours, avec **Pause / Reprendre / Annuler / Relancer / Retirer** toujours à un clic. |
| **Téléchargements** | Tout ce que `yt-dlp` sait faire, plus les liens d'épisodes Supreme Master TV. Les téléchargements reprennent au lieu de recommencer. |
| **Mode réseau local** | Un serveur web fait uniquement avec la bibliothèque standard, pour que d'autres appareils transcrivent via cette machine — mot de passe facultatif, éteint tant que vous ne le démarrez pas. |

## Fonctionnement

<div align="center">

<img src="../img/how-it-works.png" alt="" width="100%">

</div>

L'interface Tk s'exécute dans le processus principal. Chaque tâche de transcription tourne dans un sous-processus de longue durée qui garde le modèle Whisper en mémoire et répond en JSON délimité par des sauts de ligne sur stdin/stdout ; `yt-dlp` reçoit son propre sous-processus par téléchargement. Un jeton UUID par worker et un battement de cœur toutes les 5 secondes rendent ce routage robuste face au recyclage des identifiants de processus et permettent à l'interface de détecter un worker bloqué au lieu de se bloquer avec lui.

## Hors ligne par défaut

Tous les moteurs par défaut s'exécutent sur votre machine. Rien n'est envoyé, aucun compte n'existe, et une fois le modèle téléchargé l'application fonctionne réseau débranché.

> [!IMPORTANT]
> Deux moteurs **optionnels** rompent cette garantie, et tous deux restent désactivés tant que vous n'allez pas les choisir dans **Advanced → Backend**. Ne les utilisez que pour du contenu que vous acceptez d'envoyer à un tiers.
>
> - **`cloud_stt`** — Google Gemini API → [CLOUD_STT.md](../CLOUD_STT.md)
> - **`google_cloud_stt`** — Google Cloud Speech-to-Text → [CLOUD_STT_GOOGLE.md](../CLOUD_STT_GOOGLE.md)

## Compiler depuis les sources

```bash
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

## Documentation

| Document | Contenu |
|---|---|
| [INSTALL.md](../INSTALL.md) | Installation et dépannage |
| [LIVE.md](../LIVE.md) | L'onglet Live |
| [DENOISE.md](../DENOISE.md) | Débruitage adaptatif |
| [SERVER.md](../SERVER.md) | Mode serveur web / réseau local |
| [CONFIG.md](../CONFIG.md) | Toutes les clés de configuration |
| [BUILD.md](../BUILD.md) | Compiler soi-même |
| [CHANGELOG.md](../CHANGELOG.md) | Historique des versions |

> La documentation complète est en anglais. Cette page est un aperçu ; reportez-vous aux documents anglais pour le détail.

## Licence

Le code propre à ce projet est publié sous **licence BSD 3-Clause** — voir [LICENSE](../../LICENSE). Les binaires embarqués (`ffmpeg`, `ffprobe`, `yt-dlp`), l'environnement Python fourni et ses paquets, ainsi que le modèle Whisper lui-même conservent leurs licences d'origine ; [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) les récapitule.

---

<div align="center">
<sub>transcription hors ligne · Whisper local avec interface · générateur de sous-titres · diarisation · Windows · macOS</sub>
</div>
