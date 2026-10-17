<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**Bezplatný, offline prepis a titulky pre dlhé nahrávky vo vašom jazyku — na bežnom notebooku, bez účtu a bez nahrávania zvuku na internet.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Stiahnuť pre Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS a Linux: pozri [Stiahnutie](#download).

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
<b>Slovenčina</b> ·
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

## Pre koho to je

Pre tvorcov titulkov, prekladateľov, výskumníkov a novinárov, ktorí prevádzajú dlhé
nahrávky (rozhovory, prednášky, prejavy, videá) na text alebo titulky.
Potiahnite audio alebo video súbor a prepis sa zapíše hneď vedľa neho. Rozpoznávanie reči beží na vašom vlastnom počítači, takže sa
neplatia žiadne poplatky za minútu a po stiahnutí modelu nie je potrebné
žiadne pripojenie k internetu.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="Karta Transcribe: miesto na pustenie súboru, výber enginu a jazyka, možnosti označenia hovoriacich a časových značiek slov" width="80%">
</div>

## Čo je nové vo verzii 2.0

- **Rýchlosť a zostávajúci čas:** záložka Queue ukazuje rýchlosť každej úlohy a odhadovaný zostávajúci čas.
- **Titulkované video z odkazu:** stiahnite, prepíšte a vpáľte titulky do videa ako jednu úlohu ([docs/SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Prepis ako webová stránka:** jeden `.html` súbor s vyhľadávaním a prehrávaním po kliknutí, ktorý funguje offline v akomkoľvek prehliadači.
- **Offline režim, ktorý si môžete overiť:** so zapnutou funkciou Work offline ukazuje stavový riadok, či má aplikácia alebo ňou spustený proces sieťové pripojenie.
- **Preklad do angličtiny:** reč v inom jazyku sa jedným prechodom prevedie na anglické titulky.
- **Rýchly štart:** nová inštalácia položí tri otázky a 18-sekundová ukážka ihneď predvedie výsledok.
- **Nahlásiť problém** z ponuky Help, bez účtu na GitHube.
- **macOS:** menu aplikácie s Nastavením (Command-čiarka), svetlý a tmavý režim podľa systému, oznámenia. **Windows:** priebeh na paneli úloh a tmavé záhlavia okien.

Kompletný zoznam: [CHANGELOG](../CHANGELOG.md).

## Funkcie

- **Lokálne enginy:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (predvolené), whisper.cpp a NVIDIA Parakeet pre mnoho jazykov, ktoré Whisper
  rozpoznáva. Využíva grafickú kartu NVIDIA
  cez CUDA, keď je to možné, inak procesor (CPU).
- **Aplikácia vo vašom jazyku:** Ponuky, tlačidlá a správy v 42 jazykoch (strojovo
  preložené a ako také označené; opravy sú vítané). Riadi sa jazykom systému, alebo
  si jazyk vyberiete v Rozšírených nastaveniach. Perčina, arabčina a hebrejčina sú
  zatiaľ dostupné vo Windows.
- **14 výstupných formátov:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX a
  PDF, plus formáty oTranscribe, ELAN, InqScribe a Express Scribe. DOCX
  a PDF správne vykresľujú každé písmo, perzština, arabčina a urdčina sa čítajú sprava doľava
  so spojenými písmenami.
- **Zdieľateľná webová stránka:** uložte hotový prepis ako jeden `.html` súbor, ktorý
  funguje offline v akomkoľvek prehliadači; kliknutím na slovo si ho vypočujete, môžete vyhľadávať, preskakovať po
  kapitolách.
- **Menovky hovoriacich** bez účtu Hugging Face, navyše časové značky jednotlivých slov a
  orezanie časového rozsahu.
- **Prerušené úlohy pokračujú** od posledného kontrolného bodu, namiesto toho, aby začínali
  znova (predvolený engine).
- **Online videá:** sťahovanie z akejkoľvek stránky, ktorú podporuje [yt-dlp](https://github.com/yt-dlp/yt-dlp),
  a prepis po dokončení sťahovania.
- **Odkaz na titulkované video:** jedno zaškrtnutie zmení odkaz na `<title>-subbed.mp4`
  s vpálenými titulkami: stiahnutie, prepis a vpálenie titulkov v jednej naplánovanej úlohe
  ([docs/SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Naživo:** prepisujte zvuk z mikrofónu, alebo systémový zvuk vo Windows,
  v reálnom čase ([docs/LIVE.md](../LIVE.md)).
- **Dávkové spracovanie (Batch queue) a sledovaný priečinok** pre mnoho súborov naraz.
- **Režim lokálnej siete:** stránka pre prepis a API kompatibilné s OpenAI pre
  ostatné zariadenia vo vašej sieti ([docs/SERVER.md](../SERVER.md)).
- **Voliteľné, v predvolenom stave vypnuté:** AI nástroje pre hotový prepis (zhrnutie,
  otázky, dvojjazyčné SRT) a offline prevod textu na reč s klonovaním hlasu.

Porovnanie so Subtitle Edit, Vibe, Buzz, noScribe a aTrain,
vrátane toho, kedy je lepšie zvoliť inú aplikáciu:
**[docs/COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Stiahnutie

Najnovšia verzia: **[stránka vydaní (releases)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| Súbor | Pre koho |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 alebo 11, 64-bit. Túto verziu bude chcieť väčšina ľudí. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows bez inštalácie: rozbaľte a spustite. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Macy s čipom Apple silicon, macOS 14 alebo novší. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Macy s procesorom Intel, macOS 10.15 alebo novší. |

Na Linuxe sa spúšťa zo zdrojových kódov: [platform/linux/README.md](../../platform/linux/README.md).

Pribalený FFmpeg je zostavenie pod licenciou GPL. Jeho zodpovedajúci zdrojový kód je pripojený ku každému vydaniu ako
súbory `WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*`; presné odkazy sú v
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

ffmpeg a yt-dlp sú súčasťou balenia. Pri prvom spustení okno pre rýchly štart vyberie
rečový model pre váš jazyk: Rýchly (Small, asi 500 MB) alebo Najlepšia
kvalita (Best quality, až asi 3 GB); stiahne sa len raz, pri prvom použití. Počítajte s 8 GB
pamäte RAM; na procesore (CPU) trvajú modely Large asi 1,5–2,5-násobok dĺžky
zvuku a Small asi polovicu, grafická karta (GPU) NVIDIA je oveľa rýchlejšia. Zostavenia pre Windows nie sú digitálne podpísané a pre Mac nie sú
notarizované, takže SmartScreen a Gatekeeper pri prvom spustení zobrazia varovanie;
[docs/INSTALL.md](../INSTALL.md) ukazuje, na čo kliknúť. Pre aktualizáciu spustite
novší inštalátor cez ten starý; nastavenia zostanú zachované.

**Počet stiahnutí podľa verzie** (každý odznak počíta len vydania
danej verzie — staršie verzie zostávajú zverejnené a ich počty sa nikdy
nemažú):

[![v2.1.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.1.0/total?label=v2.1.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.1.0)
[![v2.0.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.0.0/total?label=v2.0.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0)
[![v1.9.3](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.3/total?label=v1.9.3&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.3)
[![v1.9.1](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.1/total?label=v1.9.1&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.1)
[![v1.9.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.0/total?label=v1.9.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.0)
[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

## Čo opúšťa váš počítač

Pri predvolenom nastavení váš zvuk aj prepisy zostávajú na vašom počítači.
Aplikácia využíva sieť len na:

- stiahnutie modelu alebo voliteľnej súčasti pri prvom použití;
- načítanie online nastavení pri spustení a na dennú kontrolu aktualizácií na GitHube, ktorá
  vás len informuje o novej verzii;
- odoslanie štatistík používania po každom dokončenom prepise (v predvolenom stave zapnuté): model,
  jazyk, dĺžky trvania, počet slov, verzia aplikácie, operačný systém, procesor (CPU) a
  veľkosť pamäte, a región; nikdy sa neodosiela názov súboru. Môžete to vypnúť v
  **Help → Usage statistics**.

Zvuk alebo text prepisu sa odosiela len v prípade, že si vyberiete cloudový engine (Gemini API
alebo Google Cloud Speech-to-Text) alebo ak si sami pripojíte vzdialeného poskytovateľa AI.
**File → Work offline** to všetko zastaví. Každé pripojenie je vypísané v
[docs/CONFIG.md](../CONFIG.md#network-use).

## Dokumentácia

[Inštalácia](../INSTALL.md) · [Konfigurácia](../CONFIG.md) ·
[Živý prepis](../LIVE.md) · [Režim lokálnej siete a API](../SERVER.md) ·
[Cloudové enginy](../CLOUD_STT.md) · [Architektúra](../ARCHITECTURE.md) ·
[História zmien](../CHANGELOG.md) · [Všetky dokumenty](../README.md)

## Zostavenie zo zdrojových kódov

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Vyžaduje Python 3.11 alebo novší. Procesy zostavenia (pipelines): [docs/BUILD.md](../BUILD.md). Testy a pull requesty:
[CONTRIBUTING.md](../../CONTRIBUTING.md).

## Prispievanie a kontakt

- **Chyby a návrhy funkcií:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Otázky a nápady:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Všetko ostatné:** e-mailom, cez
  [Kontaktnú sekciu na webe](https://whisper-transcriber-suite.pages.dev/#contact)
- **Hlásenie bezpečnostných chýb:** [SECURITY.md](../../SECURITY.md)

Tento projekt sa riadi kódexom správania [Contributor Covenant](../../.github/CODE_OF_CONDUCT.md).
Ak vám aplikácia šetrí čas, hviezdička (Star) na začiatku tejto stránky pomôže ostatným
ju nájsť.

## Ako sa tento projekt vyvíja

Hlavný správca ho vyvíja s výraznou pomocou AI programovacích asistentov (prevažne Claude). Kontrola typov
a jednotkové testy (unit tests) musia prejsť pred každým commitom a CI ich po
každom pushnutí spúšťa znova na Windows a Linuxe. Kontrolný zoznam pre vydanie ([release checklist](../RELEASE_PROCESS.md)) zahŕňa manuálny test inštalácie na
reálnom stroji. Commity vytvorené s pomocou AI teraz uvádzajú model na riadku `Assisted-by:`; mnoho starších
namiesto toho obsahuje riadok `Co-Authored-By: Claude`.

## Licencia

Copyright (c) 2026 translation-robot (spoluautor). Projekt žije v tomto repozitári,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
Vlastný zdrojový kód projektu je pod licenciou [BSD 3-Clause](../../LICENSE). Pribalené
nástroje, behové prostredie Pythonu a modely si zachovávajú svoje vlastné licencie; pozri
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
