<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**अपनी भाषा में लंबी रिकॉर्डिंग्स के लिए मुफ़्त, ऑफलाइन ट्रांसक्रिप्शन (श्रुतलेख) और सबटाइटल्स — एक साधारण लैपटॉप पर, बिना किसी अकाउंट और बिना कोई ऑडियो अपलोड किए।**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Windows के लिए डाउनलोड करें](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS और Linux: [डाउनलोड](#download) देखें।

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
<b>हिन्दी</b> ·
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

## यह किसके लिए है

सबटाइटल्स बनाने वालों, अनुवादकों, शोधकर्ताओं और पत्रकारों के लिए जो लंबी रिकॉर्डिंग्स (इंटरव्यू, व्याख्यान, बातचीत, वीडियो) को टेक्स्ट या सबटाइटल्स में बदलते हैं।
एक ऑडियो या वीडियो फ़ाइल छोड़ें और उसके ठीक बगल में ट्रांसक्रिप्ट लिख दी जाएगी। स्पीच इंजन आपके अपने कंप्यूटर पर काम करता है, इसलिए प्रति मिनट कोई खर्च नहीं है और एक बार मॉडल डाउनलोड हो जाने पर, इंटरनेट कनेक्शन की आवश्यकता नहीं होती है।

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="Transcribe टैब: फ़ाइल डालने की जगह, इंजन और भाषा चुनने के विकल्प, स्पीकर लेबल और शब्द टाइमस्टैम्प के विकल्प" width="80%">
</div>

## 2.0 में नया क्या है

- **गति और शेष समय:** Queue (कतार) टैब प्रत्येक कार्य की गति और अनुमानित शेष समय दिखाता है।
- **लिंक से सबटाइटल्ड वीडियो:** एक ही कार्य में डाउनलोड करें, ट्रांसक्राइब करें और सबटाइटल्स जोड़ें ([docs/SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md))।
- **वेब पेज के रूप में ट्रांसक्रिप्ट:** सर्च और 'क्लिक-टू-प्ले' के साथ एक `.html` फ़ाइल जो किसी भी ब्राउज़र में ऑफलाइन काम करती है।
- **ऑफ़लाइन काम जिसे आप जांच सकते हैं:** 'Work offline' चालू होने पर, एक स्टेटस लाइन दिखाती है कि ऐप या उसके द्वारा शुरू की गई प्रक्रिया के पास नेटवर्क कनेक्शन है या नहीं।
- **अंग्रेज़ी में अनुवाद करें:** गैर-अंग्रेज़ी भाषण एक ही बार में अंग्रेज़ी सबटाइटल्स में बदल जाता है।
- **क्विक स्टार्ट:** नया इंस्टॉलेशन तीन सवाल पूछता है, और एक 18-सेकंड की सैंपल क्लिप तुरंत परिणाम दिखाती है।
- **समस्या की रिपोर्ट करें:** बिना GitHub अकाउंट के Help मेन्यू से।
- **macOS:** सेटिंग्स (Command-comma) के साथ ऐप मेनू, लाइट और डार्क मोड जो सिस्टम का पालन करते हैं, नोटिफिकेशन्स। **Windows:** टास्कबार प्रोग्रेस और डार्क टाइटल बार्स।

पूरी सूची: [CHANGELOG](../CHANGELOG.md)।

## विशेषताएं

- **स्थानीय इंजन:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (डिफ़ॉल्ट), whisper.cpp और NVIDIA Parakeet, उन कई भाषाओं के लिए जिन्हें Whisper पहचानता है। जब संभव हो, CUDA के माध्यम से NVIDIA GPU का उपयोग करता है, अन्यथा CPU का।
- **आपकी भाषा में ऐप:** मेनू, बटन और संदेश 42 भाषाओं में (मशीन द्वारा अनुवादित और इसी रूप में चिह्नित; सुधार का स्वागत है)। यह आपके सिस्टम की भाषा का पालन करता है, या आप उन्नत सेटिंग्स में कोई भाषा चुन सकते हैं। फ़ारसी, अरबी और हिब्रू फ़िलहाल Windows पर उपलब्ध हैं।
- **14 आउटपुट फ़ॉर्मेट्स:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX और PDF, साथ ही oTranscribe, ELAN, InqScribe और Express Scribe फ़ॉर्मेट्स। DOCX और PDF हर स्क्रिप्ट को सही ढंग से लिखते हैं, और फ़ारसी, अरबी और उर्दू दाएं से बाएं जुड़े अक्षरों के साथ पढ़े जाते हैं।
- **शेयर करने योग्य वेब पेज:** समाप्त ट्रांसक्रिप्ट को एक `.html` फ़ाइल के रूप में सहेजें जो किसी भी ब्राउज़र में ऑफ़लाइन काम करती है; सुनने के लिए शब्द पर क्लिक करें, खोजें, चैप्टर्स पर जाएं।
- **स्पीकर लेबल्स:** Hugging Face अकाउंट के बिना, साथ ही शब्दों के टाइमस्टैम्प और टाइम-रेंज क्लिपिंग।
- **रुके हुए कार्य वहीं से शुरू होते हैं:** डिफ़ॉल्ट इंजन के साथ, बीच में रुके हुए कार्य फिर से शुरू होने के बजाय अपने अंतिम चेकप्वाइंट से काम करना शुरू कर देते हैं।
- **ऑनलाइन वीडियो:** [yt-dlp](https://github.com/yt-dlp/yt-dlp) द्वारा समर्थित किसी भी साइट से डाउनलोड करें और डाउनलोड समाप्त होने पर ट्रांसक्राइब करें।
- **सबटाइटल्ड वीडियो का लिंक:** एक टिक किसी भी लिंक को `<title>-subbed.mp4` में बदल देता है जिसमें सबटाइटल्स जुड़े होते हैं: कतार में लगे एक ही कार्य में डाउनलोड करें, ट्रांसक्राइब करें और जोड़ें ([docs/SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md))।
- **लाइव:** माइक्रोफ़ोन को, या Windows पर सिस्टम ऑडियो को, बोलते समय उसी समय ट्रांसक्राइब करें ([docs/LIVE.md](../LIVE.md))।
- **बैच कतार और वॉचड फोल्डर:** कई फ़ाइलों के लिए।
- **लोकल-नेटवर्क मोड:** आपके नेटवर्क पर अन्य डिवाइस के लिए एक ट्रांसक्रिप्शन पेज और एक OpenAI-संगत API ([docs/SERVER.md](../SERVER.md))।
- **वैकल्पिक, डिफ़ॉल्ट रूप से बंद:** तैयार ट्रांसक्रिप्ट के लिए AI टूल (सारांश, प्रश्न, द्विभाषी SRT), और वॉयस क्लोनिंग के साथ ऑफ़लाइन टेक्स्ट टू वॉयस।

Subtitle Edit, Vibe, Buzz, noScribe और aTrain के साथ इसकी तुलना कैसे होती है, इसमें यह भी शामिल है कि कब कोई अन्य ऐप बेहतर विकल्प है:
**[docs/COMPARISON.md](../COMPARISON.md)**।

<a id="download"></a>

## डाउनलोड

नवीनतम रिलीज़: **[रिलीज़ पेज](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**।

| फ़ाइल | के लिए |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 या 11, 64-बिट। ज़्यादातर लोग इसे ही चाहते हैं। |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | बिना इंस्टॉल किए Windows: अनज़िप करें और चलाएं। |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Apple सिलिकॉन वाले Mac, macOS 14 या नया। |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Intel Mac, macOS 10.15 या नया। |

Linux सोर्स से चलता है: [platform/linux/README.md](../../platform/linux/README.md)।

बंडल किया गया FFmpeg एक GPL बिल्ड है। इसका संबंधित स्रोत प्रत्येक रिलीज़ के साथ `WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*` फ़ाइलों के रूप में संलग्न है; सटीक लिंक [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) में हैं।

ffmpeg और yt-dlp बंडल किए गए हैं। पहली बार लॉन्च करने पर एक क्विक स्टार्ट विंडो आपकी भाषा के लिए स्पीच मॉडल चुनती है: तेज़ (छोटा, लगभग 500 MB) या सर्वोत्तम गुणवत्ता (लगभग 3 GB तक); यह पहले उपयोग पर एक बार डाउनलोड होता है। 8 GB RAM की योजना बनाएं; CPU पर बड़े (Large) मॉडल ऑडियो की लंबाई का लगभग 1.5-2.5 गुना समय लेते हैं और छोटे (Small) लगभग आधा, NVIDIA GPU बहुत तेज़ होता है। Windows बिल्ड कोड-साइन नहीं हैं और Mac बिल्ड नोटराइज़ नहीं हैं, इसलिए SmartScreen और Gatekeeper पहली बार लॉन्च करने पर चेतावनी देते हैं; [docs/INSTALL.md](../INSTALL.md) दिखाता है कि क्या क्लिक करना है। अपडेट करने के लिए, नए इंस्टॉलर को पुराने वाले के ऊपर चलाएं; सेटिंग्स सुरक्षित रखी जाती हैं।

**संस्करण द्वारा डाउनलोड** (प्रत्येक बैज केवल उस संस्करण की अपनी रिलीज़ की गणना करता है — पुराने संस्करण प्रकाशित रहते हैं और उनकी गणना कभी रीसेट नहीं होती है):

[![v2.1.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.1.0/total?label=v2.1.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.1.0)
[![v2.0.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.0.0/total?label=v2.0.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0)
[![v1.9.3](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.3/total?label=v1.9.3&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.3)
[![v1.9.1](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.1/total?label=v1.9.1&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.1)
[![v1.9.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.0/total?label=v1.9.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.0)
[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

## आपके कंप्यूटर से क्या बाहर जाता है

डिफ़ॉल्ट सेटिंग्स के साथ आपका ऑडियो और ट्रांसक्रिप्ट आपके कंप्यूटर पर ही रहता है।
ऐप नेटवर्क का उपयोग इसके लिए करता है:

- पहली बार आवश्यकता होने पर एक मॉडल या एक वैकल्पिक घटक डाउनलोड करने के लिए;
- स्टार्टअप पर इसकी ऑनलाइन सेटिंग्स और GitHub पर दैनिक अपडेट चेक, जो आपको केवल नए संस्करण के बारे में बताता है;
- प्रत्येक समाप्त ट्रांसक्रिप्शन के बाद उपयोग के आंकड़े (डिफ़ॉल्ट रूप से चालू): मॉडल, भाषा, अवधि, शब्दों की संख्या, ऐप संस्करण, ऑपरेटिंग सिस्टम, CPU और मेमोरी का आकार, और क्षेत्र, लेकिन फ़ाइल का नाम कभी नहीं। उन्हें **Help → Usage statistics** के तहत बंद कर सकते हैं।

ऑडियो या ट्रांसक्रिप्ट टेक्स्ट केवल तभी भेजा जाता है जब आप कोई क्लाउड इंजन (Gemini API या Google Cloud Speech-to-Text) चुनते हैं या किसी रिमोट AI प्रदाता को स्वयं कनेक्ट करते हैं।
**File → Work offline** इन सभी को रोक देता है। प्रत्येक कनेक्शन [docs/CONFIG.md](../CONFIG.md#network-use) में सूचीबद्ध है।

## दस्तावेज़ीकरण

[इंस्टॉल करें](../INSTALL.md) · [कॉन्फ़िगरेशन](../CONFIG.md) ·
[लाइव ट्रांसक्रिप्शन](../LIVE.md) · [लोकल-नेटवर्क मोड और API](../SERVER.md) ·
[क्लाउड इंजन](../CLOUD_STT.md) · [आर्किटेक्चर](../ARCHITECTURE.md) ·
[चेंजलॉग](../CHANGELOG.md) · [सभी दस्तावेज़](../README.md)

## सोर्स से बनाएं

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Python 3.11 या इसके बाद के संस्करण की आवश्यकता है। बिल्ड पाइपलाइन: [docs/BUILD.md](../BUILD.md)। टेस्ट और पुल रिक्वेस्ट:
[CONTRIBUTING.md](../../CONTRIBUTING.md)।

## योगदान और संपर्क

- **बग और सुविधा अनुरोध:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **प्रश्न और विचार:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **बाकी सब कुछ:** ईमेल द्वारा, [वेबसाइट के संपर्क अनुभाग](https://whisper-transcriber-suite.pages.dev/#contact) के माध्यम से
- **सुरक्षा रिपोर्ट:** [SECURITY.md](../../SECURITY.md)

यह प्रोजेक्ट [योगदानकर्ता नियम (Contributor Covenant)](../../.github/CODE_OF_CONDUCT.md) का पालन करता है।
अगर यह ऐप आपका समय बचाता है, तो इस पेज के शीर्ष पर एक Star (स्टार) अन्य लोगों को इसे खोजने में मदद करता है।

## इस प्रोजेक्ट को कैसे बनाया गया है

मेंटेनर इसे AI कोडिंग सहायकों (मुख्य रूप से Claude) की भारी मदद से विकसित करता है। प्रत्येक कमिट (commit) से पहले टाइप चेक और यूनिट टेस्ट पास होने चाहिए, और CI प्रत्येक पुश के बाद उन्हें Windows और Linux पर फिर से चलाता है। [रिलीज़ चेकलिस्ट](../RELEASE_PROCESS.md) में वास्तविक मशीन पर मैन्युअल इंस्टॉल परीक्षण शामिल है। AI की मदद से किए गए कमिट अब `Assisted-by:` पंक्ति में मॉडल का नाम देते हैं; कई पुराने कमिट में इसके बजाय `Co-Authored-By: Claude` पंक्ति होती है।

## लाइसेंस

कॉपीराइट (c) 2026 translation-robot (co-author)। यह प्रोजेक्ट इस रिपॉजिटरी में स्थित है, [Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite)। प्रोजेक्ट का अपना सोर्स [BSD 3-Clause License](../../LICENSE) के अंतर्गत है। बंडल किए गए उपकरण, Python रनटाइम और मॉडल अपने स्वयं के लाइसेंस रखते हैं; [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) देखें।
