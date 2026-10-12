<div align="center">

<img src="../img/hero.png" alt="Whisper Transcriber Suite: garsas įeina, tekstas išeina. Nemokama, atvirojo kodo transkribavimo programa, kuri naudoja Whisper jūsų pačių kompiuteryje." width="100%">

# Whisper Transcriber Suite

**Nemokamas, neprisijungus veikiantis ilgų įrašų transkribavimas ir subtitravimas jūsų kalba — naudojant įprastą nešiojamąjį kompiuterį, be paskyros ir be garso failų įkėlimo.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Atsisiųsti „Windows“ operacinei sistemai](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

„macOS“ ir „Linux“: žiūrėkite [Atsisiuntimas](#download).

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
<b>Lietuvių</b> ·
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

## Kam tai skirta

Subtitruotojams, vertėjams, tyrėjams ir žurnalistams, kurie ilgus
įrašus (interviu, paskaitas, pokalbius, vaizdo įrašus) paverčia tekstu ar subtitrais.
Įkelkite garso ar vaizdo failą, ir transkripcija bus išsaugota šalia jo. Kalbos variklis veikia jūsų pačių kompiuteryje, todėl nėra
minutės mokesčio, o atsisiuntus modelį, nereikia jokio interneto
ryšio.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="„Transcribe“ kortelė: įmetimo vieta, variklio ir kalbos pasirinkimai, kalbėtojo etiketės ir žodžio laiko žymos parinktys" width="80%">
</div>

## Kas naujo 2.0 versijoje

- **Greitis ir likęs laikas:** „Queue“ kortelė rodo kiekvienos užduoties greitį ir apytikslį likusį laiką.
- **Vaizdo įrašas su subtitrais iš nuorodos:** atsisiųskite, transkribuokite ir įrašykite subtitrus kaip vieną užduotį ([docs/SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Transkripcija kaip tinklalapis:** vienas `.html` failas su paieška ir atkūrimu paspaudus, veikiantis neprisijungus bet kurioje naršyklėje.
- **Patikrinamas darbas neprisijungus:** įjungus „Work offline“, būsenos eilutė rodo, ar programa, ar jos paleistas procesas turi tinklo ryšį.
- **Vertimas į anglų kalbą:** ne angliška kalba paverčiama angliškais subtitrais vienu ypu.
- **Greita pradžia:** naujai įdiegus, užduodami trys klausimai, o 18 sekundžių pavyzdinis klipas iškart parodo rezultatą.
- **Pranešti apie problemą** iš meniu „Help“, be „GitHub“ paskyros.
- **macOS:** programos meniu su „Settings“ (Command kablelis), šviesia ir tamsia tema, atitinkančia sistemą, bei pranešimais. **Windows:** užduočių juostos eigos indikatorius ir tamsios antraščių juostos.

Visas sąrašas: [CHANGELOG](../CHANGELOG.md).

## Funkcijos

- **Vietiniai varikliai:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (numatytasis), whisper.cpp ir NVIDIA Parakeet, daugeliui „Whisper“ atpažįstamų kalbų. Naudoja NVIDIA vaizdo plokštę (GPU)
  per CUDA, kai tik įmanoma, kitu atveju – procesorių (CPU).
- **Programa jūsų kalba:** Meniu, mygtukai ir pranešimai 42 kalbomis (išversta
  automatiškai ir pažymėta kaip tokia; pataisymai laukiami). Programa seka jūsų
  sistemos kalbą arba kalbą galite pasirinkti išplėstiniuose nustatymuose. Persų,
  arabų ir hebrajų kalbos kol kas siūlomos sistemoje Windows.
- **14 išvesties formatų:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX ir
  PDF, taip pat oTranscribe, ELAN, InqScribe ir Express Scribe formatai. DOCX
  ir PDF atvaizduoja kiekvieną raštą, o persų, arabų ir urdu kalbos rašomos iš dešinės į kairę, sujungtomis raidėmis.
- **Tinklalapis dalinimuisi:** išsaugokite baigtą transkripciją kaip vieną `.html` failą,
  kuris veikia neprisijungus bet kurioje naršyklėje; spustelėkite žodį, kad jį išgirstumėte, ieškokite, pereikite prie skyrių.
- **Kalbėtojų etiketės** be „Hugging Face“ paskyros, taip pat žodžių laiko žymos ir
  karpymas pagal laiko intervalą.
- **Nutrauktos užduotys pratęsiamos** nuo paskutinio kontrolinio taško, užuot pradėjus
  iš naujo (numatytasis variklis).
- **Internetiniai vaizdo įrašai:** atsisiųskite iš bet kurios svetainės, kurią palaiko [yt-dlp](https://github.com/yt-dlp/yt-dlp),
  ir transkribuokite pasibaigus atsisiuntimui.
- **Nuoroda į vaizdo įrašą su subtitrais:** viena varnelė nuorodą paverčia į `<pavadinimas>-subbed.mp4`
  su įrašytais subtitrais: atsisiuntimas, transkribavimas ir įrašymas vienoje eilės
  užduotyje ([docs/SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Tiesiogiai (Live):** transkribuokite mikrofoną, arba, „Windows“ sistemoje, sistemos garsą, jam 
  skambant ([docs/LIVE.md](../LIVE.md)).
- **Užduočių eilė ir stebimas aplankas** dideliam failų kiekiui.
- **Vietinio tinklo režimas:** transkribavimo puslapis ir su OpenAI suderinama API
  kitiems jūsų tinklo įrenginiams ([docs/SERVER.md](../SERVER.md)).
- **Pasirinktinai, išjungta pagal nutylėjimą:** AI įrankiai baigtai transkripcijai (santrauka,
  klausimai, dvikalbis SRT) ir teksto vertimas į balsą neprisijungus, naudojant balso klonavimą.

Kaip tai lyginama su Subtitle Edit, Vibe, Buzz, noScribe ir aTrain,
įskaitant atvejus, kai geresnis pasirinkimas yra kita programa:
**[docs/COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Atsisiuntimas

Naujausias leidimas: **[releases page](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| Failas | Skirta |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 arba 11, 64-bit. Daugumai žmonių reikia šio. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows be diegimo: išarchyvuokite ir paleiskite. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Mac su Apple Silicon, macOS 14 ar naujesne versija. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Intel Mac, macOS 10.15 ar naujesne versija. |

Linux veikia iš šaltinio kodo: [platform/linux/README.md](../../platform/linux/README.md).

Pridėtas FFmpeg yra GPL versija. Atitinkamas jo šaltinio kodas pridedamas prie kiekvieno leidimo kaip
`WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*` failai; tikslios nuorodos yra
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) faile.

ffmpeg ir yt-dlp yra įtraukti. Pirmą kartą paleidus, greitosios pradžios langas parenka
kalbos modelį jūsų kalbai: Fast (Mažas, apie 500 MB) arba Best
quality (iki maždaug 3 GB); jis atsisiunčiamas vieną kartą, per pirmąjį naudojimą. Planuokite 8 GB
RAM atminties; procesoriuje (CPU) didelių (Large) modelių apdorojimas trunka apie 1,5–2,5 karto ilgiau nei 
garso įrašas, o mažų (Small) – apie pusę to laiko, su NVIDIA GPU procesas vyksta žymiai greičiau. Windows versijos nėra pasirašytos kodu, o Mac versijos nėra
notarizuotos, todėl SmartScreen ir Gatekeeper pirmą kartą paleidus įspės;
[docs/INSTALL.md](../INSTALL.md) rodo, ką reikia spustelėti. Norėdami atnaujinti, paleiskite
naujesnę diegimo programą ant senosios; nustatymai išlieka.

**Atsisiuntimai pagal versiją** (kiekvienas ženklelis skaičiuoja tik
tos versijos leidimą — senesnės versijos lieka paskelbtos ir jų skaičiai niekada
nenunulinami):

[![v2.1.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.1.0/total?label=v2.1.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.1.0)
[![v2.0.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.0.0/total?label=v2.0.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0)
[![v1.9.3](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.3/total?label=v1.9.3&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.3)
[![v1.9.1](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.1/total?label=v1.9.1&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.1)
[![v1.9.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.0/total?label=v1.9.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.0)
[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

## Kas palieka jūsų kompiuterį

Pagal numatytuosius nustatymus garso įrašai ir transkripcijos lieka jūsų kompiuteryje.
Programa naudoja tinklą:

- atsisiųsti modelį ar pasirenkamą komponentą, kai jo prireikia pirmą kartą;
- atnaujinti internetinius nustatymus paleidimo metu ir kasdien patikrinti atnaujinimus „GitHub“, kas
  tik praneša apie naują versiją;
- naudojimo statistikai, kuri pagal nutylėjimą įjungta, po kiekvienos baigtos transkripcijos: modeliui,
  kalbai, trukmei, žodžių skaičiui, programos versijai, operacinei sistemai, CPU ir
  atminties dydžiui bei regionui; failo pavadinimas niekada nesiunčiamas. Išjunkite tai per
  **Help → Usage statistics**.

Garsas arba transkripcijos tekstas siunčiamas tik tuo atveju, jei pasirenkate debesies variklį („Gemini API“
arba „Google Cloud Speech-to-Text“) arba patys prijungiate nuotolinį AI tiekėją.
**File → Work offline** sustabdo visa tai. Kiekvienas ryšys išvardytas
[docs/CONFIG.md](../CONFIG.md#network-use) faile.

## Dokumentacija

[Diegimas](../INSTALL.md) · [Konfigūracija](../CONFIG.md) ·
[Tiesioginis transkribavimas](../LIVE.md) · [Vietinio tinklo režimas ir API](../SERVER.md) ·
[Debesies varikliai](../CLOUD_STT.md) · [Architektūra](../ARCHITECTURE.md) ·
[Pakeitimų žurnalas](../CHANGELOG.md) · [Visi dokumentai](../README.md)

## Kompiliavimas iš šaltinio kodo

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Reikia „Python“ 3.11 ar naujesnės versijos. Kompiliavimo procesai: [docs/BUILD.md](../BUILD.md). Testai ir „pull“ užklausos (pull requests):
[CONTRIBUTING.md](../../CONTRIBUTING.md).

## Prisidėjimas ir kontaktai

- **Klaidos ir naujų funkcijų užklausos:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Klausimai ir idėjos:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Visa kita:** el. paštu, per
  [svetainės „Contact“ skiltį](https://whisper-transcriber-suite.pages.dev/#contact)
- **Saugumo ataskaitos:** [SECURITY.md](../../SECURITY.md)

Šis projektas laikosi [Contributor Covenant](../../.github/CODE_OF_CONDUCT.md).
Jei programa sutaupo jums laiko, žvaigždutė (Star) šio puslapio viršuje padės kitiems
žmonėms ją rasti.

## Kaip kuriamas šis projektas

Prižiūrėtojas jį kuria naudodamasis didele AI programavimo padėjėjų (daugiausia „Claude“) pagalba. Tipų patikrinimai
ir vienetų testai turi būti sėkmingi prieš kiekvieną pakeitimą (commit), o CI juos dar kartą paleidžia „Windows“ ir „Linux“ sistemose po
kiekvieno išsiuntimo (push). [Išleidimo kontrolinis sąrašas](../RELEASE_PROCESS.md) apima rankinį diegimo testą
tikrame kompiuteryje. Pakeitimai, padaryti su AI pagalba, dabar nurodo modelį `Assisted-by:` eilutėje; daugelyje senesnių
vietoj to yra `Co-Authored-By: Claude` eilutė.

## Licencija

Autorių teisės (c) 2026 translation-robot (co-author). Projektas yra šioje saugykloje,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
Pats projekto šaltinio kodas yra apsaugotas [BSD 3-Clause License](../../LICENSE). Pridėti
įrankiai, „Python“ vykdymo aplinka ir modeliai išlaiko savo licencijas; žiūrėkite
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
