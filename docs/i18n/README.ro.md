<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: sunet la intrare, text la ieșire. Transcriere gratuită, open-source, care rulează Whisper pe propriul tău calculator." width="100%">

# Whisper Transcriber Suite

**Transcriere și subtitrare gratuită, offline, pentru înregistrări lungi, în limba ta — pe un laptop obișnuit, fără cont și fără încărcarea fișierelor audio.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Descarcă pentru Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS și Linux: vezi [Descărcare](#download).

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
<b>Română</b> ·
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

## Pentru cine este

Subtitratori, traducători, cercetători și jurnaliști care transformă înregistrări lungi
(interviuri, cursuri, discuții, videoclipuri) în text sau subtitrări.
Trage un fișier audio sau video și transcrierea este salvată alături de el. Motorul de vorbire rulează pe propriul tău calculator, așadar nu
există costuri pe minut și, odată ce modelul este descărcat, nu mai este necesară nicio conexiune
la internet.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="Fila Transcribe: o zonă de tragere, selectoare pentru motor și limbă, opțiuni pentru etichetarea vorbitorilor și marcaje de timp pentru cuvinte" width="80%">
</div>

## Noutăți în 2.0

- **Viteza și timpul rămas:** fila Queue arată viteza fiecărei sarcini și o estimare a timpului rămas.
- **Videoclip cu subtitrare dintr-un link:** descarcă, transcrie și integrează (burn in) subtitrările într-o singură sarcină ([docs/SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Transcrierea ca pagină web:** un singur fișier `.html` cu căutare și redare la un click distanță, care funcționează offline în orice browser.
- **Lucrează offline cu posibilitate de verificare:** cu opțiunea Work offline activată, o bară de stare arată dacă aplicația sau un proces inițiat de aceasta are conexiune la rețea.
- **Traduce în engleză:** vorbirea în altă limbă se transformă direct în subtitrări în engleză, într-un singur pas.
- **Pornire rapidă:** la o nouă instalare se pun trei întrebări, iar un clip mostră de 18 secunde afișează imediat rezultatul.
- **Raportează o problemă** din meniul Help, fără un cont GitHub.
- **macOS:** meniu al aplicației cu Setări (Command-virgulă), temă Luminoasă și Întunecată care urmează setările sistemului, notificări. **Windows:** progres afișat în bara de activități și bare de titlu întunecate.

Lista completă: [CHANGELOG](../CHANGELOG.md).

## Caracteristici

- **Motoare locale:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (implicit), whisper.cpp și NVIDIA Parakeet, pentru multiplele limbi pe care Whisper le
  recunoaște. Folosește un procesor grafic (GPU) NVIDIA
  prin CUDA atunci când este posibil, altfel folosește procesorul (CPU).
- **Aplicația în limba ta:** Meniuri, butoane și mesaje în 42 de limbi (traduse
  automat și marcate ca atare; corecturile sunt binevenite). Aplicația urmează limba
  sistemului tău sau poți alege una în Setări avansate. Persana, araba și ebraica
  sunt oferite deocamdată pe Windows.
- **14 formate de ieșire:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX și
  PDF, plus formatele oTranscribe, ELAN, InqScribe și Express Scribe. DOCX
  și PDF randează corect toate tipurile de scriere, iar limba persană, arabă și urdu sunt scrise de la dreapta la stânga cu caractere unite.
- **Pagină web ușor de partajat:** salvează o transcriere finalizată ca un singur fișier `.html` care
  funcționează offline în orice browser; dă click pe un cuvânt pentru a-l auzi, caută sau sari la
  capitole.
- **Etichete pentru vorbitori** fără a avea nevoie de un cont Hugging Face, plus marcaje de timp la nivel de cuvânt și
  decupare pe interval de timp.
- **Sarcinile întrerupte se reiau** de la ultimul punct de control salvat, în loc să o ia
  de la capăt (motorul implicit).
- **Videoclipuri online:** descarcă de pe orice site suportat de [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  și transcrie imediat cum se finalizează descărcarea.
- **Link către videoclip subtitrat:** cu o singură bifă transformă un link în `<titlu>-subbed.mp4`
  cu subtitrările integrate permanent: descărcare, transcriere și integrare într-o singură sarcină
  în coada de așteptare ([docs/SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Live:** transcrie un microfon sau, pe Windows, sunetul sistemului, în timp real
  ([docs/LIVE.md](../LIVE.md)).
- **Coadă de așteptare (Batch) și dosar monitorizat** pentru multe fișiere.
- **Mod rețea locală:** o pagină de transcriere și un API compatibil OpenAI pentru
  celelalte dispozitive din rețeaua ta ([docs/SERVER.md](../SERVER.md)).
- **Opționale, dezactivate implicit:** instrumente AI pentru o transcriere finalizată (rezumat,
  întrebări, SRT bilingv), și transformare din text în voce offline, cu clonarea vocii.

Cum se compară cu Subtitle Edit, Vibe, Buzz, noScribe și aTrain,
inclusiv când o altă aplicație este o alegere mai bună:
**[docs/COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Descărcare

Cea mai recentă lansare: **[releases page](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| Fișier | Pentru |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 sau 11, 64-bit. Majoritatea oamenilor doresc această versiune. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows fără instalare: dezarhivează și rulează. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Mac-uri cu procesor Apple Silicon, macOS 14 sau mai nou. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Mac-uri cu procesor Intel, macOS 10.15 sau mai nou. |

Linux rulează din codul sursă: [platform/linux/README.md](../../platform/linux/README.md).

Versiunea inclusă a FFmpeg este o variantă GPL. Codul sursă corespunzător este atașat fiecărei lansări sub formă de
fișiere `WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*`; linkurile exacte sunt în
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

ffmpeg și yt-dlp sunt incluse în pachet. La prima lansare, o fereastră de pornire rapidă îți alege
modelul de vorbire pentru limba ta: Fast (Mic, aproximativ 500 MB) sau Best
quality (până la aproximativ 3 GB); se descarcă o singură dată, la prima utilizare. Ai nevoie de aproximativ 8 GB
de memorie RAM; pe un procesor (CPU), modelele Mari (Large) durează de aproximativ 1,5–2,5 ori lungimea
fișierului audio, iar cele Mici (Small) aproximativ jumătate, însă pe o placă video NVIDIA procesul este mult mai rapid. Build-urile de Windows nu sunt semnate digital, iar cele de Mac nu sunt
notarizate, așa că SmartScreen și Gatekeeper vor afișa un avertisment la prima lansare;
[docs/INSTALL.md](../INSTALL.md) arată pe ce trebuie să dai click. Pentru a actualiza, rulează noul
instalator peste cel vechi; setările se vor păstra.

**Descărcări după versiune** (fiecare ecuson numără doar
lansarea acelei versiuni — versiunile mai vechi rămân publicate, iar contoarele lor nu sunt niciodată
resetate):

[![v2.1.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.1.0/total?label=v2.1.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.1.0)
[![v2.0.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.0.0/total?label=v2.0.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0)
[![v1.9.3](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.3/total?label=v1.9.3&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.3)
[![v1.9.1](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.1/total?label=v1.9.1&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.1)
[![v1.9.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.0/total?label=v1.9.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.0)
[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

## Ce pleacă de pe computerul tău

Cu setările implicite, sunetul și transcrierile tale rămân pe computerul tău.
Aplicația folosește rețeaua pentru:

- a descărca un model sau o componentă opțională prima dată când este necesară;
- setările sale online la pornire și o verificare zilnică a actualizărilor pe GitHub, care
  doar îți spune despre o versiune nouă;
- statistici de utilizare, activate implicit, după fiecare transcriere finalizată: model,
  limbă, durate, număr de cuvinte, versiunea aplicației, sistemul de operare, CPU și
  memoria, precum și regiunea, însă niciodată numele fișierului. Dezactivează-le la
  **Help → Usage statistics**.

Sunetul sau textul transcris este trimis doar dacă alegi un motor bazat pe cloud (Gemini API
sau Google Cloud Speech-to-Text) sau dacă conectezi singur un furnizor AI extern.
**File → Work offline** oprește tot traficul. Orice conexiune este listată în
[docs/CONFIG.md](../CONFIG.md#network-use).

## Documentație

[Instalare](../INSTALL.md) · [Configurare](../CONFIG.md) ·
[Transcriere în timp real](../LIVE.md) · [Mod rețea locală și API](../SERVER.md) ·
[Motoare Cloud](../CLOUD_STT.md) · [Arhitectură](../ARCHITECTURE.md) ·
[Jurnalul modificărilor](../CHANGELOG.md) · [Toate documentele](../README.md)

## Construiește din codul sursă

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Necesită Python 3.11 sau mai nou. Procesul de construcție: [docs/BUILD.md](../BUILD.md). Teste și cereri de pull (pull requests):
[CONTRIBUTING.md](../../CONTRIBUTING.md).

## Contribuții și contact

- **Probleme (Bugs) și cereri de noi funcții:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Întrebări și idei:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Orice altceva:** prin e-mail, folosind
  [secțiunea de Contact a site-ului](https://whisper-transcriber-suite.pages.dev/#contact)
- **Raportare probleme de securitate:** [SECURITY.md](../../SECURITY.md)

Acest proiect respectă [Contributor Covenant](../../.github/CODE_OF_CONDUCT.md).
Dacă aplicația îți salvează timp, o Steluță (Star) în partea de sus a acestei pagini va ajuta și alte persoane
să o descopere.

## Cum este dezvoltat acest proiect

Mentenantorul îl dezvoltă cu ajutorul masiv al asistenților de programare AI (în principal Claude). Verificările de tipuri
și testele unitare trebuie să treacă înainte de fiecare commit, iar sistemul de integrare continuă (CI) le rulează din nou pe Windows și Linux după
fiecare push. [Lista de verificare pentru lansare](../RELEASE_PROCESS.md) include un test manual de instalare pe o
mașină fizică reală. Commit-urile făcute cu ajutorul AI includ acum numele modelului pe o linie `Assisted-by:`; multe dintre cele mai vechi
conțin în schimb o linie `Co-Authored-By: Claude`.

## Licență

Drepturi de autor (c) 2026 translation-robot (co-author). Proiectul se află în acest depozit,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
Codul sursă propriu al proiectului este sub [BSD 3-Clause License](../../LICENSE). Instrumentele
incluse, runtime-ul Python și modelele își păstrează propriile licențe; vezi
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
