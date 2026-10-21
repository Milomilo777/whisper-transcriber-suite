<div align="center" dir="rtl">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**תמלול וכתוביות בחינם, במצב לא מקוון, עבור הקלטות ארוכות בשפה שלך — על מחשב נייד רגיל, ללא צורך בחשבון וללא העלאת שמע לאינטרנט.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![downloads](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/total?label=downloads&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [הורדה עבור Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

עבור macOS ו-Linux: ראו סעיף [הורדה](#download).

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
<b>עברית</b> ·
<a href="README.lv.md">Latviešu</a> ·
<a href="README.ca.md">Català</a> ·
<a href="README.bn.md">বাংলা</a> ·
<a href="README.fil.md">Filipino</a>
</p>

<!-- language-links:end -->
<!-- translated from README.md at commit 66585d5 -->

</div>

<div dir="rtl">

## למי זה מיועד

ליוצרי כתוביות, מתרגמים, חוקרים ועיתונאים שהופכים הקלטות ארוכות 
(ראיונות, הרצאות, נאומים, סרטונים) לטקסט או כתוביות.
גררו קובץ שמע או וידאו והתמליל ייכתב לצידו. מנוע זיהוי הדיבור פועל 
על המחשב האישי שלכם, לכן אין עלות לפי דקה, ולאחר הורדת המודל, 
אין צורך בחיבור לאינטרנט.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="לשונית Transcribe: אזור לגרירת קבצים, בוררי מנוע ושפה, ואפשרויות לתוויות דוברים ולחותמות זמן למילים" width="80%">
</div>

## מה חדש בגרסה 2.0

- **מהירות וזמן נותר:** לשונית התור (Queue) מציגה את המהירות של כל משימה ואת הזמן שנותר בקירוב.
- **וידאו עם כתוביות מקישור:** הורדה, תמלול והטמעת כתוביות (burn-in) כמשימה אחת ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **תמליל כדף אינטרנט:** קובץ `.html` יחיד עם אפשרות חיפוש ולחיצה להשמעה, שעובד במצב לא מקוון בכל דפדפן.
- **עבודה לא מקוונת ניתנת לבדיקה:** כאשר המצב "Work offline" מופעל, שורת סטטוס מראה האם לאפליקציה או לתהליך שהיא הפעילה יש חיבור לרשת.
- **תרגום לאנגלית:** דיבור שאינו באנגלית הופך לכתוביות באנגלית במעבר אחד.
- **התחלה מהירה:** התקנות חדשות שואלות שלוש שאלות, וקליפ דגימה של 18 שניות מציג מיד תוצאה.
- **דיווח על בעיה:** מתפריט העזרה (Help), ללא צורך בחשבון GitHub.
- **macOS:** תפריט אפליקציה עם הגדרות (Command-פסיק), ערכת נושא בהירה וכהה שעוקבת אחרי המערכת, והתראות. **Windows:** התקדמות בשורת המשימות (taskbar) ושורות כותרת כהות.

רשימה מלאה: [../CHANGELOG.md](../CHANGELOG.md).

## תכונות

- **מנועים מקומיים:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (ברירת מחדל), whisper.cpp ו-NVIDIA Parakeet, עבור השפות הרבות 
  ש-Whisper מזהה. משתמש בכרטיס מסך של NVIDIA
  דרך CUDA כאשר הדבר אפשרי, ואם לא - במעבד הראשי (CPU).
- **האפליקציה בשפה שלך:** תפריטים, כפתורים והודעות ב-42 שפות (תרגום מכונה, מסומן
  ככזה; תיקונים יתקבלו בברכה). היא פועלת לפי שפת המערכת שלך, או שאפשר לבחור שפה
  בהגדרות מתקדמות. פרסית, ערבית ועברית זמינות בינתיים ב-Windows.
- **14 פורמטים של פלט:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX 
  ו-PDF, בנוסף לפורמטים של oTranscribe, ELAN, InqScribe ו-Express Scribe. קובצי
  DOCX ו-PDF תומכים בכל סוגי הכתב, כולל עברית, פרסית, ערבית ואורדו הנקראים מימין לשמאל.
- **דף אינטרנט הניתן לשיתוף:** שמרו תמליל מוכן כקובץ `.html` יחיד 
  שעובד במצב לא מקוון בכל דפדפן; לחצו על מילה כדי לשמוע אותה, חפשו, וקפצו לפרקים.
- **תוויות דוברים** ללא צורך בחשבון Hugging Face, בנוסף לחותמות זמן למילים (word timestamps) 
  וחיתוך לפי טווח זמן.
- **משימות שנקטעו ממשיכות** מהשמירה האחרונה שלהן (checkpoint) במקום להתחיל 
  מחדש (במנוע ברירת המחדל).
- **סרטוני אינטרנט:** הורידו מכל אתר ש-[yt-dlp](https://github.com/yt-dlp/yt-dlp) 
  תומך בו, ובצעו תמלול כשההורדה מסתיימת.
- **קישור לווידאו עם כתוביות:** לחיצה אחת (סימון V) הופך קישור לקובץ `<title>-subbed.mp4`
  כשהכתוביות מוטמעות בתוכו: הורדה, תמלול והטמעה במשימה אחת בתור 
  ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **חי (Live):** תמללו מיקרופון, או את שמע המערכת ב-Windows, בזמן 
  אמת ([../LIVE.md](../LIVE.md)).
- **תור עיבוד באצ' (Batch queue) ותיקיית מעקב (watched folder)** עבור קבצים רבים.
- **מצב רשת מקומית:** דף תמלול ו-API התואם ל-OpenAI עבור 
  המכשירים האחרים ברשת שלכם ([../SERVER.md](../SERVER.md)).
- **אופציונלי, כבוי כברירת מחדל:** כלי AI עבור תמליל מוכן (סיכום, 
  שאלות, SRT דו-לשוני), וטקסט-לדיבור במצב לא מקוון עם שיבוט קול (voice cloning).

השוואה מול Subtitle Edit, Vibe, Buzz, noScribe ו-aTrain, 
וכן מתי אפליקציה אחרת עשויה להיות הבחירה הטובה יותר: 
**[../COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## הורדה

הגרסה האחרונה: **[דף שחרור גרסאות (releases)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| קובץ | מיועד ל- |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 או 11, 64-bit. מתאים לרוב המשתמשים. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows ללא התקנה: פשוט חלצו והפעילו. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | מחשבי Mac עם שבבי Apple silicon (סדרת M), מגרסה macOS 14 ומעלה. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | מחשבי Mac עם מעבד Intel, מגרסה macOS 10.15 ומעלה. |

ב-Linux האפליקציה פועלת מקוד המקור (source): [../../platform/linux/README.md](../../platform/linux/README.md).

ה-FFmpeg המצורף הוא גרסת GPL. קוד המקור התואם לו מצורף לכל גרסה 
כקובצי `WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*`; הקישורים המדויקים מופיעים ב-
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

הכלים ffmpeg ו-yt-dlp כלולים באריזה. בהפעלה הראשונה, חלון התחלה מהירה יבחר 
את מודל הדיבור עבור השפה שלכם: מהיר (Small, כ-500 MB) או האיכות 
הטובה ביותר (עד כ-3 GB); ההורדה מתבצעת פעם אחת, בשימוש הראשון. רצוי שיהיה לכם 8 GB
של זיכרון RAM; על מעבד (CPU), המודלים הגדולים (Large) לוקחים פי 1.5–2.5 מאורך
השמע, והמודלים הקטנים (Small) כחצי מזמן השמע. כרטיס מסך של NVIDIA יהיה הרבה יותר מהיר. קובצי ה-Windows אינם חתומים דיגיטלית וקובצי ה-Mac אינם 
מאושרים (notarized), ולכן SmartScreen ו-Gatekeeper יציגו אזהרה בהפעלה הראשונה;
[../INSTALL.md](../INSTALL.md) מראה על מה צריך ללחוץ. כדי לעדכן, הפעילו את 
תוכנת ההתקנה החדשה מעל הישנה; ההגדרות שלכם יישמרו.

**הורדות לפי גרסה** (כל תג סופר רק את ההורדות של 
אותה גרסה — גרסאות ישנות נשארות זמינות והספירה שלהן אינה 
מתאפסת לעולם):

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

## מה יוצא מהמחשב שלכם

עם הגדרות ברירת המחדל, השמע והתמלילים שלכם נשארים על המחשב.
האפליקציה כן משתמשת ברשת עבור:

- הורדת מודל או רכיב אופציונלי בפעם הראשונה שיש בו צורך;
- ההגדרות המקוונות שלה בעת ההפעלה, ובדיקת עדכונים יומית מ-GitHub, שרק
  מודיעה לכם אם קיימת גרסה חדשה;
- סטטיסטיקות שימוש, שמופעלות כברירת מחדל, לאחר כל תמלול שמסתיים: מודל, 
  שפה, זמנים, ספירת מילים, גרסת האפליקציה, מערכת הפעלה, מעבד (CPU) 
  וגודל זיכרון, ואזור, אך לעולם לא שם הקובץ. ניתן לכבות זאת תחת
  **Help → Usage statistics**.

שמע או טקסט נשלחים החוצה רק אם תבחרו במנוע ענן (Gemini API 
או Google Cloud Speech-to-Text) או אם תחברו בעצמכם ספק בינה מלאכותית מרוחק.
האפשרות **File → Work offline** עוצרת את כל התקשורת הזו. כל התחברות לרשת מפורטת ב-
[../CONFIG.md](../CONFIG.md#network-use).

## תיעוד (Documentation)

[התקנה](../INSTALL.md) · [הגדרות (Configuration)](../CONFIG.md) ·
[תמלול חי (Live transcription)](../LIVE.md) · [מצב רשת מקומית ו-API](../SERVER.md) ·
[מנועי ענן](../CLOUD_STT.md) · [ארכיטקטורה](../ARCHITECTURE.md) ·
[יומן שינויים (Changelog)](../CHANGELOG.md) · [כל המסמכים](../README.md)

## בנייה מקוד מקור (Build from source)

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

דורש Python 3.11 ומעלה. תהליכי בנייה: [../BUILD.md](../BUILD.md). בדיקות (Tests) ובקשות משיכה (pull requests):
[../../CONTRIBUTING.md](../../CONTRIBUTING.md).

## תרומה ויצירת קשר

- **באגים ובקשות לתכונות חדשות:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **שאלות ורעיונות:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **כל דבר אחר:** במייל, דרך 
  [אזור צור קשר (Contact) באתר האינטרנט](https://whisper-transcriber-suite.com/#contact) · ✉ [admin@whisper-transcriber-suite.com](mailto:admin@whisper-transcriber-suite.com)
- **דיווחי אבטחה:** [../../SECURITY.md](../../SECURITY.md)

פרויקט זה פועל לפי [קוד ההתנהגות של תורמים (Contributor Covenant)](../../.github/CODE_OF_CONDUCT.md).
אם האפליקציה חוסכת לכם זמן, סימון 'כוכב' (Star) בראש דף זה יעזור לאנשים אחרים
למצוא אותה.

## איך הפרויקט הזה נבנה

המתחזק מפתח את האפליקציה בעזרתם הרבה של עוזרי כתיבת קוד מבוססי AI (בעיקר Claude). בדיקות טיפוסים (Type checks)
ובדיקות יחידה (unit tests) חייבות לעבור לפני כל קומיט (commit), ומערכת ה-CI מריצה אותן שוב ב-Windows וב-Linux לאחר 
כל דחיפה (push). [רשימת תיוג השחרור (release checklist)](../RELEASE_PROCESS.md) כוללת בדיקת התקנה ידנית על 
מכונה אמיתית. קומיטים שנעשו בעזרת AI מציינים כעת את המודל בשורת `Assisted-by:`; לקומיטים ישנים רבים יש 
במקום זאת שורת `Co-Authored-By: Claude`.

## רישיון (License)

Copyright (c) 2026 translation-robot (co-author). הפרויקט מאוחסן במאגר זה,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
קוד המקור של הפרויקט עצמו נמצא תחת [רישיון BSD 3-Clause](../../LICENSE). 
כלים מצורפים, סביבת הריצה של Python והמודלים שומרים על הרישיונות שלהם; ראו 
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
</div>
