<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: hang be, szöveg ki. Ingyenes, nyílt forráskódú átíró, amely a Whispert futtatja saját számítógépén." width="100%">

# Whisper Transcriber Suite

**Ingyenes, offline hangfelismerés és feliratozás hosszú felvételekhez a saját nyelvén — egy átlagos laptopon, fiók és hangfeltöltés nélkül.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![downloads](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/total?label=downloads&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Letöltés Windowshoz](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS és Linux: lásd a [Letöltés](#download) szakaszt.

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
<b>Magyar</b> ·
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

## Kinek szól

Feliratozóknak, fordítóknak, kutatóknak és újságíróknak, akik hosszú felvételekből (interjúkból, előadásokból, beszélgetésekből, videókból) készítenek szöveget vagy feliratot.
Húzzon be egy hang- vagy videófájlt, és az átirat mellé íródik. A beszédfelismerő motor az Ön saját számítógépén fut, így percdíj nélkül működik, és — miután a modell letöltődött — internetkapcsolatra sincs szükség.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="A Transcribe fül: ejtési terület, motor és nyelv választók, beszélőcímke és szó-időbélyeg opciók" width="80%">
</div>

## Újdonságok a 2.0-s verzióban

- **Sebesség és hátralévő idő:** A Queue (Várólista) lap mutatja az egyes feladatok sebességét és a becsült hátralévő időt.
- **Feliratozott videó egy linkből:** Töltse le, írja át és égesse be a feliratokat egyetlen folyamatként ([docs/SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Átirat weblapként:** Egy `.html` fájl keresővel és kattintásra induló lejátszással, amely offline is működik bármely böngészőben.
- **Ellenőrizhető offline munka:** Bekapcsolt Work offline mód esetén egy állapotsor jelzi, hogy az alkalmazás vagy az általa indított folyamatok rendelkeznek-e hálózati kapcsolattal.
- **Fordítás angolra:** A nem angol nyelvű beszéd egy menetben angol felirattá válik.
- **Gyorsindítás:** Az új telepítések három kérdést tesznek fel, és egy 18 másodperces mintaklip azonnal megmutatja az eredményt.
- **Probléma jelentése** a Help (Súgó) menüből, GitHub-fiók nélkül.
- **macOS:** Alkalmazásmenü Beállításokkal (Command-vessző), Világos és Sötét téma, amely követi a rendszert, értesítések. **Windows:** Tálca folyamatjelző és sötét címsorok.

A teljes lista: [CHANGELOG](../CHANGELOG.md).

## Funkciók

- **Helyi motorok:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (alapértelmezett), whisper.cpp és NVIDIA Parakeet a Whisper által felismert sok nyelvhez. Ha teheti, NVIDIA GPU-t használ CUDA-n keresztül, egyébként processzort.
- **Az alkalmazás az Ön nyelvén:** Menük, gombok és üzenetek 42 nyelven (gépi fordítás, ennek megfelelően jelölve; a javításokat szívesen fogadjuk). Követi a rendszer nyelvét, vagy a Speciális beállításokban választhat egyet. A perzsa, az arab és a héber egyelőre Windows alatt érhető el.
- **14 kimeneti formátum:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX és PDF, valamint oTranscribe, ELAN, InqScribe és Express Scribe formátumok. A DOCX és a PDF minden írást megfelelően rajzol ki; a perzsa, arab és urdu nyelvek jobbról balra, összekapcsolt betűkkel jelennek meg.
- **Megosztható weblap:** Mentse el a kész átiratot egyetlen `.html` fájlként, amely offline is működik bármely böngészőben; kattintson egy szóra a meghallgatásához, keressen, és ugorjon a fejezetekre.
- **Beszélőcímkék** Hugging Face fiók nélkül, valamint szó szintű időbélyegek és időintervallum-vágás.
- **A megszakított feladatok folytatódnak** a legutóbbi ellenőrzőponttól ahelyett, hogy elölről kezdenék (alapértelmezett motor).
- **Online videók:** Töltse le bármely olyan oldalról, amit az [yt-dlp](https://github.com/yt-dlp/yt-dlp) támogat, és az átírás azonnal elindul, amint a letöltés befejeződik.
- **Link feliratos videóhoz:** Egyetlen pipával a linkből `<cím>-subbed.mp4` lesz beégetett felirattal: letöltés, átírás és beégetés egyetlen várólistás feladatban ([docs/SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Élő:** Írja át egy mikrofon, vagy Windows alatt a rendszer hangját, valós időben ([docs/LIVE.md](../LIVE.md)).
- **Várólista és megfigyelt mappa** rengeteg fájl esetén.
- **Helyi hálózati mód:** Átíró felület és OpenAI-kompatibilis API a hálózatán lévő többi eszköz számára ([docs/SERVER.md](../SERVER.md)).
- **Opcionális, alapértelmezésként kikapcsolva:** AI eszközök a kész átirathoz (összefoglaló, kérdések, kétnyelvű SRT), valamint offline szövegfelolvasó hangklónozással.

Hogyan viszonyul a Subtitle Edit, Vibe, Buzz, noScribe és aTrain programokhoz, és mikor érdemes másik alkalmazást választani: **[docs/COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Letöltés

Legújabb kiadás: **[releases page](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| Fájl | Kinek ajánlott |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 vagy 11, 64-bites. A legtöbb felhasználónak erre van szüksége. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows telepítés nélkül: csomagolja ki és futtassa. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Mac-ek Apple Siliconnal, macOS 14 vagy újabb. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Intel alapú Mac-ek, macOS 10.15 vagy újabb. |

Linux alatt forráskódból futtatható: [platform/linux/README.md](../../platform/linux/README.md).

A mellékelt FFmpeg egy GPL kiépítés. Az ehhez tartozó forráskód minden kiadáshoz csatolva van `WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*` fájlokként; a pontos linkek megtalálhatóak a [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) fájlban.

Az ffmpeg és az yt-dlp be van építve. Az első indításkor egy gyorsbeállító ablakban választhatja ki az adott nyelvhez tartozó beszédmodellt: Fast (Kicsi, kb. 500 MB) vagy Best quality (akár kb. 3 GB); ez csak egyszer töltődik le. Számoljon 8 GB memóriával; processzor használatakor a Large (Nagy) modellek átírási ideje nagyjából a hang hosszának 1,5–2,5-szerese, a Small (Kicsi) modelleké a fele, míg egy NVIDIA GPU-val a folyamat jóval gyorsabb. A Windows-verziók nincsenek kódaláírással ellátva, a Mac-es változatok pedig nincsenek közjegyző által hitelesítve (notarized), ezért a SmartScreen és a Gatekeeper figyelmeztetést jelenít meg az első indításkor; a [docs/INSTALL.md](../INSTALL.md) leírja, mire kell kattintani. Frissítéshez futtassa az újabb telepítőt a régi felett; a beállítások megmaradnak.

**Letöltések verziónként** (minden jelvény csak az adott verzió saját kiadását számolja — a régebbi verziók is elérhetőek maradnak, és a számlálójuk sosem nullázódik):

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

## Mi hagyja el a számítógépét

Az alapértelmezett beállításokkal a hanganyagok és az átiratok a számítógépén maradnak.
Az alkalmazás az alábbiakhoz használja a hálózatot:

- egy modell vagy egy opcionális komponens letöltéséhez az első alkalommal;
- az online beállítások lekéréséhez indításkor és egy napi frissítés-ellenőrzéshez a GitHubon, amely csak arról tájékoztat, ha új verzió jelent meg;
- használati statisztikák elküldéséhez (alapértelmezésként bekapcsolva) minden befejezett átírás után: a modell, a nyelv, az időtartamok, a szavak száma, az alkalmazás verziója, az operációs rendszer, a CPU, a memória mérete és a régió; a fájl neve soha nem kerül elküldésre. Ezt kikapcsolhatja a **Help → Usage statistics** menüpont alatt.

Hang- vagy átiratszöveg csak akkor kerül elküldésre, ha Ön egy felhőalapú motort választ (Gemini API vagy Google Cloud Speech-to-Text), vagy ha saját maga kapcsol hozzá egy távoli AI-szolgáltatót. A **File → Work offline** menüpont megszakít minden kapcsolatot. Minden hálózati kapcsolat fel van sorolva a [docs/CONFIG.md](../CONFIG.md#network-use) oldalon.

## Dokumentáció

[Telepítés](../INSTALL.md) · [Beállítások](../CONFIG.md) · [Élő átírás](../LIVE.md) · [Helyi hálózati mód és API](../SERVER.md) · [Felhő motorok](../CLOUD_STT.md) · [Architektúra](../ARCHITECTURE.md) · [Változási napló](../CHANGELOG.md) · [Minden dokumentum](../README.md)

## Építés forráskódból

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Működéséhez Python 3.11 vagy újabb verzió szükséges. Build folyamatok: [docs/BUILD.md](../BUILD.md). Tesztek és pull requestek: [CONTRIBUTING.md](../../CONTRIBUTING.md).

## Hozzájárulás és kapcsolat

- **Hibák és új funkciók kérése:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Kérdések és ötletek:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Minden egyéb:** e-mailben, a weboldal [Kapcsolat részén keresztül](https://whisper-transcriber-suite.com/#contact) · ✉ [admin@whisper-transcriber-suite.com](mailto:admin@whisper-transcriber-suite.com)
- **Biztonsági bejelentések:** [SECURITY.md](../../SECURITY.md)

Ez a projekt követi a [Contributor Covenant](../../.github/CODE_OF_CONDUCT.md) irányelveit.
Ha az alkalmazás időt takarít meg Önnek, az oldal tetején lévő Csillag megnyomása segít másoknak is rátalálni.

## Hogyan készül ez a projekt

A karbantartó nagyrészt AI kódolási asszisztensek (főként Claude) segítségével fejleszti. Minden commit előtt lefutnak a típusellenőrzések és az egységtesztek, majd a CI ismét lefuttatja őket Windowson és Linuxon minden push után. A [kiadási ellenőrzőlista](../RELEASE_PROCESS.md) egy valós gépen végzett manuális telepítési tesztet is tartalmaz. Az AI segítségével készült commitok most már egy `Assisted-by:` sorban nevezik meg a modellt; sok régebbi pedig egy `Co-Authored-By: Claude` sort tartalmaz.

## Licenc

Copyright (c) 2026 translation-robot (co-author). A projekt ebben a tárolóban található: [Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
A projekt saját forráskódja a [BSD 3-Clause License](../../LICENSE) alatt áll. A mellékelt eszközök, a Python futtatókörnyezet és a modellek megtartják saját licencüket; lásd a [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) fájlt.
