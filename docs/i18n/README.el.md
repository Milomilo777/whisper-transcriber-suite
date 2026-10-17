<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**Δωρεάν, εκτός σύνδεσης απομαγνητοφώνηση και υπότιτλοι για μεγάλες ηχογραφήσεις στη γλώσσα σας — σε έναν συνηθισμένο φορητό υπολογιστή, χωρίς λογαριασμό και χωρίς μεταφόρτωση ήχου.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Λήψη για Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS και Linux: δείτε την ενότητα [Λήψη](#download).

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
<b>Ελληνικά</b> ·
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

## Για ποιους προορίζεται

Για δημιουργούς υποτίτλων, μεταφραστές, ερευνητές και δημοσιογράφους που μετατρέπουν μεγάλες 
ηχογραφήσεις (συνεντεύξεις, διαλέξεις, ομιλίες, βίντεο) σε κείμενο ή υπότιτλους. 
Σύρετε ένα αρχείο ήχου ή βίντεο και η απομαγνητοφώνηση θα γραφτεί δίπλα του. Η μηχανή αναγνώρισης ομιλίας εκτελείται στον δικό σας υπολογιστή, επομένως δεν υπάρχει
κόστος ανά λεπτό και, μόλις γίνει λήψη του μοντέλου, δεν απαιτείται σύνδεση στο διαδίκτυο.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="Η καρτέλα Transcribe: περιοχή απόθεσης αρχείων, επιλογή μηχανής και γλώσσας, επιλογές για ετικέτες ομιλητών και χρονοσημάνσεις λέξεων" width="80%">
</div>

## Τι νέο υπάρχει στην έκδοση 2.0

- **Ταχύτητα και υπολειπόμενος χρόνος:** η καρτέλα Ουρά (Queue) εμφανίζει την ταχύτητα κάθε εργασίας και έναν κατά προσέγγιση υπολειπόμενο χρόνο.
- **Βίντεο με υπότιτλους από έναν σύνδεσμο:** λήψη, απομαγνητοφώνηση και ενσωμάτωση υποτίτλων ως μία εργασία ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Το κείμενο ως ιστοσελίδα:** ένα αρχείο `.html` με αναζήτηση και αναπαραγωγή με κλικ που λειτουργεί εκτός σύνδεσης σε οποιοδήποτε πρόγραμμα περιήγησης.
- **Εργασία εκτός σύνδεσης που μπορείτε να ελέγξετε:** με την Εργασία εκτός σύνδεσης (Work offline) ενεργοποιημένη, μια γραμμή κατάστασης δείχνει εάν η εφαρμογή ή μια διεργασία που ξεκίνησε έχει σύνδεση στο δίκτυο.
- **Μετάφραση στα Αγγλικά:** η μη αγγλική ομιλία γίνεται αγγλικοί υπότιτλοι με ένα πέρασμα.
- **Γρήγορη εκκίνηση:** οι νέες εγκαταστάσεις κάνουν τρεις ερωτήσεις, και ένα δείγμα 18 δευτερολέπτων δείχνει αμέσως το αποτέλεσμα.
- **Αναφορά προβλήματος:** από το μενού Βοήθεια (Help), χωρίς λογαριασμό GitHub.
- **macOS:** μενού εφαρμογής με Ρυθμίσεις (Command-κόμμα), Φωτεινό και Σκοτεινό θέμα που ακολουθούν το σύστημα, ειδοποιήσεις. **Windows:** πρόοδος στη γραμμή εργασιών και σκούρες γραμμές τίτλου.

Πλήρης λίστα: [../CHANGELOG.md](../CHANGELOG.md).

## Λειτουργίες

- **Τοπικές μηχανές:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (προεπιλογή), whisper.cpp και NVIDIA Parakeet, για τις πολλές γλώσσες που
  αναγνωρίζει το Whisper. Χρησιμοποιεί κάρτα γραφικών NVIDIA
  μέσω CUDA όταν είναι δυνατόν, διαφορετικά τον επεξεργαστή (CPU).
- **Η εφαρμογή στη γλώσσα σας:** Μενού, κουμπιά και μηνύματα σε 42 γλώσσες (μηχανική
  μετάφραση, με σχετική σήμανση· οι διορθώσεις είναι ευπρόσδεκτες). Ακολουθεί τη
  γλώσσα του συστήματός σας ή επιλέγετε μία στις Ρυθμίσεις για προχωρημένους. Τα
  Περσικά, τα Αραβικά και τα Εβραϊκά προσφέρονται προς το παρόν στα Windows.
- **14 μορφές εξόδου:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX και
  PDF, συν τις μορφές oTranscribe, ELAN, InqScribe και Express Scribe. Tα DOCX
  και PDF σχεδιάζουν κάθε γραφή, και τα Περσικά, Αραβικά και Ουρντού διαβάζονται από δεξιά προς τα αριστερά με ενωμένα γράμματα.
- **Ιστοσελίδα για κοινή χρήση:** αποθηκεύστε την ολοκληρωμένη απομαγνητοφώνηση ως ένα αρχείο `.html` 
  που λειτουργεί εκτός σύνδεσης σε κάθε πρόγραμμα περιήγησης· κάντε κλικ σε μια λέξη για να την ακούσετε, αναζητήστε, μεταβείτε σε κεφάλαια.
- **Ετικέτες ομιλητών** χωρίς λογαριασμό Hugging Face, μαζί με χρονοσημάνσεις λέξεων (word timestamps) και περικοπή χρονικού εύρους.
- **Οι διακοπείσες εργασίες συνεχίζονται** από το τελευταίο τους σημείο ελέγχου (checkpoint) αντί να ξεκινήσουν από την αρχή (προεπιλεγμένος κινητήρας).
- **Διαδικτυακά βίντεο:** λήψη από οποιονδήποτε ιστότοπο που υποστηρίζει το [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  και απομαγνητοφώνηση όταν ολοκληρωθεί η λήψη.
- **Σύνδεσμος σε βίντεο με υπότιτλους:** ένα κλικ μετατρέπει έναν σύνδεσμο σε `<τίτλος>-subbed.mp4` 
  με ενσωματωμένους τους υπότιτλους: λήψη, απομαγνητοφώνηση και ενσωμάτωση σε μία εργασία στην ουρά ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Ζωντανά:** απομαγνητοφωνήστε ένα μικρόφωνο, ή τον ήχο του συστήματος στα Windows, καθώς 
  συμβαίνει ([../LIVE.md](../LIVE.md)).
- **Ουρά παρτίδας και φάκελος παρακολούθησης (watched folder)** για πολλά αρχεία.
- **Λειτουργία τοπικού δικτύου:** μια σελίδα απομαγνητοφώνησης και ένα API συμβατό με το OpenAI για
  τις άλλες συσκευές στο δίκτυό σας ([../SERVER.md](../SERVER.md)).
- **Προαιρετικά, απενεργοποιημένα από προεπιλογή:** εργαλεία AI για ένα ολοκληρωμένο κείμενο (περίληψη,
  ερωτήσεις, δίγλωσσο SRT) και μετατροπή κειμένου σε φωνή εκτός σύνδεσης με κλωνοποίηση φωνής.

Πώς συγκρίνεται με τα Subtitle Edit, Vibe, Buzz, noScribe και aTrain, 
καθώς και πότε μια άλλη εφαρμογή είναι η καλύτερη επιλογή: 
**[../COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Λήψη

Τελευταία έκδοση: **[σελίδα εκδόσεων (releases)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| Αρχείο | Για |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 ή 11, 64-bit. Οι περισσότεροι χρήστες θέλουν αυτό. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows χωρίς εγκατάσταση: αποσυμπιέστε και εκτελέστε. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Mac με Apple silicon, macOS 14 ή νεότερο. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Mac με επεξεργαστή Intel, macOS 10.15 ή νεότερο. |

Στο Linux εκτελείται από τον πηγαίο κώδικα: [../../platform/linux/README.md](../../platform/linux/README.md).

Το ενσωματωμένο FFmpeg είναι μια έκδοση GPL. Ο αντίστοιχος πηγαίος κώδικας επισυνάπτεται σε κάθε έκδοση ως
αρχεία `WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*`· οι ακριβείς σύνδεσμοι βρίσκονται στο [../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

Τα ffmpeg και yt-dlp περιλαμβάνονται. Κατά την πρώτη εκκίνηση ένα παράθυρο γρήγορης εκκίνησης επιλέγει 
το μοντέλο ομιλίας για τη γλώσσα σας: Γρήγορο (Μικρό, περίπου 500 MB) ή Καλύτερη
ποιότητα (έως περίπου 3 GB)· γίνεται λήψη μία φορά, κατά την πρώτη χρήση. Υπολογίστε ότι θα χρειαστείτε 8 GB
μνήμης RAM· σε CPU τα μοντέλα Large χρειάζονται περίπου 1,5–2,5 φορές τη διάρκεια
του ήχου και τα μοντέλα Small περίπου τη μισή, μια κάρτα γραφικών NVIDIA είναι πολύ πιο γρήγορη. Οι εκδόσεις για Windows δεν φέρουν ψηφιακή υπογραφή και οι εκδόσεις για Mac δεν είναι
επαληθευμένες (notarized), επομένως το SmartScreen και το Gatekeeper θα προειδοποιήσουν στην πρώτη εκκίνηση·
το [../INSTALL.md](../INSTALL.md) δείχνει πού πρέπει να κάνετε κλικ. Για να ενημερώσετε την εφαρμογή, εκτελέστε το
νεότερο πρόγραμμα εγκατάστασης πάνω από το παλιό· οι ρυθμίσεις διατηρούνται.

**Λήψεις ανά έκδοση** (κάθε σήμα μετράει μόνο τη συγκεκριμένη 
έκδοση — οι παλαιότερες εκδόσεις παραμένουν δημοσιευμένες και οι μετρήσεις τους δεν 
μηδενίζονται ποτέ):

[![v2.1.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.1.0/total?label=v2.1.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.1.0)
[![v2.0.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.0.0/total?label=v2.0.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0)
[![v1.9.3](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.3/total?label=v1.9.3&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.3)
[![v1.9.1](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.1/total?label=v1.9.1&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.1)
[![v1.9.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.0/total?label=v1.9.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.0)
[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

## Τι φεύγει από τον υπολογιστή σας

Με τις προεπιλεγμένες ρυθμίσεις ο ήχος και τα κείμενά σας παραμένουν στον υπολογιστή σας.
Η εφαρμογή χρησιμοποιεί το δίκτυο για:

- λήψη ενός μοντέλου ή ενός προαιρετικού στοιχείου την πρώτη φορά που απαιτείται·
- τις διαδικτυακές ρυθμίσεις της κατά την εκκίνηση και έναν καθημερινό έλεγχο ενημερώσεων στο GitHub, που
  μόνο σας ενημερώνει για μια νέα έκδοση·
- στατιστικά χρήσης, ενεργοποιημένα από προεπιλογή, μετά από κάθε ολοκληρωμένη απομαγνητοφώνηση: μοντέλο, 
  γλώσσα, διάρκειες, πλήθος λέξεων, έκδοση εφαρμογής, λειτουργικό σύστημα, μέγεθος CPU και 
  μνήμης, και περιοχή, ποτέ το όνομα του αρχείου. Απενεργοποιήστε τα στο μενού 
  **Help → Usage statistics**.

Ο ήχος ή το κείμενο αποστέλλεται μόνο εάν επιλέξετε έναν κινητήρα cloud (Gemini API 
ή Google Cloud Speech-to-Text) ή εάν συνδέσετε έναν απομακρυσμένο πάροχο AI εσείς οι ίδιοι. 
Η επιλογή **File → Work offline** σταματάει όλες αυτές τις συνδέσεις. Κάθε σύνδεση αναφέρεται στο 
[../CONFIG.md](../CONFIG.md#network-use).

## Τεκμηρίωση

[Εγκατάσταση](../INSTALL.md) · [Διαμόρφωση](../CONFIG.md) ·
[Ζωντανή απομαγνητοφώνηση](../LIVE.md) · [Λειτουργία τοπικού δικτύου και API](../SERVER.md) ·
[Μηχανές Cloud](../CLOUD_STT.md) · [Αρχιτεκτονική](../ARCHITECTURE.md) ·
[Ιστορικό αλλαγών](../CHANGELOG.md) · [Όλη η τεκμηρίωση](../README.md)

## Μεταγλώττιση από τον πηγαίο κώδικα (Build)

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Απαιτείται Python 3.11 ή νεότερη έκδοση. Ροές εργασιών μεταγλώττισης (Build pipelines): [../BUILD.md](../BUILD.md). Δοκιμές (Tests) και pull requests: 
[../../CONTRIBUTING.md](../../CONTRIBUTING.md).

## Συνεισφορά και επικοινωνία

- **Σφάλματα και αιτήματα για νέες λειτουργίες:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Ερωτήσεις και ιδέες:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Οτιδήποτε άλλο:** μέσω email, από την
  [ενότητα Επικοινωνίας (Contact) του ιστότοπου](https://whisper-transcriber-suite.pages.dev/#contact)
- **Αναφορές ασφαλείας:** [../../SECURITY.md](../../SECURITY.md)

Αυτό το έργο ακολουθεί τον [Κώδικα Δεοντολογίας Συνεισφερόντων (Contributor Covenant)](../../.github/CODE_OF_CONDUCT.md). 
Εάν η εφαρμογή σας εξοικονομεί χρόνο, ένα Αστέρι (Star) στην κορυφή αυτής της σελίδας βοηθά άλλα άτομα 
να τη βρουν.

## Πώς κατασκευάστηκε αυτό το έργο

Ο συντηρητής το αναπτύσσει με μεγάλη βοήθεια από AI βοηθούς προγραμματισμού (κυρίως το Claude). Οι έλεγχοι τύπων (Type checks) 
και οι δοκιμές μονάδας (unit tests) πρέπει να είναι επιτυχείς πριν από κάθε commit, και το CI τις εκτελεί ξανά σε Windows και Linux μετά από 
κάθε push. Η [λίστα ελέγχου κυκλοφορίας (release checklist)](../RELEASE_PROCESS.md) περιλαμβάνει μια χειροκίνητη δοκιμή εγκατάστασης σε 
πραγματικό μηχάνημα. Τα commits που γίνονται με βοήθεια AI πλέον αναφέρουν το μοντέλο σε μια γραμμή `Assisted-by:`· πολλά παλαιότερα 
φέρουν αντ' αυτού μια γραμμή `Co-Authored-By: Claude`.

## Άδεια χρήσης

Copyright (c) 2026 translation-robot (co-author). Το έργο φιλοξενείται σε αυτό το αποθετήριο,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite). 
Ο πηγαίος κώδικας του ίδιου του έργου υπόκειται στην [Άδεια BSD 3-Clause](../../LICENSE). Τα ενσωματωμένα 
εργαλεία, το περιβάλλον εκτέλεσης της Python και τα μοντέλα διατηρούν τις δικές τους άδειες χρήσης· δείτε το
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
