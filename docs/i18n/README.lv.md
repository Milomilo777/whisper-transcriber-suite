<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**Bezmaksas bezsaistes transkripcija un subtitri gariem ierakstiem jūsu valodā — parastā klēpjdatorā, bez konta un bez audio augšupielādes.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [⬇ Lejupielādēt sistēmai Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS un Linux: skatiet [Lejupielāde](#download).

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
<b>Latviešu</b> ·
<a href="README.ca.md">Català</a> ·
<a href="README.bn.md">বাংলা</a> ·
<a href="README.fil.md">Filipino</a>
</p>

<!-- language-links:end -->

<!-- translated from README.md at commit 66585d5 -->

</div>

## Kam tas ir paredzēts

Subtitrētājiem, tulkotājiem, pētniekiem un žurnālistiem, kuri garus
ierakstus (intervijas, lekcijas, sarunas, video) pārvērš tekstā vai subtitros.
Ievelciet audio vai video failu, un transkripts tiks saglabāts tajā pašā mapē. Runas dzinējs darbojas jūsu datorā, tādēļ nav
maksas par minūti, un, kad modelis ir lejupielādēts, interneta savienojums
nav nepieciešams.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="Cilne Transcribe: vieta failu nomešanai, dzinēja un valodas izvēle, runātāju etiķešu un vārdu laikspiedolu opcijas" width="80%">
</div>

## Kas jauns 2.0 versijā

- **Ātrums un atlikušais laiks:** Cilnē Rinda ir redzams katra darba ātrums un aptuvenais atlikušais laiks.
- **Video ar subtitriem no saites:** lejupielādēt, transkribēt un iestrādāt subtitrus kā vienu darbu ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Transkripts kā tīmekļa lapa:** viens `.html` fails ar meklēšanu un atskaņošanu klikšķinot, kas darbojas bezsaistē jebkurā pārlūkprogrammā.
- **Bezsaistes statusa pārbaude:** ja ir ieslēgts Darbs bezsaistē, statusa rinda parāda, vai lietotnei vai tās sāktam procesam ir tīkla savienojums.
- **Tulkot angļu valodā:** citu valodu runa tiek pārvērsta angļu subtitros vienā posmā.
- **Ātrā sākšana:** jaunas instalācijas uzdod trīs jautājumus, un 18 sekunžu parauga klips uzreiz parāda rezultātu.
- **Ziņot par problēmu** no sadaļas Palīdzība, bez GitHub konta.
- **macOS:** lietotnes izvēlne ar Iestatījumiem (Command-komats), gaišais un tumšais režīms atbilstoši sistēmai, paziņojumi. **Windows:** progresa josla uzdevumjoslā un tumšas virsrakstjoslas.

Pilns saraksts: [CHANGELOG](../CHANGELOG.md).

## Funkcijas

- **Lokālie dzinēji:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (noklusējums), whisper.cpp un NVIDIA Parakeet daudzām valodām, ko Whisper
  atpazīst. Izmanto NVIDIA GPU
  caur CUDA, ja iespējams, pretējā gadījumā CPU.
- **Lietotne jūsu valodā:** Izvēlnes, pogas un ziņojumi 42 valodās (mašīntulkoti un
  tā atzīmēti; labojumi ir gaidīti). Lietotne seko sistēmas valodai, vai arī valodu
  var izvēlēties papildu iestatījumos. Persiešu, arābu un ivrita valoda pagaidām ir
  pieejama sistēmā Windows.
- **14 izvades formāti:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX un
  PDF, kā arī oTranscribe, ELAN, InqScribe un Express Scribe formāti. DOCX
  un PDF atbalsta visus rakstus, bet persiešu, arābu un urdu tiek lasīti no labās uz kreiso
  ar savienotiem burtiem.
- **Koplietojama tīmekļa lapa:** saglabājiet pabeigtu transkriptu kā vienu `.html` failu, kas
  darbojas bezsaistē jebkurā pārlūkprogrammā; noklikšķiniet uz vārda, lai to dzirdētu, meklējiet, pārejiet uz
  nodaļām.
- **Runātāju atpazīšana** bez Hugging Face konta, kā arī vārdu laikspiedoli un
  laika diapazona apgriešana.
- **Pārtraukti darbi turpinās** no pēdējā saglabāšanas punkta, nevis tiek sākti
  no jauna (noklusējuma dzinējs).
- **Tiešsaistes video:** lejupielādējiet no jebkuras vietnes, ko atbalsta [yt-dlp](https://github.com/yt-dlp/yt-dlp),
  un transkribējiet, kad lejupielāde ir pabeigta.
- **Saite uz video ar subtitriem:** viena atzīme pārvērš saiti par `<title>-subbed.mp4`
  ar iestrādātiem subtitriem: lejupielādēt, transkribēt un iestrādāt kā vienu uzdevumu rindā
  ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Tiešraide:** transkribējiet mikrofonu vai sistēmas audio (Windows) reāllaikā,
  kamēr tas notiek ([../LIVE.md](../LIVE.md)).
- **Pakešapstrādes rinda (batch) un uzraudzītā mape** daudziem failiem.
- **Lokālā tīkla režīms:** transkripcijas lapa un OpenAI saderīgs API
  citām ierīcēm jūsu tīklā ([../SERVER.md](../SERVER.md)).
- **Pēc izvēles, pēc noklusējuma izslēgts:** AI rīki pabeigtam transkriptam (kopsavilkums,
  jautājumi, divvalodu SRT) un bezsaistes teksta pārvēršana runā ar balss klonēšanu.

Kā tas salīdzināms ar Subtitle Edit, Vibe, Buzz, noScribe un aTrain,
tostarp, kad cita lietotne ir labāka izvēle:
**[../COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Lejupielāde

Jaunākais laidiens: **[laidienu lapa](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| Fails | Paredzēts |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 vai 11, 64 bitu. Lielākajai daļai cilvēku būs nepieciešams šis. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows bez instalēšanas: atpakojiet un palaidiet. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Mac ar Apple Silicon, macOS 14 vai jaunāka. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Intel Mac, macOS 10.15 vai jaunāka. |

Linux darbojas no pirmkoda: [../platform/linux/README.md](../../platform/linux/README.md).

Komplektā iekļautais FFmpeg ir GPL būvējums. Tā atbilstošais pirmkods ir pievienots katram laidienam kā
`WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*` faili; precīzas saites ir atrodamas šeit:
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

ffmpeg un yt-dlp ir iekļauti komplektā. Pirmajā palaišanas reizē ātrās palaišanas logs izvēlas
runas modeli jūsu valodai: Ātrs (Small, aptuveni 500 MB) vai Vislabākā
kvalitāte (līdz aptuveni 3 GB); tas tiek lejupielādēts vienu reizi, pirmajā lietošanas reizē. Rēķinieties ar nepieciešamību pēc 8 GB RAM; izmantojot CPU, Large modeļu apstrāde aizņem aptuveni 1,5–2,5 reizes vairāk laika nekā
audio garums, bet Small aptuveni pusi; NVIDIA GPU ir daudz ātrāks. Windows versijām nav koda paraksta, un Mac versijām nav
notariāla apstiprinājuma, tādēļ SmartScreen un Gatekeeper brīdina pirmajā palaišanas reizē;
[../INSTALL.md](../INSTALL.md) parāda, uz ko jānoklikšķina. Lai atjauninātu, vienkārši palaidiet jaunāko
instalēšanas programmu virs vecās; iestatījumi tiek saglabāti.

**Lejupielādes pēc versijas** (katra nozīmīte skaita tikai konkrētās versijas
laidienu — vecākas versijas paliek publicētas un to skaits nekad
netiek atiestatīts):

[![v2.1.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.1.0/total?label=v2.1.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.1.0)
[![v2.0.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.0.0/total?label=v2.0.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0)
[![v1.9.3](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.3/total?label=v1.9.3&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.3)
[![v1.9.1](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.1/total?label=v1.9.1&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.1)
[![v1.9.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.0/total?label=v1.9.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.0)
[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

## Kādi dati pamet jūsu datoru

Ar noklusējuma iestatījumiem jūsu audio un transkripti paliek jūsu datorā.
Lietotne izmanto tīklu šādiem mērķiem:

- modeļa vai papildu komponenta lejupielādei pirmajā reizē, kad tas ir nepieciešams;
- tiešsaistes iestatījumu pārbaudei startēšanas laikā un ikdienas atjauninājumu pārbaudei pakalpojumā GitHub, kas
  tikai informē par jaunu versiju;
- lietošanas statistikai, kas ir ieslēgta pēc noklusējuma, pēc katras pabeigtas transkripcijas: modelis,
  valoda, ilgums, vārdu skaits, lietotnes versija, operētājsistēma, CPU un
  atmiņas lielums, kā arī reģions, nekad netiek sūtīts faila nosaukums. To var izslēgt sadaļā
  **Help → Usage statistics**.

Audio vai transkripta teksts tiek sūtīts tikai tad, ja izvēlaties mākoņpakalpojuma dzinēju (Gemini API
vai Google Cloud Speech-to-Text) vai pats pievienojat attālu AI pakalpojumu sniedzēju.
**File → Work offline** aptur to visu. Visi savienojumi ir uzskaitīti šeit:
[../CONFIG.md](../CONFIG.md#network-use).

## Dokumentācija

[Instalēšana](../INSTALL.md) · [Konfigurācija](../CONFIG.md) ·
[Tiešraides transkripcija](../LIVE.md) · [Lokālā tīkla režīms un API](../SERVER.md) ·
[Mākoņpakalpojuma dzinēji](../CLOUD_STT.md) · [Arhitektūra](../ARCHITECTURE.md) ·
[Izmaiņu žurnāls](../CHANGELOG.md) · [Visa dokumentācija](../README.md)

## Būvēt no pirmkoda

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Nepieciešama Python 3.11 vai jaunāka versija. Būvēšanas konveijeri: [../BUILD.md](../BUILD.md). Testi un pull pieprasījumi:
[../../CONTRIBUTING.md](../../CONTRIBUTING.md).

## Līdzdalība un saziņa

- **Kļūdu ziņojumi un funkciju pieprasījumi:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Jautājumi un idejas:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Viss pārējais:** pa e-pastu, izmantojot
  [mājaslapas saziņas sadaļu](https://whisper-transcriber-suite.com/#contact)
- **Drošības ziņojumi:** [../../SECURITY.md](../../SECURITY.md)

Šis projekts ievēro [Contributor Covenant](../../.github/CODE_OF_CONDUCT.md).
Ja lietotne ietaupa jūsu laiku, zvaigznīte (Star) šīs lapas augšpusē palīdzēs citiem
to atrast.

## Kā šis projekts ir veidots

Uzturētājs to izstrādā ar lielu palīdzību no mākslīgā intelekta kodēšanas asistentiem (galvenokārt Claude). Tipu pārbaudēm
un vienībtestiem jābūt veiksmīgiem pirms katra apstiprinājuma (commit), un CI tos vēlreiz palaiž sistēmās Windows un Linux pēc
katras izmaiņu sūtīšanas (push). [Izlaidumu kontrolsaraksts](../RELEASE_PROCESS.md) ietver manuālas instalēšanas testu
reālā datorā. Apstiprinājumos, kas veikti ar MI palīdzību, tagad ir norādīts modelis rindā `Assisted-by:`; daudzos vecākos
apstiprinājumos tā vietā ir rinda `Co-Authored-By: Claude`.

## Licence

Autortiesības (c) 2026 translation-robot (līdzautors). Projekts atrodas šajā repozitorijā,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
Projekta paša pirmkods ir saskaņā ar [BSD 3-Clause License](../../LICENSE). Iekļautie
rīki, Python izpildes vide un modeļi saglabā savas licences; skatiet
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
