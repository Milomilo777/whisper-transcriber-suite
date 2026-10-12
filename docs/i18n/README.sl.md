<div align="center">

<img src="../img/hero.png" alt="Whisper Transcriber Suite: zvok noter, besedilo ven. Brezplačna odprtokodna transkripcija, ki poganja Whisper na vašem računalniku." width="100%">

# Whisper Transcriber Suite

**Brezplačna transkripcija in podnapisi brez povezave za dolge posnetke v vašem jeziku — na navadnem prenosniku, brez računa in brez nalaganja zvoka v splet.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Prenesi za Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS in Linux: glej [Prenos](#download).

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
<b>Slovenščina</b> ·
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

## Za koga je to

Za ustvarjalce podnapisov, prevajalce, raziskovalce in novinarje, ki dolge posnetke (intervjuje, predavanja, govore, videoposnetke) pretvarjajo v besedilo ali podnapise.
Vstavite zvočno ali video datoteko in transkript bo zapisan poleg nje. Sistem za prepoznavanje govora deluje na vašem računalniku, zato
ni stroškov na minuto, po prenosu modela pa internetna povezava ni več potrebna.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="Zavihek Transcribe: prostor za odlaganje datotek, izbira sistema in jezika, možnosti za oznake govorcev in časovne oznake za vsako besedo" width="80%">
</div>

## Kaj je novega v 2.0

- **Hitrost in preostali čas:** zavihek Queue prikazuje hitrost vsakega opravila in približen preostali čas.
- **Videoposnetek s podnapisi iz povezave:** prenos, transkripcija in vgraditev podnapisov kot eno opravilo ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Transkript kot spletna stran:** ena datoteka `.html` z iskanjem in funkcijo "klikni za poslušanje", ki deluje brez povezave v katerem koli brskalniku.
- **Preverljivo delo brez povezave:** z vklopljeno funkcijo Work offline vrstica stanja prikazuje, ali ima aplikacija ali proces, ki ga je sprožila, omrežno povezavo.
- **Prevod v angleščino:** govor, ki ni v angleščini, postane v enem prehodu angleški podnapis.
- **Hiter začetek:** pri novih namestitvah se zastavijo tri vprašanja, 18-sekundni preizkusni posnetek pa takoj prikaže rezultat.
- **Prijavite težavo** v meniju Help, brez računa GitHub.
- **macOS:** meni aplikacije s Settings (Command-vejica), svetlim (Light) in temnim (Dark) načinom, ki sledita sistemu, obvestila. **Windows:** napredek v opravilni vrstici in temne naslovne vrstice.

Celoten seznam: [CHANGELOG](../CHANGELOG.md).

## Funkcije

- **Lokalni sistemi:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (privzeto), whisper.cpp in NVIDIA Parakeet, za številne jezike, ki jih Whisper
  prepozna. Uporablja grafično kartico NVIDIA (GPU)
  prek tehnologije CUDA, ko je to mogoče, sicer pa procesor (CPU).
- **Aplikacija v vašem jeziku:** Meniji, gumbi in sporočila v 42 jezikih (strojno
  prevedeno in kot tako označeno; popravki so dobrodošli). Sledi jeziku sistema,
  jezik pa lahko izberete tudi v Naprednih nastavitvah. Perzijščina, arabščina in
  hebrejščina so zaenkrat na voljo v sistemu Windows.
- **14 izhodnih formatov:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX in
  PDF, ter formati oTranscribe, ELAN, InqScribe in Express Scribe. DOCX
  in PDF izrišeta vsako pisavo, perzijščina, arabščina in urdujščina pa se berejo od desne proti levi
  s povezanimi črkami.
- **Spletna stran za deljenje:** shranite končni transkript kot eno datoteko `.html`, ki
  deluje brez povezave v katerem koli brskalniku; kliknite na besedo, da jo slišite, iščite, preskakujte na poglavja.
- **Oznake govorcev** brez računa Hugging Face, ter časovne oznake za vsako besedo in
  izrezovanje časovnega obsega.
- **Prekinjena opravila se nadaljujejo** z zadnje shranjene točke namesto da bi se začela
  znova (privzeti sistem).
- **Spletni videoposnetki:** prenesite s katere koli strani, ki jo podpira [yt-dlp](https://github.com/yt-dlp/yt-dlp),
  in transkribirajte, ko se prenos zaključi.
- **Povezava do videoposnetka s podnapisi:** ena kljukica spremeni povezavo v `<title>-subbed.mp4`
  z vgrajenimi podnapisi: prenesite, transkribirajte in vgradite v enem opravilu iz čakalne vrste
  ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **V živo:** transkribirajte mikrofon, ali sistemski zvok v sistemu Windows, medtem ko
  se dogaja ([../LIVE.md](../LIVE.md)).
- **Paketna čakalna vrsta in nadzorovana mapa** za veliko datotek.
- **Način lokalnega omrežja:** stran za transkripcijo in API, združljiv z OpenAI, za
  druge naprave v vašem omrežju ([../SERVER.md](../SERVER.md)).
- **Izbirno, privzeto izklopljeno:** orodja AI za končani transkript (povzetek,
  vprašanja, dvojezični SRT) in pretvorba besedila v govor z zvočnim kloniranjem brez povezave.

Kako se primerja s programi Subtitle Edit, Vibe, Buzz, noScribe in aTrain,
vključno s primeri, ko je druga aplikacija boljša izbira:
**[../COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Prenos

Najnovejša različica: **[stran z izdajami](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| Datoteka | Za koga |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 ali 11, 64-bitni. Večina uporabnikov potrebuje to datoteko. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows brez namestitve: razširite (unzip) in zaženite. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Računalniki Mac s čipi Apple silicon, macOS 14 ali novejši. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Računalniki Mac s čipi Intel, macOS 10.15 ali novejši. |

Linux se zažene iz izvorne kode: [../../platform/linux/README.md](../../platform/linux/README.md).

Priloženi FFmpeg je različica GPL. Njegova pripadajoča izvorna koda je priložena vsaki izdaji kot datoteke
`WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*`; točne povezave so v
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

ffmpeg in yt-dlp sta vključena v paket. Ob prvem zagonu okno za hiter začetek izbere
govorni model za vaš jezik: Fast (Majhen, približno 500 MB) ali Best
quality (do približno 3 GB); prenese se enkrat, ob prvi uporabi. Predvidite 8 GB
RAM-a; na procesorju (CPU) veliki modeli potrebujejo približno 1,5 do 2,5-krat toliko časa, kot traja
sam zvočni posnetek, majhni modeli pa približno polovico tega časa, NVIDIA GPU je veliko hitrejši. Različice za Windows niso digitalno podpisane, različice za Mac pa niso
notarizirane, zato SmartScreen in Gatekeeper ob prvem zagonu opozorita;
[../INSTALL.md](../INSTALL.md) prikazuje, na kaj morate klikniti. Za posodobitev zaženite
novejši namestitveni program čez starega; nastavitve se ohranijo.

**Prenosi po različicah** (vsaka značka šteje samo prenose za
tisto različico — starejše različice ostanejo objavljene in se njihove številke nikoli
ne ponastavijo):

[![v2.1.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.1.0/total?label=v2.1.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.1.0)
[![v2.0.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.0.0/total?label=v2.0.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0)
[![v1.9.3](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.3/total?label=v1.9.3&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.3)
[![v1.9.1](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.1/total?label=v1.9.1&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.1)
[![v1.9.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.0/total?label=v1.9.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.0)
[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

## Kaj zapusti vaš računalnik

Pri privzetih nastavitvah vaš zvok in transkripti ostanejo na vašem računalniku.
Aplikacija omrežje kljub temu uporablja za:

- prenos modela ali izbirne komponente, ko jo prvič potrebujete;
- svoje spletne nastavitve ob zagonu in dnevno preverjanje posodobitev na GitHubu, kar
  vas le obvesti o novi različici;
- statistiko uporabe, ki je privzeto vklopljena, po vsaki končani transkripciji: model,
  jezik, trajanja, število besed, različica aplikacije, operacijski sistem, procesor in
  velikost pomnilnika ter regija, nikoli ime datoteke. To lahko izklopite pod
  **Help → Usage statistics**.

Zvok ali besedilo transkripta se pošljeta samo, če izberete oblačni sistem (Gemini API
ali Google Cloud Speech-to-Text) ali sami povežete oddaljenega ponudnika AI.
**File → Work offline** zaustavi vse to. Vsaka povezava je navedena v
[../CONFIG.md](../CONFIG.md#network-use).

## Dokumentacija

[Namestitev](../INSTALL.md) · [Konfiguracija](../CONFIG.md) ·
[Transkripcija v živo](../LIVE.md) · [Način lokalnega omrežja in API](../SERVER.md) ·
[Oblačni sistemi](../CLOUD_STT.md) · [Arhitektura](../ARCHITECTURE.md) ·
[Dnevnik sprememb](../CHANGELOG.md) · [Vsa dokumentacija](../README.md)

## Izgradnja iz izvorne kode

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Zahteva Python 3.11 ali novejši. Proces izgradnje: [../BUILD.md](../BUILD.md). Testi in zahtevki za združitev (pull requests):
[../../CONTRIBUTING.md](../../CONTRIBUTING.md).

## Prispevki in stik

- **Hrošči in predlogi za nove funkcije:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Vprašanja in ideje:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Vse ostalo:** po e-pošti, prek
  [razdelka Contact na spletni strani](https://whisper-transcriber-suite.pages.dev/#contact)
- **Prijave varnostnih ranljivosti:** [../../SECURITY.md](../../SECURITY.md)

Ta projekt sledi kodeksu [Contributor Covenant](../../.github/CODE_OF_CONDUCT.md).
Če vam aplikacija prihrani čas, zvezdica na vrhu te strani pomaga drugim ljudem,
da jo najdejo.

## Kako se gradi ta projekt

Vzdrževalec ga razvija z veliko pomočjo programerskih asistentov AI (predvsem Claude). Preverjanja tipov
in enotni testi morajo uspešno prestati preizkus pred vsako uveljavitvijo (commit), CI pa jih ponovno zažene v operacijskih sistemih Windows in Linux po
vsakem potisku (push). [Kontrolni seznam za izdajo](../RELEASE_PROCESS.md) vključuje ročni preizkus namestitve na
pravem računalniku. Uveljavitve, narejene s pomočjo AI, zdaj navajajo model v vrstici `Assisted-by:`; številne starejše
pa namesto tega vsebujejo vrstico `Co-Authored-By: Claude`.

## Licenca

Avtorske pravice (c) 2026 translation-robot (soavtor). Projekt živi v tem repozitoriju,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
Sama izvorna koda projekta je pod licenco [BSD 3-Clause License](../../LICENSE). Priložena
orodja, izvajalno okolje Python in modeli ohranjajo svoje lastne licence; glejte
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
