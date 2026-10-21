<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**Ilmainen, offline-tilassa toimiva transkriptio ja tekstitys pitkille tallenteille omalla kielelläsi — tavallisella kannettavalla tietokoneella, ilman tiliä ja ilman äänen lataamista pilveen.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![downloads](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/total?label=downloads&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [⬇ Lataa Windowsille](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS ja Linux: katso [Lataus](#download).

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
<b>Suomi</b> ·
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

## Kenelle se on tarkoitettu

Tekstittäjille, kääntäjille, tutkijoille ja toimittajille, jotka muuttavat pitkiä
tallenteita (haastatteluja, luentoja, puheita, videoita) tekstiksi tai tekstityksiksi.
Vedä ja pudota ääni- tai videotiedosto, niin transkriptio tallennetaan samaan kansioon. Puhemoottori toimii omalla tietokoneellasi, joten
minuuttikohtaisia kustannuksia ei ole, ja kun malli on ladattu, internet-yhteyttä
ei tarvita.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="Transcribe-välilehti: pudotusalue tiedostoille, moottorin ja kielen valinnat, puhujatunnisteiden ja sanakohtaisten aikaleimojen asetukset" width="80%">
</div>

## Mitä uutta versiossa 2.0

- **Nopeus ja jäljellä oleva aika:** Jono-välilehti näyttää jokaisen työn nopeuden ja karkean arvion jäljellä olevasta ajasta.
- **Tekstitetty video linkistä:** lataa, transkriboi ja polta tekstitykset kiinni yhtenä työnä ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Transkriptio verkkosivuna:** yksi `.html`-tiedosto, jossa on haku ja klikkaa-ja-toista-ominaisuus, joka toimii offline-tilassa missä tahansa selaimessa.
- **Offline-tilan tarkistus:** kun Työskentele offline-tilassa on päällä, tilarivi näyttää, onko sovelluksella tai sen käynnistämällä prosessilla verkkoyhteys.
- **Käännä englanniksi:** vieraskielinen puhe muuttuu englanninkielisiksi tekstityksiksi yhdellä kertaa.
- **Pika-aloitus:** uudet asennukset kysyvät kolme kysymystä, ja 18 sekunnin näytepätkä näyttää tuloksen heti.
- **Ilmoita ongelmasta** Ohje-valikosta ilman GitHub-tiliä.
- **macOS:** sovellusvalikko asetuksilla (Komento-pilkku), järjestelmää seuraava vaalea ja tumma teema, ilmoitukset. **Windows:** edistymispalkki tehtäväpalkissa ja tummat otsikkopalkit.

Täysi luettelo: [CHANGELOG](../CHANGELOG.md).

## Ominaisuudet

- **Paikalliset moottorit:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (oletus), whisper.cpp ja NVIDIA Parakeet niille monille kielille, jotka Whisper
  tunnistaa. Käyttää NVIDIA-näytönohjainta
  CUDA:n kautta kun mahdollista, muuten suoritinta.
- **Sovellus omalla kielelläsi:** Valikot, painikkeet ja viestit 42 kielellä
  (konekäännetty ja merkitty sellaiseksi; korjaukset ovat tervetulleita). Sovellus
  seuraa järjestelmän kieltä, tai voit valita kielen lisäasetuksista. Persia, arabia
  ja heprea ovat toistaiseksi tarjolla Windowsissa.
- **14 tulostusmuotoa:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX ja
  PDF, plus oTranscribe-, ELAN-, InqScribe- ja Express Scribe -muodot. DOCX
  ja PDF piirtävät jokaisen kirjoitusjärjestelmän, ja persiaa, arabiaa ja urdua luetaan oikealta vasemmalle
  yhdistetyillä kirjaimilla.
- **Jaettava verkkosivu:** tallenna valmis transkriptio yhtenä `.html`-tiedostona, joka
  toimii offline-tilassa missä tahansa selaimessa; klikkaa sanaa kuullaksesi sen, hae, hyppää
  lukuihin.
- **Puhujien tunnistus** ilman Hugging Face -tiliä, plus sanakohtaiset aikaleimat ja
  aikavälin rajaus.
- **Keskeytetyt työt jatkuvat** viimeisestä tarkistuspisteestä alusta aloittamisen
  sijaan (oletusmoottori).
- **Verkkovideot:** lataa miltä tahansa sivustolta, jota [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  tukee, ja transkriboi, kun lataus on valmis.
- **Linkki tekstitettyyn videoon:** valintaruudun ruksilla linkki muuttuu `<title>-subbed.mp4`-tiedostoksi
  johon tekstitykset on poltettu kiinni: lataa, transkriboi ja polta kiinni yhtenä työnä jonossa
  ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Live:** transkriboi mikrofoni, tai järjestelmän ääni Windowsissa, samalla kun se
  tapahtuu ([../LIVE.md](../LIVE.md)).
- **Eräjono ja valvottu kansio** useille tiedostoille.
- **Lähiverkkotila:** transkriptiosivu ja OpenAI-yhteensopiva API
  verkkosi muille laitteille ([../SERVER.md](../SERVER.md)).
- **Valinnainen, oletuksena pois päältä:** Tekoälytyökalut valmiille transkriptiolle (yhteenveto,
  kysymykset, kaksikielinen SRT), ja offline-tekstistä-puheeksi -toiminto äänen kloonauksella.

Miten se vertautuu Subtitle Editiin, Vibeen, Buzziin, noScribeen ja aTrainiin,
mukaan lukien milloin toinen sovellus on parempi valinta:
**[../COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Lataus

Uusin julkaisu: **[julkaisusivu](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| Tiedosto | Kenelle |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 tai 11, 64-bittinen. Useimmat haluavat tämän. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows ilman asennusta: pura ja suorita. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Macit Apple Siliconilla, macOS 14 tai uudempi. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Intel-Macit, macOS 10.15 tai uudempi. |

Linux toimii lähdekoodista: [../platform/linux/README.md](../../platform/linux/README.md).

Mukana toimitettu FFmpeg on GPL-versio. Sen vastaava lähdekoodi on liitetty jokaiseen julkaisuun
`WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*`-tiedostoina; tarkat linkit ovat tiedostossa
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

ffmpeg ja yt-dlp sisältyvät pakettiin. Ensimmäisellä käynnistyskerralla pika-aloitusikkuna valitsee
puhemallin kielellesi: Nopea (Small, noin 500 Mt) tai Paras
laatu (jopa noin 3 Gt); se ladataan kerran ensimmäisellä käyttökerralla. Varaa 8 Gt RAM-muistia; suorittimella Large-mallit vievät noin 1,5–2,5 kertaa äänen pituuden
verran aikaa ja Small noin puolet; NVIDIA-näytönohjain on paljon nopeampi. Windows-versioita ei ole koodiallekirjoitettu ja Mac-versioita ei ole
notarisoitu, joten SmartScreen ja Gatekeeper varoittavat ensimmäisellä käynnistyskerralla;
[../INSTALL.md](../INSTALL.md) näyttää, mitä pitää klikata. Päivittääksesi aja uudempi
asennusohjelma vanhan päälle; asetukset säilyvät.

**Lataukset versioittain** (jokainen merkki laskee vain kyseisen version oman
julkaisun — vanhemmat versiot pysyvät julkaistuina ja niiden laskureita ei koskaan
nollata):

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

## Mitä tietoja tietokoneeltasi siirretään verkkoon

Oletusasetuksilla ääni ja transkriptiot pysyvät tietokoneellasi.
Sovellus käyttää verkkoa kuitenkin seuraaviin:

- mallin tai valinnaisen komponentin lataamiseen ensimmäisellä kerralla, kun sitä tarvitaan;
- sen verkkoasetuksiin käynnistyksen yhteydessä ja päivittäiseen päivitystarkistukseen GitHubissa, joka
  kertoo vain uudesta versiosta;
- käyttötilastoihin, päällä oletuksena, jokaisen valmistuneen transkription jälkeen: malli,
  kieli, kestot, sanamäärä, sovellusversio, käyttöjärjestelmä, suoritin ja
  muistin määrä, sekä alue, ei koskaan tiedoston nimeä. Laita ne pois päältä kohdasta
  **Help → Usage statistics**.

Ääntä tai transkriptiotekstiä lähetetään vain, jos valitset pilvipohjaisen moottorin (Gemini API
tai Google Cloud Speech-to-Text) tai yhdistät itse etä-tekoälytarjoajaan.
**File → Work offline** pysäyttää kaiken tämän. Jokainen yhteys on lueteltu kohdassa
[../CONFIG.md](../CONFIG.md#network-use).

## Dokumentaatio

[Asennus](../INSTALL.md) · [Kokoonpano](../CONFIG.md) ·
[Live-transkriptio](../LIVE.md) · [Lähiverkkotila ja API](../SERVER.md) ·
[Pilvipohjaiset moottorit](../CLOUD_STT.md) · [Arkkitehtuuri](../ARCHITECTURE.md) ·
[Muutosloki](../CHANGELOG.md) · [Kaikki dokumentit](../README.md)

## Rakenna lähdekoodista

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Vaatii Python 3.11:n tai uudemman. Rakennusputket: [../BUILD.md](../BUILD.md). Testit ja vetopyynnöt (pull requests):
[../../CONTRIBUTING.md](../../CONTRIBUTING.md).

## Osallistuminen ja yhteystiedot

- **Bugeista ilmoittaminen ja ominaisuuspyynnöt:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Kysymykset ja ideat:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Kaikki muu:** sähköpostitse,
  [verkkosivuston yhteystieto-osion kautta](https://whisper-transcriber-suite.com/#contact) · ✉ [admin@whisper-transcriber-suite.com](mailto:admin@whisper-transcriber-suite.com)
- **Turvallisuusraportit:** [../../SECURITY.md](../../SECURITY.md)

Tämä projekti noudattaa [Contributor Covenant -käytännesääntöjä](../../.github/CODE_OF_CONDUCT.md).
Jos sovellus säästää aikaasi, tähti (Star) tämän sivun yläreunassa auttaa muita
löytämään sen.

## Miten tämä projekti on rakennettu

Ylläpitäjä kehittää sitä tekoäly-koodausavustajien (pääasiassa Claude) vahvalla tuella. Tyyppitarkistusten
ja yksikkötestien on mentävä läpi ennen jokaista committia, ja CI suorittaa ne uudelleen Windowsissa ja Linuxissa jokaisen
pushin jälkeen. [Julkaisutarkistuslista](../RELEASE_PROCESS.md) sisältää manuaalisen asennustestin
oikealla koneella. Tekoälyn avulla tehdyt commitit nimeävät nyt mallin `Assisted-by:`-rivillä; monissa vanhemmissa
on sen sijaan `Co-Authored-By: Claude`-rivi.

## Lisenssi

Tekijänoikeus (c) 2026 translation-robot (toinen tekijä). Projekti sijaitsee tässä repositoriossa,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
Projektin oma lähdekoodi on [BSD 3-Clause -lisenssin](../../LICENSE) alainen. Mukana toimitetut
työkalut, Python-ajoympäristö ja mallit pitävät omat lisenssinsä; katso
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
