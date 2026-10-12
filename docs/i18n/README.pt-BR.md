<div align="center">

<img src="../img/hero.png" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**Transcrição e legendas offline e gratuitas para gravações longas no seu idioma — em um laptop comum, sem conta e sem fazer upload do áudio.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Baixar para Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS e Linux: veja em [Download](#download).

<!-- language-links:start -->

<p>
<a href="../../README.md">English</a> ·
<a href="README.de.md">Deutsch</a> ·
<a href="README.fr.md">Français</a> ·
<a href="README.es.md">Español</a> ·
<a href="README.it.md">Italiano</a> ·
<b>Português (Brasil)</b> ·
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

## Para quem é

Legendadores, tradutores, pesquisadores e jornalistas que transformam gravações
longas (entrevistas, aulas, palestras, vídeos) em texto ou legendas.
Arraste um arquivo de áudio ou vídeo e a transcrição será salva ao lado dele. O motor de reconhecimento de fala roda no seu próprio computador, portanto
não há custo por minuto e, uma vez que o modelo é baixado, nenhuma conexão com
a internet é necessária.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="A aba Transcribe: uma área para soltar arquivos, seletores de mecanismo e idioma, e opções de rótulos de falante e carimbos de tempo por palavra" width="80%">
</div>

## O que há de novo na versão 2.0

- **Velocidade e tempo restante:** a aba Queue (Fila) mostra a velocidade de cada tarefa e uma estimativa do tempo restante.
- **Vídeo legendado a partir de um link:** baixe, transcreva e incorpore as legendas no vídeo em uma única tarefa ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Transcrição como página web:** um único arquivo `.html` com busca e clique para reproduzir que funciona offline em qualquer navegador.
- **Trabalho offline verificável:** com o modo Work offline ativado, uma barra de status mostra se o aplicativo ou algum processo iniciado por ele possui conexão com a rede.
- **Traduzir para o inglês:** áudios em outros idiomas viram legendas em inglês em uma única etapa.
- **Início rápido:** novas instalações fazem três perguntas, e um clipe de amostra de 18 segundos exibe o resultado imediatamente.
- **Relatar um problema** (Report a problem) no menu Help, sem precisar de uma conta no GitHub.
- **macOS:** menu do aplicativo com Settings (Command-vírgula), temas Light (Claro) e Dark (Escuro) que acompanham o sistema, notificações. **Windows:** progresso na barra de tarefas e barras de título escuras.

Lista completa: [CHANGELOG](../CHANGELOG.md).

## Funcionalidades

- **Motores locais:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (padrão), whisper.cpp e NVIDIA Parakeet, para os diversos idiomas que o Whisper
  reconhece. Utiliza uma GPU NVIDIA
  via CUDA quando possível, caso contrário utiliza a CPU.
- **O aplicativo no seu idioma:** Menus, botões e mensagens em 42 idiomas (tradução
  automática, indicada como tal; correções são bem-vindas). Ele segue o idioma do
  seu sistema, ou você escolhe um em Configurações avançadas. Persa, árabe e
  hebraico estão disponíveis por enquanto no Windows.
- **14 formatos de saída:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX e
  PDF, além dos formatos oTranscribe, ELAN, InqScribe e Express Scribe. DOCX
  e PDF renderizam qualquer sistema de escrita, e persa, árabe e urdu são lidos da direita para a esquerda
  com as letras conectadas.
- **Página web compartilhável:** salve uma transcrição concluída como um único arquivo `.html` que
  funciona offline em qualquer navegador; clique em uma palavra para ouvi-la, busque ou pule para os
  capítulos.
- **Identificação de locutores (Speaker labels)** sem precisar de uma conta no Hugging Face, além de timestamps (marcações de tempo) por palavra e
  recorte de intervalo de tempo.
- **Tarefas interrompidas são retomadas** a partir do último ponto de verificação (checkpoint) em vez de começarem
  do zero (motor padrão).
- **Vídeos online:** baixe de qualquer site que o [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  suporte e faça a transcrição assim que o download terminar.
- **Link para vídeo legendado:** uma única opção transforma um link em `<title>-subbed.mp4`
  com as legendas embutidas: baixa, transcreve e embute tudo em uma única tarefa na fila
  ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Ao vivo (Live):** transcreva um microfone, ou o áudio do sistema no Windows, em tempo
  real ([../LIVE.md](../LIVE.md)).
- **Fila de processamento em lote e pasta monitorada** para processar muitos arquivos.
- **Modo de rede local:** uma página de transcrição e uma API compatível com OpenAI para
  os outros dispositivos na sua rede ([../SERVER.md](../SERVER.md)).
- **Opcionais, desativados por padrão:** ferramentas de IA para uma transcrição concluída (resumo,
  perguntas, SRT bilíngue) e conversão de texto em voz offline, incluindo clonagem de voz.

Como ele se compara com Subtitle Edit, Vibe, Buzz, noScribe e aTrain,
incluindo quando outro aplicativo pode ser a melhor escolha:
**[../COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Download

Último lançamento (release): **[página de releases](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| Arquivo | Para |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 ou 11, 64-bit. A maioria das pessoas vai querer este. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows sem instalação: extraia e execute. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Macs com Apple Silicon, macOS 14 ou mais recente. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Macs Intel, macOS 10.15 ou mais recente. |

No Linux ele é executado a partir do código-fonte: [../../platform/linux/README.md](../../platform/linux/README.md).

O FFmpeg incluído é uma versão sob a licença GPL. O código-fonte correspondente está anexado a cada lançamento como
arquivos `WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*`; os links exatos estão em
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

ffmpeg e yt-dlp já vêm incluídos. Ao iniciar pela primeira vez, uma janela de início rápido permite escolher
o modelo de fala para o seu idioma: Fast (Pequeno, cerca de 500 MB) ou Best
quality (até cerca de 3 GB); o download é feito uma única vez, no primeiro uso. Planeje ter 8 GB
de RAM; em uma CPU os modelos grandes (Large) demoram de 1,5 a 2,5 vezes o tamanho
do áudio e os pequenos (Small) cerca da metade; uma GPU NVIDIA é muito mais rápida. As compilações para Windows não possuem assinatura de código e as do Mac não são
notarizadas, portanto, o SmartScreen e o Gatekeeper mostrarão avisos no primeiro uso;
[../INSTALL.md](../INSTALL.md) mostra onde você deve clicar. Para atualizar, execute o
novo instalador por cima do antigo; suas configurações serão mantidas.

**Downloads por versão** (cada emblema conta apenas os downloads daquela
versão específica — versões antigas continuam publicadas e suas contagens nunca são
zeradas):

[![v2.1.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.1.0/total?label=v2.1.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.1.0)
[![v2.0.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.0.0/total?label=v2.0.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0)
[![v1.9.3](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.3/total?label=v1.9.3&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.3)
[![v1.9.1](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.1/total?label=v1.9.1&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.1)
[![v1.9.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.0/total?label=v1.9.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.0)
[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

## O que sai do seu computador

Com as configurações padrão, o seu áudio e as transcrições permanecem no seu computador.
O aplicativo utiliza a rede apenas para:

- baixar um modelo ou um componente opcional na primeira vez que for necessário;
- suas configurações online na inicialização e uma verificação diária de atualização no GitHub, que
  apenas avisa sobre uma nova versão;
- estatísticas de uso, ativadas por padrão, após cada transcrição concluída: modelo,
  idioma, durações, contagem de palavras, versão do app, sistema operacional, CPU e
  tamanho da memória, além da região, mas nunca o nome do arquivo. Desative-as em
  **Help → Usage statistics**.

O áudio ou o texto da transcrição são enviados apenas se você escolher um motor em nuvem (Gemini API
ou Google Cloud Speech-to-Text) ou se conectar a um provedor remoto de IA por conta própria.
**File → Work offline** bloqueia tudo isso. Todas as conexões estão listadas em
[../CONFIG.md](../CONFIG.md#network-use).

## Documentação

[Instalação (Install)](../INSTALL.md) · [Configuração (Configuration)](../CONFIG.md) ·
[Transcrição ao vivo (Live transcription)](../LIVE.md) · [Modo de rede local e API (Local-network mode and API)](../SERVER.md) ·
[Motores em nuvem (Cloud engines)](../CLOUD_STT.md) · [Arquitetura (Architecture)](../ARCHITECTURE.md) ·
[Changelog](../CHANGELOG.md) · [Toda a documentação (All docs)](../README.md)

## Compilar a partir do código-fonte

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Requer Python 3.11 ou superior. Pipelines de compilação: [../BUILD.md](../BUILD.md). Testes e pull requests:
[../../CONTRIBUTING.md](../../CONTRIBUTING.md).

## Contribuição e contato

- **Bugs e solicitações de recursos:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Perguntas e ideias:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Tudo o mais:** por e-mail, por meio da
  [seção Contact (Contato) do site](https://whisper-transcriber-suite.pages.dev/#contact)
- **Relatórios de segurança:** [../../SECURITY.md](../../SECURITY.md)

Este projeto segue o [Contributor Covenant](../../.github/CODE_OF_CONDUCT.md).
Se o aplicativo poupar seu tempo, deixar uma Estrela (Star) no topo desta página ajudará outras pessoas a
encontrá-lo.

## Como este projeto é desenvolvido

O mantenedor desenvolve o projeto com grande ajuda de assistentes de IA para programação (principalmente o Claude). As verificações de tipagem
e os testes unitários precisam passar antes de cada commit, e a CI os executa novamente no Windows e no Linux após
cada push. A [lista de verificação de lançamentos (release checklist)](../RELEASE_PROCESS.md) inclui um teste de instalação manual em uma
máquina real. Os commits feitos com a ajuda de IA agora mencionam o nome do modelo em uma linha `Assisted-by:`; muitos dos mais antigos
contêm em vez disso uma linha `Co-Authored-By: Claude`.

## Licença

Copyright (c) 2026 translation-robot (co-author). O projeto fica neste repositório,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
O código-fonte do próprio projeto está sob a licença [BSD 3-Clause License](../../LICENSE). Ferramentas
embutidas, o runtime do Python e os modelos mantêm suas próprias licenças; veja em
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
