<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: dźwięk wchodzi, tekst wychodzi. Darmowa, open-source'owa transkrypcja, która uruchamia Whisper na Twoim własnym komputerze." width="100%">

# Whisper Transcriber Suite

**Darmowa, działająca offline transkrypcja i napisy do długich nagrań w Twoim języku — na zwykłym laptopie, bez konta i bez wysyłania plików dźwiękowych.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![downloads](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/total?label=downloads&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Pobierz dla systemu Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS i Linux: zobacz [Pobieranie](#download).

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
<b>Polski</b> ·
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

## Dla kogo jest ten program

Dla twórców napisów, tłumaczy, badaczy i dziennikarzy, którzy zamieniają długie
nagrania (wywiady, wykłady, rozmowy, filmy) w tekst lub napisy.
Upuść plik audio lub wideo, a transkrypcja zostanie zapisana tuż obok niego. Silnik mowy działa na Twoim własnym komputerze, więc nie ma
żadnych kosztów za minutę i po pobraniu modelu nie jest potrzebne połączenie z internetem.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="Zakładka Transcribe: pole upuszczania, wybór silnika i języka, opcje etykiet mówców i znaczników czasu słów" width="80%">
</div>

## Co nowego w wersji 2.0

- **Prędkość i pozostały czas:** zakładka Queue pokazuje prędkość każdego zadania i przybliżony pozostały czas.
- **Wideo z napisami z linku:** pobierz, transkrybuj i wpal napisy jako jedno zadanie ([docs/SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Transkrypcja jako strona internetowa:** jeden plik `.html` z wyszukiwaniem i odtwarzaniem po kliknięciu, działający offline w dowolnej przeglądarce.
- **Tryb offline, który możesz sprawdzić:** przy włączonej opcji Work offline, pasek stanu pokazuje, czy aplikacja lub uruchomiony przez nią proces ma połączenie z siecią.
- **Tłumaczenie na angielski:** mowa w innych językach zostaje przetłumaczona na angielskie napisy w jednym przejściu.
- **Szybki start:** nowa instalacja zadaje trzy pytania, a 18-sekundowy klip próbny od razu pokazuje wynik.
- **Zgłoś problem** z poziomu Pomocy (Help), bez konta na GitHubie.
- **macOS:** menu aplikacji z opcją Ustawień (Command-przecinek), tryb jasny i ciemny zgodny z systemem, powiadomienia. **Windows:** postęp na pasku zadań i ciemne paski tytułu.

Pełna lista: [CHANGELOG](../CHANGELOG.md).

## Funkcje

- **Lokalne silniki:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (domyślnie), whisper.cpp i NVIDIA Parakeet dla wielu języków rozpoznawanych przez Whisper. Wykorzystuje układ graficzny NVIDIA
  przez CUDA, gdy to możliwe, a w przeciwnym razie procesor (CPU).
- **Aplikacja w Twoim języku:** Menu, przyciski i komunikaty w 42 językach
  (tłumaczenie maszynowe, oznaczone jako takie; poprawki są mile widziane).
  Aplikacja podąża za językiem systemu, albo możesz wybrać język w Ustawieniach
  zaawansowanych. Perski, arabski i hebrajski są na razie dostępne w systemie
  Windows.
- **14 formatów wyjściowych:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX i
  PDF, plus formaty oTranscribe, ELAN, InqScribe i Express Scribe. DOCX
  i PDF poprawnie rysują każdy alfabet, a język perski, arabski i urdu czytane są od prawej do lewej
  za pomocą połączonych liter.
- **Łatwa do udostępnienia strona internetowa:** zapisz gotową transkrypcję jako jeden plik `.html`, który
  działa offline w dowolnej przeglądarce; kliknij słowo, aby je usłyszeć, wyszukuj, przeskakuj do
  rozdziałów.
- **Etykiety mówców** bez konta Hugging Face, plus znaczniki czasu słów i
  przycinanie do zakresu czasu.
- **Wznawianie przerwanych zadań** od ostatniego punktu kontrolnego zamiast zaczynania
  od nowa (domyślny silnik).
- **Filmy online:** pobieranie z dowolnej strony wspieranej przez [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  i transkrypcja po zakończeniu pobierania.
- **Link do filmu z napisami:** jedno zaznaczenie zamienia link na `<title>-subbed.mp4`
  z wpalonymi napisami: pobieranie, transkrypcja i wpalanie w jednym zakolejkowanym zadaniu
  ([docs/SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Na żywo:** transkrybuj mikrofon, lub dźwięk z systemu w Windowsie, na
  bieżąco ([docs/LIVE.md](../LIVE.md)).
- **Kolejkowanie zadań (Batch queue) i obserwowany folder** dla wielu plików.
- **Tryb sieci lokalnej:** strona transkrypcji i API kompatybilne z OpenAI dla
  innych urządzeń w Twojej sieci ([docs/SERVER.md](../SERVER.md)).
- **Opcjonalne, domyślnie wyłączone:** Narzędzia AI dla gotowej transkrypcji (podsumowanie,
  pytania, dwujęzyczne napisy SRT) oraz zamiana tekstu na mowę offline z klonowaniem głosu.

Jak wypada w porównaniu z Subtitle Edit, Vibe, Buzz, noScribe i aTrain,
w tym kiedy inna aplikacja będzie lepszym wyborem:
**[docs/COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Pobieranie

Najnowsza wersja: **[strona wydań (releases)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| Plik | Dla kogo |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 lub 11, 64-bitowy. Zdecydowana większość wybierze ten. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows bez instalacji: rozpakuj i uruchom. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Mac z układem Apple silicon, macOS 14 lub nowszy. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Mac z procesorem Intel, macOS 10.15 lub nowszy. |

Linux uruchamiany jest z kodu źródłowego: [platform/linux/README.md](../../platform/linux/README.md).

Wbudowany pakiet FFmpeg to kompilacja na licencji GPL. Odpowiedni kod źródłowy jest dołączony do każdego wydania jako pliki
`WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*`; dokładne linki można znaleźć w
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

ffmpeg i yt-dlp są wbudowane. Przy pierwszym uruchomieniu, okno szybkiego startu (quick start) wybiera
model mowy dla Twojego języka: Szybki (Small, około 500 MB) lub Najwyższa
jakość (Best quality, do około 3 GB); model pobiera się raz, przy pierwszym użyciu. Zaplanuj 8 GB
pamięci RAM; na procesorze (CPU) modele Large potrzebują czasu wynoszącego około 1,5–2,5-krotności długości
nagrania audio, a Small o połowę mniej; układy graficzne (GPU) NVIDIA są znacznie szybsze. Kompilacje dla Windows nie są podpisane cyfrowo (code-signed), a te dla Maca nie są
notaryzowane (notarized), dlatego SmartScreen i Gatekeeper wyświetlają ostrzeżenie przy pierwszym uruchomieniu;
[docs/INSTALL.md](../INSTALL.md) pokazuje, w co kliknąć. Aby zaktualizować program, uruchom
nowy instalator bezpośrednio na starszą wersję; ustawienia zostaną zachowane.

**Pobrania z podziałem na wersje** (każda odznaka zlicza tylko wydania
danej wersji — starsze wersje pozostają opublikowane i ich liczniki nigdy
nie są resetowane):

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

## Co opuszcza Twój komputer

Przy domyślnych ustawieniach Twój dźwięk i transkrypcje pozostają na Twoim komputerze.
Aplikacja korzysta jednak z sieci, aby:

- pobrać model lub opcjonalny komponent, gdy jest on potrzebny po raz pierwszy;
- pobrać swoje ustawienia sieciowe przy starcie, oraz codziennie sprawdzić dostępność aktualizacji z GitHuba, co
  służy tylko poinformowaniu Cię o nowej wersji;
- wysyłać statystyki użytkowania, domyślnie włączone, po każdej ukończonej transkrypcji: model,
  język, czasy trwania, liczba słów, wersja aplikacji, system operacyjny, procesor (CPU) i
  ilość pamięci RAM, a także region; nigdy nazwy pliku. Można to wyłączyć w menu
  **Help → Usage statistics**.

Dźwięk lub tekst transkrypcji jest wysyłany tylko wtedy, gdy wybierzesz silnik w chmurze (Gemini API
lub Google Cloud Speech-to-Text) lub jeśli samodzielnie podłączysz zdalnego dostawcę AI.
Opcja **File → Work offline** całkowicie to wyłącza. Każde połączenie zostało wymienione w
[docs/CONFIG.md](../CONFIG.md#network-use).

## Dokumentacja

[Instalacja](../INSTALL.md) · [Konfiguracja](../CONFIG.md) ·
[Transkrypcja na żywo](../LIVE.md) · [Tryb sieci lokalnej i API](../SERVER.md) ·
[Silniki w chmurze](../CLOUD_STT.md) · [Architektura](../ARCHITECTURE.md) ·
[Historia zmian](../CHANGELOG.md) · [Wszystkie dokumenty](../README.md)

## Budowanie ze źródeł

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Wymaga Pythona 3.11 lub nowszego. Procesy budowania (pipelines): [docs/BUILD.md](../BUILD.md). Testy i pull requesty:
[CONTRIBUTING.md](../../CONTRIBUTING.md).

## Współpraca i kontakt

- **Błędy i propozycje funkcji:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Pytania i pomysły:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Cała reszta:** mailowo, poprzez
  [Sekcję kontaktową na stronie](https://whisper-transcriber-suite.com/#contact)
- **Zgłoszenia bezpieczeństwa:** [SECURITY.md](../../SECURITY.md)

Ten projekt przestrzega [Contributor Covenant](../../.github/CODE_OF_CONDUCT.md).
Jeśli aplikacja oszczędza Twój czas, gwiazdka (Star) na górze tej strony pomoże innym osobom
ją znaleźć.

## Jak tworzony jest ten projekt

Główny opiekun rozwija go przy ogromnej pomocy asystentów programowania opartych na AI (głównie Claude). Weryfikacja typów
oraz testy jednostkowe muszą zakończyć się pomyślnie przed każdym commitem, a CI uruchamia je ponownie w systemach Windows i Linux po
każdym pushu. Lista kontrolna wydania ([release checklist](../RELEASE_PROCESS.md)) obejmuje ręczny test instalacji na
prawdziwym komputerze. Commity wykonane z pomocą AI zawierają nazwę modelu w linii `Assisted-by:`; wiele starszych
zamiast tego posiada linię `Co-Authored-By: Claude`.

## Licencja

Copyright (c) 2026 translation-robot (współautor). Projekt jest utrzymywany w tym repozytorium,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
Własny kod źródłowy projektu dostępny jest na [licencji BSD 3-Clause](../../LICENSE). Dołączone
narzędzia, środowisko wykonawcze Pythona i modele posiadają własne licencje; zobacz
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
