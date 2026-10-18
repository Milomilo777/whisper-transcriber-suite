<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**Transcrição e legendas gratuitas e offline para longas gravações no seu idioma — num portátil comum, sem necessidade de conta e sem envio de áudio.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Transferir para Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS e Linux: consulte a secção [Transferir](#download).

<!-- language-links:start -->

<p>
<a href="../../README.md">English</a> ·
<a href="README.de.md">Deutsch</a> ·
<a href="README.fr.md">Français</a> ·
<a href="README.es.md">Español</a> ·
<a href="README.it.md">Italiano</a> ·
<a href="README.pt-BR.md">Português (Brasil)</a> ·
<b>Português (Portugal)</b> ·
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

## A quem se destina

Legendadores, tradutores, investigadores e jornalistas que convertem longas
gravações (entrevistas, palestras, conferências, vídeos) em texto ou legendas.
Arraste um ficheiro de áudio ou vídeo e a transcrição será guardada junto ao mesmo. O motor de reconhecimento de voz é executado no seu próprio computador, portanto não há
custos por minuto e, uma vez transferido o modelo, não é necessária ligação
à internet.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="O separador Transcribe: uma área para largar ficheiros, seletores de motor e idioma, e opções de etiquetas de orador e de marcas temporais por palavra" width="80%">
</div>

## Novidades na versão 2.0

- **Velocidade e tempo restante:** o separador "Queue" (Fila) mostra a velocidade de cada tarefa e uma estimativa do tempo restante.
- **Vídeo legendado a partir de um link:** transfira, transcreva e incorpore as legendas numa única tarefa ([docs/SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Transcrição como página web:** um ficheiro `.html` com pesquisa e reprodução ao clicar, que funciona offline em qualquer navegador.
- **Modo offline verificável:** com a opção "Work offline" ativa, uma linha de estado mostra se a aplicação ou um processo iniciado por ela tem ligação à rede.
- **Tradução para inglês:** discurso noutros idiomas é convertido em legendas em inglês de uma só vez.
- **Início rápido:** as novas instalações fazem três perguntas, e um clipe de amostra de 18 segundos mostra o resultado imediatamente.
- **Reportar um problema** através do menu Help, sem necessidade de conta no GitHub.
- **macOS:** menu da aplicação com Settings (Comando-vírgula), modos Claro e Escuro que seguem o sistema, notificações. **Windows:** progresso na barra de tarefas e barras de título escuras.

Lista completa: [CHANGELOG](../CHANGELOG.md).

## Funcionalidades

- **Motores locais:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (padrão), whisper.cpp e NVIDIA Parakeet, para os muitos idiomas que o Whisper
  reconhece. Utiliza uma GPU NVIDIA
  através do CUDA quando possível, caso contrário utiliza o processador (CPU).
- **A aplicação no seu idioma:** Menus, botões e mensagens em 42 idiomas (tradução
  automática, assinalada como tal; as correções são bem-vindas). Segue o idioma do
  seu sistema, ou pode escolher um em Definições avançadas. O persa, o árabe e o
  hebraico estão, para já, disponíveis no Windows.
- **14 formatos de saída:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX e
  PDF, para além dos formatos oTranscribe, ELAN, InqScribe e Express Scribe. Os formatos DOCX
  e PDF renderizam todas as escritas corretamente, e persa, árabe e urdu são lidos da direita para a esquerda
  com letras unidas.
- **Página web partilhável:** guarde uma transcrição concluída como um único ficheiro `.html` que
  funciona offline em qualquer navegador; clique numa palavra para a ouvir, pesquise, salte entre
  capítulos.
- **Identificação de oradores** sem necessidade de conta no Hugging Face, com carimbos de data/hora palavra a palavra e
  recorte de intervalos de tempo.
- **Retoma de tarefas interrompidas** a partir do último ponto de restauro, em vez de recomeçar
  do zero (motor padrão).
- **Vídeos online:** transfira de qualquer site suportado pelo [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  e transcreva assim que a transferência for concluída.
- **Link para vídeo legendado:** basta uma seleção para converter um link em `<title>-subbed.mp4`
  com as legendas incorporadas: transfira, transcreva e incorpore numa única tarefa em fila de espera
  ([docs/SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Ao vivo:** transcreva o microfone, ou o áudio do sistema no Windows, em tempo
  real ([docs/LIVE.md](../LIVE.md)).
- **Fila de tarefas em lote e pasta monitorizada** para vários ficheiros em simultâneo.
- **Modo de rede local:** uma página de transcrição e uma API compatível com OpenAI para
  os restantes dispositivos na sua rede ([docs/SERVER.md](../SERVER.md)).
- **Opcional, desativado por padrão:** ferramentas de IA para uma transcrição concluída (resumo,
  perguntas, SRT bilingue), e texto para voz offline com clonagem de voz.

Como se compara ao Subtitle Edit, Vibe, Buzz, noScribe e aTrain,
incluindo em que situações outra aplicação poderá ser a melhor escolha:
**[docs/COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Transferir

Último lançamento: **[página de lançamentos](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| Ficheiro | Para |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 ou 11, 64 bits. A maioria dos utilizadores necessita deste. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows sem instalação: extrair e executar. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Macs com Apple Silicon, macOS 14 ou mais recente. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Macs com processadores Intel, macOS 10.15 ou mais recente. |

Linux executa-se a partir do código fonte: [platform/linux/README.md](../../platform/linux/README.md).

O executável FFmpeg incluído é uma compilação GPL. O seu código fonte correspondente encontra-se anexado a cada versão como ficheiros
`WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*`; os links exatos estão presentes em
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

ffmpeg e yt-dlp vêm incluídos. Ao abrir pela primeira vez, uma janela de início rápido permite escolher
o modelo de voz para o seu idioma: Rápido (Small, cerca de 500 MB) ou Melhor
qualidade (até cerca de 3 GB); será transferido uma única vez, na primeira utilização. Planeie cerca de 8 GB
de memória RAM; no processador (CPU) os modelos Large demoram aproximadamente 1.5 a 2.5 vezes a duração do
áudio e os Small demoram cerca de metade. Uma placa gráfica (GPU) NVIDIA é bastante mais rápida. As compilações do Windows não são assinadas e as do Mac não são
notarizadas, pelo que o SmartScreen e o Gatekeeper poderão apresentar avisos na primeira vez que o executar;
[docs/INSTALL.md](../INSTALL.md) demonstra os passos necessários para avançar. Para atualizar, execute simplesmente o
novo instalador por cima do antigo; as suas definições serão mantidas.

**Transferências por versão** (cada emblema contabiliza apenas a própria versão — as versões antigas mantêm-se publicadas e os seus contadores nunca são repostos a zero):

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

Com as definições por omissão, os seus ficheiros áudio e transcrições permanecem sempre no seu computador.
A aplicação utiliza a rede para:

- transferir um modelo ou um componente opcional da primeira vez que for necessário;
- configurações iniciais e uma verificação diária de atualizações no GitHub, que
  serve apenas para o notificar de uma nova versão;
- estatísticas de utilização, ativas por omissão, após cada transcrição terminada: modelo utilizado,
  idioma, durações, contagem de palavras, versão da aplicação, sistema operativo, tamanho da CPU e da
  memória RAM, além da região, mas nunca o nome do ficheiro. Poderá desativar esta opção em
  **Help → Usage statistics**.

O texto da transcrição e o ficheiro áudio só serão enviados para a internet se optar ativamente por um motor em nuvem (API Gemini
ou Google Cloud Speech-to-Text) ou associar um provedor de IA remoto. O modo
**File → Work offline** desativa imediatamente qualquer ligação. Todas as ligações encontram-se descritas em
[docs/CONFIG.md](../CONFIG.md#network-use).

## Documentação

[Instalação](../INSTALL.md) · [Configuração](../CONFIG.md) ·
[Transcrição ao vivo](../LIVE.md) · [Modo de rede local e API](../SERVER.md) ·
[Motores na nuvem](../CLOUD_STT.md) · [Arquitetura](../ARCHITECTURE.md) ·
[Changelog](../CHANGELOG.md) · [Toda a documentação](../README.md)

## Compilar através do código fonte

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Necessita de Python 3.11 ou mais recente. Pipelines de compilação: [docs/BUILD.md](../BUILD.md). Testes e pull requests:
[CONTRIBUTING.md](../../CONTRIBUTING.md).

## Contribuição e contacto

- **Bugs e sugestões de funcionalidades:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Dúvidas e ideias:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Quaisquer outros assuntos:** via correio eletrónico, através da
  [Secção de contacto do site](https://whisper-transcriber-suite.com/#contact)
- **Relatórios de segurança:** [SECURITY.md](../../SECURITY.md)

Este projeto segue o [Contributor Covenant](../../.github/CODE_OF_CONDUCT.md).
Se a aplicação lhe poupar tempo, deixar uma Estrela (Star) no topo desta página poderá ajudar outros utilizadores
a encontrá-la mais rapidamente.

## Como este projeto é concebido

O mantenedor (maintainer) desenvolve o projeto com considerável auxílio de assistentes virtuais de IA (essencialmente o Claude). As verificações de tipo
e os testes unitários necessitam de ser concluídos com sucesso antes de cada alteração de código (commit), e o sistema de integração contínua (CI) volta a executá-los para Windows e Linux após
cada submissão (push). A [lista de verificação de lançamentos](../RELEASE_PROCESS.md) inclui uma etapa manual para testar a instalação num computador
físico. Atualmente, sempre que um submissão é realizado em conjunto com um assistente de IA, o respetivo modelo é mencionado na linha `Assisted-by:`; as submissões mais
antigas têm antes uma linha `Co-Authored-By: Claude`.

## Licença

Copyright (c) 2026 translation-robot (co-autor). O projeto é desenvolvido e mantido neste repositório,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
O código fonte do projeto encontra-se licenciado sob os termos da [Licença BSD 3-Clause](../../LICENSE). As ferramentas incorporadas,
o ambiente de execução Python e os modelos mantêm, respetivamente, as suas próprias licenças; consulte a secção
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
