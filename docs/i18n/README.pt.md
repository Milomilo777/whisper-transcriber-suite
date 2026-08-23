<div align="center">

<img src="../img/hero.png" alt="Whisper Project" width="100%">

# Whisper Project

### Arraste um ficheiro de áudio ou vídeo. Receba uma **transcrição com marcação de tempo e formatada** — sem que o ficheiro saia do seu computador.

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![downloads](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/total?color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases)
[![License: BSD-3](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)
[![Stars](https://img.shields.io/github/stars/Milomilo777/whisper-transcriber-suite?style=flat&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/stargazers)

### [⬇  Transferir para Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

<p>
  <a href="../../README.md"><img src="https://flagcdn.com/16x12/us.png" alt="" width="16" height="12"> English</a> ∙
  <a href="README.zh-CN.md"><img src="https://flagcdn.com/16x12/cn.png" alt="" width="16" height="12"> 简体中文</a> ∙
  <a href="README.ja.md"><img src="https://flagcdn.com/16x12/jp.png" alt="" width="16" height="12"> 日本語</a> ∙
  <a href="README.ko.md"><img src="https://flagcdn.com/16x12/kr.png" alt="" width="16" height="12"> 한국어</a> ∙
  <a href="README.de.md"><img src="https://flagcdn.com/16x12/de.png" alt="" width="16" height="12"> Deutsch</a> ∙
  <a href="README.es.md"><img src="https://flagcdn.com/16x12/es.png" alt="" width="16" height="12"> Español</a> ∙
  <a href="README.fr.md"><img src="https://flagcdn.com/16x12/fr.png" alt="" width="16" height="12"> Français</a> ∙
  <img src="https://flagcdn.com/16x12/pt.png" alt="" width="16" height="12">
  <b>Português</b> ∙
  <a href="README.fa.md"><img src="https://flagcdn.com/16x12/ir.png" alt="" width="16" height="12"> فارسی</a>
</p>

</div>

---

Uma aplicação de ambiente de trabalho que executa o modelo Whisper da OpenAI **localmente**, através do [faster-whisper](https://github.com/SYSTRAN/faster-whisper), pelo que transcrever não custa nada por minuto, funciona num avião e nunca envia a sua gravação para ninguém. Largue um ficheiro e serão escritos `.srt`, `.vtt`, `.txt`, `.json`, `.docx`, `.pdf` e mais, ao lado do original. Também descarrega de qualquer site suportado pelo `yt-dlp`, identifica oradores, processa uma fila de trabalhos e pode transformar-se numa página de transcrição para os outros dispositivos da sua rede.

Sem conta. Sem chave de API. Sem subscrição. Os seus ficheiros ficam no seu disco.

- 🔒 **Corre na sua máquina** — faster-whisper (CTranslate2) por omissão, mais whisper.cpp e NVIDIA Parakeet
- 📝 **14 formatos de saída** — `srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf`, mais oTranscribe / ELAN / InqScribe / Express Scribe
- 🎙️ **Transcrição em direto** — microfone ou som do sistema, enquanto se fala → [LIVE.md](../LIVE.md)
- 🗣️ **Identificação de oradores** — diarização offline, marcação de tempo por palavra e corte por intervalo
- 🎬 **Descargas** — qualquer site suportado pelo `yt-dlp`, com transcrição automática no fim se quiser
- 🧹 **Redução de ruído adaptativa** — mede o áudio e só o limpa quando isso ajuda → [DENOISE.md](../DENOISE.md)
- 🌐 **Modo de rede local** — torne esta máquina numa página de transcrição para os seus outros dispositivos
- 💸 **Gratuito e com licença BSD-3** — sem custo por minuto, sem subscrição, sem telemetria por omissão

## Transferência

Obtenha a versão mais recente na **[página de releases](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**:

| Ficheiro | Tamanho | Indicado para |
|---|---|---|
| **`WhisperProject-…-Setup-Standard.exe`** | ~215 MB | **A maioria das pessoas.** Um instalador normal: atalho no menu Iniciar, atualiza por cima de uma versão anterior, ficheiros visíveis no disco. |
| **`WhisperProject-…-Portable.zip`** | ~330 MB | Descompactar e executar. Sem instalação, sem permissões de administrador, funciona numa pen USB. |
| **`WhisperProject-…-macOS-*.dmg`** | ~400 MB | macOS (x64 e arm64 são publicados em separado). |

Está tudo incluído — um Python integrado, `ffmpeg`, `ffprobe` e `yt-dlp`. A única coisa transferida depois é o próprio modelo de voz (**1–3 GB, uma só vez**, no primeiro arranque); a partir daí a aplicação funciona totalmente offline.

## Funcionalidades

<div align="center">

<img src="../img/features.png" alt="" width="100%">

</div>

| | |
|---|---|
| **Transcrição local** | Whisper `large-v3` por omissão, mais `large-v3-turbo` e `distil-large-v3.5`. |
| **Muitos formatos de saída** | `srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf` — escritos ao lado do ficheiro de entrada. |
| **Transcrição em direto** | Transcreve um microfone — ou o que esta máquina estiver a reproduzir — em tempo real. Os cortes caem em pausas naturais, pelo que as palavras nunca ficam partidas ao meio. |
| **Diarização de oradores** | «Identificar oradores» opcional, mais marcação de tempo por palavra e corte por intervalo. |
| **Redução de ruído adaptativa** | Mede cada gravação primeiro e só a limpa quando a medição o justifica; verifica o próprio resultado e descarta-o se tiver removido voz. |
| **Fila de processamento** | Estado em direto de cada trabalho pendente e em curso, com **Pausar / Retomar / Cancelar / Repetir / Remover** sempre a um clique. |
| **Descargas** | Tudo o que o `yt-dlp` consegue, mais ligações de episódios da Supreme Master TV. As descargas retomam em vez de recomeçar. |
| **Modo de rede local** | Um servidor web feito só com a biblioteca padrão, para que outros dispositivos transcrevam através desta máquina — palavra-passe opcional, desligado até o iniciar. |

## Como funciona

<div align="center">

<img src="../img/how-it-works.png" alt="" width="100%">

</div>

A interface Tk corre no processo principal. Cada trabalho de transcrição corre num subprocesso de longa duração que mantém o modelo Whisper em memória e responde por JSON delimitado por linhas em stdin/stdout; o `yt-dlp` recebe um subprocesso próprio por descarga. Um token UUID por worker e um sinal de vida de 5 segundos tornam esse encaminhamento robusto face à reutilização de identificadores de processo e permitem à interface detetar um worker bloqueado em vez de bloquear com ele.

## Offline por omissão

Todos os backends por omissão correm na sua máquina. Nada é enviado, não existe conta e, depois de o modelo ser transferido, a aplicação funciona com a rede desligada.

> [!IMPORTANT]
> Dois backends **opcionais** quebram essa garantia e ambos estão desligados a menos que vá a **Advanced → Backend** e os escolha. Use-os apenas com conteúdo que esteja disposto a enviar a terceiros.
>
> - **`cloud_stt`** — Google Gemini API → [CLOUD_STT.md](../CLOUD_STT.md)
> - **`google_cloud_stt`** — Google Cloud Speech-to-Text → [CLOUD_STT_GOOGLE.md](../CLOUD_STT_GOOGLE.md)

## Compilar a partir do código

```bash
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

## Documentação

| Documento | Conteúdo |
|---|---|
| [INSTALL.md](../INSTALL.md) | Instalação e resolução de problemas |
| [LIVE.md](../LIVE.md) | O separador Live |
| [DENOISE.md](../DENOISE.md) | Redução de ruído adaptativa |
| [SERVER.md](../SERVER.md) | Modo servidor web / rede local |
| [CONFIG.md](../CONFIG.md) | Todas as chaves de configuração |
| [BUILD.md](../BUILD.md) | Compilar por si próprio |
| [CHANGELOG.md](../CHANGELOG.md) | Histórico de versões |

> A documentação completa está em inglês. Esta página é um resumo; consulte os documentos em inglês para os detalhes.

## Licença

O código próprio deste projeto está sob a **licença BSD 3-Clause** — ver [LICENSE](../../LICENSE). Os binários incluídos (`ffmpeg`, `ffprobe`, `yt-dlp`), o ambiente Python fornecido e os seus pacotes, e o próprio modelo Whisper mantêm as suas licenças originais; [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) resume-as.

---

<div align="center">
<sub>transcrição offline · Whisper local com interface · gerador de legendas · diarização · Windows · macOS</sub>
</div>
