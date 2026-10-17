<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**Uzun ses kayıtları için kendi dilinizde ücretsiz, çevrimdışı deşifre ve altyazılar — sıradan bir dizüstü bilgisayarda, hesap açmadan ve ses yüklemesi yapmadan.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Windows için İndir](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS ve Linux: [İndirme (Download)](#download) bölümüne bakın.

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
<b>Türkçe</b> ·
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

## Kimler için tasarlandı

Uzun ses kayıtlarını (röportajlar, dersler, konuşmalar, videolar) metne veya altyazıya dönüştüren
altyazı çevirmenleri, çevirmenler, araştırmacılar ve gazeteciler içindir.
Bir ses veya video dosyasını sürükleyip bırakın, deşifre metni hemen yanına yazılsın. Ses tanıma motoru kendi bilgisayarınızda çalışır,
bu nedenle dakika başına ücret ödemezsiniz ve model bir kez indirildikten sonra internet bağlantısına gerek kalmaz.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="Transcribe sekmesi: dosya bırakma alanı, motor ve dil seçicileri, konuşmacı etiketi ve sözcük zaman damgası seçenekleri" width="80%">
</div>

## 2.0 Sürümündeki Yenilikler

- **Hız ve kalan süre:** Queue (Kuyruk) sekmesi, her işin hızını ve yaklaşık kalan süreyi gösterir.
- **Bağlantıdan altyazılı video:** tek bir iş olarak indir, deşifre et ve altyazıları videoya göm ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Web sayfası olarak deşifre metni:** her tarayıcıda çevrimdışı çalışan, arama ve tıklayarak oynatma özellikli tek bir `.html` dosyası.
- **Çevrimdışı çalıştığınızdan emin olun:** Work offline (Çevrimdışı çalış) açıkken, bir durum çubuğu uygulamanın veya başlattığı bir işlemin ağ bağlantısı olup olmadığını gösterir.
- **İngilizce'ye çevir:** İngilizce olmayan konuşmalar tek geçişte İngilizce altyazıya dönüşür.
- **Hızlı başlangıç:** yeni kurulumlarda üç soru sorulur ve 18 saniyelik bir örnek klip sonucu anında gösterir.
- **Sorun bildirin:** GitHub hesabı olmadan Yardım (Help) menüsünden sorun bildirebilirsiniz.
- **macOS:** Ayarlar (Command-virgül) içeren uygulama menüsü, sistemi takip eden Açık (Light) ve Koyu (Dark) temalar, bildirimler. **Windows:** görev çubuğunda ilerleme durumu ve koyu renkli başlık çubukları.

Tam liste: [../CHANGELOG.md](../CHANGELOG.md).

## Özellikler

- **Yerel motorlar:** Whisper'ın tanıdığı birçok dil için [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (varsayılan), whisper.cpp ve NVIDIA Parakeet. Yapabildiği durumlarda CUDA üzerinden bir NVIDIA GPU kullanır, aksi takdirde işlemciyi (CPU) kullanır.
- **Uygulama kendi dilinizde:** Menüler, düğmeler ve iletiler 42 dilde (makine çevirisi, bu şekilde işaretlenmiştir; düzeltmeler memnuniyetle karşılanır). Sistem dilinizi izler ya da Gelişmiş ayarlar'dan bir dil seçebilirsiniz. Farsça, Arapça ve İbranice şimdilik Windows'ta sunulmaktadır.
- **14 çıktı biçimi:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX ve
  PDF; ayrıca oTranscribe, ELAN, InqScribe ve Express Scribe biçimleri. DOCX
  ve PDF her alfabeyi çizer; Farsça, Arapça ve Urduca sağdan sola bitişik harflerle okunur.
- **Paylaşılabilir web sayfası:** bitmiş bir deşifreyi çevrimdışı çalışabilen tek bir `.html` dosyası olarak kaydedin; 
  duymak için bir kelimeye tıklayın, arama yapın, bölümlere atlayın.
- **Konuşmacı etiketleri:** Hugging Face hesabı gerektirmeden konuşmacıları ayırt eder, kelime düzeyinde zaman damgaları (timestamps) ve zaman aralığı kesme imkanı sunar.
- **Yarım kalan işler devam eder:** (varsayılan motorda) baştan başlamak yerine son kontrol noktasından (checkpoint) devam eder.
- **Çevrimiçi videolar:** [yt-dlp](https://github.com/yt-dlp/yt-dlp)'nin desteklediği 
  herhangi bir siteden indirin ve indirme bittiğinde deşifre edin.
- **Altyazılı videoya bağlantı:** tek bir onay kutusu (tick), bir bağlantıyı içine altyazı gömülmüş bir `<başlık>-subbed.mp4`
  dosyasına dönüştürür: indir, deşifre et ve tek bir iş olarak sıraya alıp videoya göm ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Canlı:** konuşulurken bir mikrofonu veya Windows'ta sistem sesini canlı olarak deşifre edin ([../LIVE.md](../LIVE.md)).
- **Toplu iş kuyruğu ve izlenen klasör (watched folder):** çok sayıda dosya için.
- **Yerel ağ modu:** ağınızdaki diğer cihazlar için bir deşifre sayfası ve OpenAI uyumlu bir API sunar ([../SERVER.md](../SERVER.md)).
- **İsteğe bağlı, varsayılan olarak kapalı:** bitmiş bir metin için yapay zeka araçları (özet, 
  sorular, iki dilli SRT) ve ses klonlama ile çevrimdışı metinden sese (text-to-voice) çeviri.

Subtitle Edit, Vibe, Buzz, noScribe ve aTrain ile karşılaştırması 
ve hangi durumlarda başka bir uygulamanın daha iyi bir seçim olabileceği: 
**[../COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## İndirme

En son sürüm: **[Sürümler sayfası (releases)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| Dosya | Şunun için |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 veya 11, 64-bit. Çoğu kişinin indirmesi gereken dosya budur. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Kurulum yapmadan Windows: zip'ten çıkarın ve çalıştırın. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Apple Silicon (M serisi çip) kullanan Mac'ler, macOS 14 veya daha yenisi. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Intel işlemcili Mac'ler, macOS 10.15 veya daha yenisi. |

Linux'ta kaynak kodundan (source) çalışır: [../../platform/linux/README.md](../../platform/linux/README.md).

Birlikte gelen FFmpeg, bir GPL derlemesidir. İlgili kaynak kodu her sürüme 
`WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*` dosyaları olarak eklenmiştir; kesin bağlantılar
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) içindedir.

ffmpeg ve yt-dlp pakete dahildir. İlk başlatmada, hızlı başlangıç penceresi 
dilinize uygun konuşma modelini seçmenizi sağlar: Hızlı (Küçük, yaklaşık 500 MB) veya En iyi
kalite (yaklaşık 3 GB'a kadar); bu dosya ilk kullanımda bir kez indirilir. 8 GB RAM
planlaması yapın; CPU üzerinde Large (Büyük) modeller ses süresinin yaklaşık 1,5–2,5 katı kadar, 
Small (Küçük) modeller ise yaklaşık yarısı kadar sürer, NVIDIA GPU ise çok daha hızlıdır. Windows derlemeleri kod imzalı değildir ve Mac derlemeleri onaylanmamıştır (notarized), 
bu nedenle SmartScreen ve Gatekeeper ilk başlatmada uyarı verir; 
[../INSTALL.md](../INSTALL.md) neye tıklamanız gerektiğini gösterir. Güncellemek için
yeni yükleyiciyi eskisinin üzerine kurun; ayarlarınız korunur.

**Sürümlere göre indirmeler** (her rozet sadece o sürümün kendi 
yayınını sayar — eski sürümler yayında kalır ve sayıları asla 
sıfırlanmaz):

[![v2.1.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.1.0/total?label=v2.1.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.1.0)
[![v2.0.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.0.0/total?label=v2.0.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0)
[![v1.9.3](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.3/total?label=v1.9.3&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.3)
[![v1.9.1](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.1/total?label=v1.9.1&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.1)
[![v1.9.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.0/total?label=v1.9.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.0)
[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

## Bilgisayarınızdan Dışarı Ne Çıkar?

Varsayılan ayarlarla sesiniz ve deşifre metinleriniz bilgisayarınızda kalır.
Uygulamanın ağı kullandığı durumlar şunlardır:

- bir modeli veya isteğe bağlı bir bileşeni ilk kez ihtiyaç duyulduğunda indirmek;
- başlangıçtaki çevrimiçi ayarları ve size yalnızca yeni bir sürüm olduğunu bildiren günlük GitHub güncelleme kontrolü;
- tamamlanan her deşifreden sonra, varsayılan olarak açık olan kullanım istatistikleri: model, 
  dil, süreler, kelime sayısı, uygulama sürümü, işletim sistemi, CPU ve 
  bellek boyutu, bölge bilgisi gönderilir, ancak dosyanın adı asla gönderilmez. Bunları kapatmak için 
  **Help → Usage statistics** yolunu izleyebilirsiniz.

Sadece bir bulut motoru (Gemini API veya Google Cloud Speech-to-Text) seçerseniz veya kendiniz 
uzak bir yapay zeka sağlayıcısı bağlarsanız ses veya metin gönderilir.
**File → Work offline** (Çevrimdışı çalış) seçeneği tüm bunları durdurur. Her bağlantı şu belgede listelenmiştir: 
[../CONFIG.md](../CONFIG.md#network-use).

## Belgeleme (Documentation)

[Kurulum (Install)](../INSTALL.md) · [Yapılandırma (Configuration)](../CONFIG.md) ·
[Canlı Deşifre (Live transcription)](../LIVE.md) · [Yerel ağ modu ve API](../SERVER.md) ·
[Bulut motorları (Cloud engines)](../CLOUD_STT.md) · [Mimari (Architecture)](../ARCHITECTURE.md) ·
[Değişiklik Günlüğü (Changelog)](../CHANGELOG.md) · [Tüm belgeler](../README.md)

## Kaynak Kodundan Derleme (Build from source)

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Python 3.11 veya daha yeni bir sürüm gerektirir. Derleme süreçleri: [../BUILD.md](../BUILD.md). Testler ve pull request'ler:
[../../CONTRIBUTING.md](../../CONTRIBUTING.md).

## Katkıda Bulunma ve İletişim

- **Hatalar (Bugs) ve yeni özellik istekleri:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Sorular ve fikirler:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Diğer her şey:** web sitesinin [İletişim bölümü (Contact)](https://whisper-transcriber-suite.pages.dev/#contact) üzerinden e-posta yoluyla
- **Güvenlik bildirimleri:** [../../SECURITY.md](../../SECURITY.md)

Bu proje [Katılımcı Sözleşmesi'ni (Contributor Covenant)](../../.github/CODE_OF_CONDUCT.md) takip eder.
Eğer uygulama size zaman kazandırıyorsa, bu sayfanın en üstündeki Yıldız (Star) düğmesi diğer insanların
uygulamayı bulmasına yardımcı olur.

## Bu Proje Nasıl Geliştirildi?

Geliştirici projeyi, yapay zeka kodlama asistanlarından (çoğunlukla Claude) büyük ölçüde yardım alarak geliştirir. Her işleme (commit) işleminden önce tip kontrolleri (type checks)
ve birim testlerinin (unit tests) geçmesi gerekir; CI bunları Windows ve Linux'ta
her push işleminden sonra tekrar çalıştırır. [Sürüm kontrol listesi (release checklist)](../RELEASE_PROCESS.md) 
gerçek bir makinede manuel bir kurulum testini de içerir. Yapay zeka yardımıyla yapılan 
commit'ler artık bir `Assisted-by:` satırında modeli belirtmektedir; birçok eski 
commit'te bunun yerine bir `Co-Authored-By: Claude` satırı bulunur.

## Lisans

Copyright (c) 2026 translation-robot (co-author). Proje şu depoda yer almaktadır:
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
Projenin kendi kaynak kodu [BSD 3-Clause Lisansı](../../LICENSE) altındadır. Pakete dahil edilen
araçlar, Python çalışma zamanı (runtime) ve modeller kendi lisanslarını korur; görmek için:
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
