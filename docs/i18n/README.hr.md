<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: zvuk ulazi, tekst izlazi. Besplatna transkripcija otvorenog koda koja pokreće Whisper na vašem računalu." width="100%">

# Whisper Transcriber Suite

**Besplatna, offline transkripcija i titlovi za duge snimke na vašem jeziku — na običnom laptopu, bez računa i bez učitavanja zvuka na internet.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![downloads](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/total?label=downloads&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Preuzmite za Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS i Linux: pogledajte [Preuzimanje](#download).

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
<b>Hrvatski</b> ·
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

## Za koga je ovo

Za autore titlova, prevoditelje, istraživače i novinare koji duge snimke (intervjue, predavanja, govore, videozapise) pretvaraju u tekst ili titlove.
Ubacite audio ili video datoteku i transkript će biti ispisan pored nje. Sustav za prepoznavanje govora radi na vašem računalu, tako da
nema troškova po minuti, a nakon preuzimanja modela, nije potrebna internetska veza.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="Kartica Transcribe: mjesto za ubacivanje datoteka, odabir sustava i jezika, opcije za oznake govornika i vremenske oznake za svaku riječ" width="80%">
</div>

## Što je novo u 2.0

- **Brzina i preostalo vrijeme:** kartica Queue prikazuje brzinu svakog posla i grubo preostalo vrijeme.
- **Titlani video s poveznice:** preuzimanje, transkripcija i ugrađivanje titlova kao jedan posao ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Transkript kao web stranica:** jedna `.html` datoteka s pretragom i funkcijom "klikni za slušanje" koja radi offline u bilo kojem pregledniku.
- **Provjerljiv rad offline:** s uključenim Work offline, statusna linija pokazuje ima li aplikacija ili proces koji je ona pokrenula mrežnu vezu.
- **Prevedi na engleski:** govor koji nije na engleskom postaje engleski titl u jednom prolazu.
- **Brzi početak:** nove instalacije postavljaju tri pitanja, a probna snimka od 18 sekundi odmah prikazuje rezultat.
- **Prijavite problem** iz Help-a, bez GitHub računa.
- **macOS:** izbornik aplikacije sa Settings (Command-zarez), Light i Dark načinom koji prate sustav, obavijesti. **Windows:** napredak na programskoj traci i tamne naslovne trake.

Cijeli popis: [CHANGELOG](../CHANGELOG.md).

## Značajke

- **Lokalni sustavi:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (zadano), whisper.cpp i NVIDIA Parakeet, za mnoge jezike koje Whisper
  prepoznaje. Koristi NVIDIA grafičku karticu (GPU)
  kroz CUDA kada je to moguće, inače procesor (CPU).
- **Aplikacija na vašem jeziku:** Izbornici, gumbi i poruke na 42 jezika (strojno
  prevedeno i tako označeno; ispravci su dobrodošli). Prati jezik vašeg sustava, a
  jezik možete odabrati i u Naprednim postavkama. Perzijski, arapski i hebrejski za
  sada su dostupni u sustavu Windows.
- **14 izlaznih formata:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX i
  PDF, plus oTranscribe, ELAN, InqScribe i Express Scribe formati. DOCX
  i PDF iscrtavaju svako pismo, a perzijski, arapski i urdu čitaju se zdesna nalijevo
  sa spojenim slovima.
- **Web stranica za dijeljenje:** spremite gotov transkript kao jednu `.html` datoteku koja
  radi offline u bilo kojem pregledniku; kliknite na riječ da biste je čuli, pretražujte, preskačite na poglavlja.
- **Oznake govornika** bez Hugging Face računa, plus vremenske oznake za svaku riječ i
  izrezivanje vremenskog raspona.
- **Prekinuti poslovi se nastavljaju** sa zadnje spremljene točke umjesto da počinju
  ispčetka (zadani sustav).
- **Online videozapisi:** preuzmite s bilo koje stranice koju [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  podržava i transkribirajte kada se preuzimanje završi.
- **Poveznica na titlani video:** jedna kvačica pretvara poveznicu u `<title>-subbed.mp4`
  s ugrađenim titlovima: preuzmite, transkribirajte i ugradite u jednom poslu iz reda čekanja
  ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Uživo:** transkribirajte mikrofon, ili sistemski zvuk na Windowsu, dok se
  događa ([../LIVE.md](../LIVE.md)).
- **Skupni red čekanja i nadzirana mapa** za mnogo datoteka.
- **Način lokalne mreže:** stranica za transkripciju i OpenAI-kompatibilan API za
  druge uređaje na vašoj mreži ([../SERVER.md](../SERVER.md)).
- **Opcionalno, zadano isključeno:** AI alati za gotov transkript (sažetak,
  pitanja, dvojezični SRT), i offline tekst u glas s kloniranjem glasa.

Kako se uspoređuje sa Subtitle Edit, Vibe, Buzz, noScribe i aTrain,
uključujući i situacije kada je druga aplikacija bolji odabir:
**[../COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Preuzimanje

Najnovija verzija: **[stranica s izdanjima](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| Datoteka | Za koga |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 ili 11, 64-bita. Većina ljudi želi ovo. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows bez instalacije: raspakirajte i pokrenite. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Mac računala s Apple silicon čipovima, macOS 14 ili noviji. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Intel Mac računala, macOS 10.15 ili noviji. |

Linux se pokreće iz izvornog koda: [../../platform/linux/README.md](../../platform/linux/README.md).

Uključeni FFmpeg je GPL verzija. Njegov odgovarajući izvorni kod je priložen uz svako izdanje kao
`WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*` datoteke; točne poveznice su u
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

ffmpeg i yt-dlp su uključeni u paket. Pri prvom pokretanju prozor za brzi početak bira
model govora za vaš jezik: Fast (Mali, oko 500 MB) ili Best
quality (do oko 3 GB); preuzima se jednom, prilikom prvog korištenja. Planirajte 8 GB
RAM-a; na procesoru (CPU) velikim je modelima potrebno oko 1,5–2,5 puta više vremena od
trajanja same audio snimke, a malim modelima oko polovice tog vremena, NVIDIA GPU je mnogo brži. Windows verzije nisu digitalno potpisane, a Mac verzije nisu
notarizirane, tako da SmartScreen i Gatekeeper upozoravaju pri prvom pokretanju;
[../INSTALL.md](../INSTALL.md) pokazuje na što treba kliknuti. Za ažuriranje, pokrenite
noviji instalater preko starog; postavke ostaju sačuvane.

**Preuzimanja po verziji** (svaka značka broji samo izdanje
te verzije — starije verzije ostaju objavljene i njihovi brojevi se nikada
ne resetiraju):

[![all versions](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/total?label=all%20versions&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases)
[![v2.1.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.1.0/total?label=v2.1.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.1.0)
[![v2.0.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.0.0/total?label=v2.0.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0)
[![v1.9.3](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.3/total?label=v1.9.3&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.3)
[![v1.9.1](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.1/total?label=v1.9.1&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.1)
[![v1.9.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.0/total?label=v1.9.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.0)
[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

## Što napušta vaše računalo

Uz zadane postavke vaš audio i transkripti ostaju na vašem računalu.
Aplikacija ipak koristi mrežu za:

- preuzimanje modela ili opcionalne komponente prvi put kada je to potrebno;
- svoje online postavke pri pokretanju i dnevnu provjeru ažuriranja na GitHub-u, što
  vas samo obavještava o novoj verziji;
- statistiku korištenja, uključenu prema zadanim postavkama, nakon svake završene transkripcije: model,
  jezik, trajanja, broj riječi, verzija aplikacije, operativni sustav, procesor i
  veličina memorije, i regija, nikada ime datoteke. Isključite to pod
  **Help → Usage statistics**.

Audio ili tekst transkripta se šalju samo ako odaberete cloud sustav (Gemini API
ili Google Cloud Speech-to-Text) ili sami povežete udaljenog AI pružatelja.
**File → Work offline** zaustavlja sve to. Svaka konekcija je navedena u
[../CONFIG.md](../CONFIG.md#network-use).

## Dokumentacija

[Instalacija](../INSTALL.md) · [Konfiguracija](../CONFIG.md) ·
[Transkripcija uživo](../LIVE.md) · [Način lokalne mreže i API](../SERVER.md) ·
[Cloud sustavi](../CLOUD_STT.md) · [Arhitektura](../ARCHITECTURE.md) ·
[Dnevnik promjena](../CHANGELOG.md) · [Svi dokumenti](../README.md)

## Izgradnja iz izvornog koda

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Zahtijeva Python 3.11 ili noviji. Proces izgradnje: [../BUILD.md](../BUILD.md). Testovi i zahtjevi za povlačenje (pull requests):
[../../CONTRIBUTING.md](../../CONTRIBUTING.md).

## Doprinosi i kontakt

- **Bugovi i zahtjevi za novim značajkama:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Pitanja i ideje:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Sve ostalo:** putem e-pošte, preko
  [odjeljka Contact na web stranici](https://whisper-transcriber-suite.com/#contact) · ✉ [admin@whisper-transcriber-suite.com](mailto:admin@whisper-transcriber-suite.com)
- **Prijave sigurnosnih propusta:** [../../SECURITY.md](../../SECURITY.md)

Ovaj projekt prati [Zavjet suradnika (Contributor Covenant)](../../.github/CODE_OF_CONDUCT.md).
Ako vam aplikacija štedi vrijeme, zvjezdica na vrhu ove stranice pomaže drugim ljudima
da je pronađu.

## Kako se gradi ovaj projekt

Održavatelj ga razvija uz veliku pomoć AI asistenata za kodiranje (uglavnom Claude). Provjere tipova
i jedinični testovi moraju proći prije svakog commita, a CI ih ponovno pokreće na Windowsu i Linuxu nakon
svakog pusha. [Kontrolna lista za izdanje](../RELEASE_PROCESS.md) uključuje ručni test instalacije na
pravom računalu. Commiti napravljeni uz pomoć AI sada navode model u liniji `Assisted-by:`; mnogi stariji
nose liniju `Co-Authored-By: Claude` umjesto toga.

## Licenca

Autorska prava (c) 2026 translation-robot (koautor). Projekt živi u ovom repozitoriju,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
Sam izvorni kod projekta je pod [BSD 3-Clause licencom](../../LICENSE). Uključeni
alati, Python okruženje i modeli zadržavaju svoje vlastite licence; pogledajte
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
