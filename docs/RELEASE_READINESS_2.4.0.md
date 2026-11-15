# 2.4.0 release readiness

Updated 2026-11-15 at 19:09; every clock deadline below is Australia/Perth (UTC+08:00)
on that date. Payload source: `7197cd21af46574aeb4c302b733076be78dfdade`.
PASS describes only the stated scope. An open or failed row requires an explicit
resolution or maintainer disposition before publication. The app payload remains frozen.

| Check | Verdict and evidence or named open cause | One owner | Clock deadline |
|---|---|---|---|
| Source qualification | PASS: accepted baseline `e771` full suite 17,064 passed, 52 skipped, zero failed; exact-source delta 458 passed, zero failed; 42/42 interface catalog parity. Baseline and delta are separate runs. | QA lead | 18:30 |
| Exact-source workflows | PASS: CI 43691496406, Windows 43691496465, macOS 43691496479 and CodeQL 43691496474 all succeeded. | QA lead | 18:30 |
| Four shipping files | PASS: actual installer, Portable and both DMG bytes independently verified; all names, sizes, SHA-256 and source bindings agree with the release draft. | QA lead | 18:30 |
| Windows native acceptance | PASS: 14 smoke checks, zero skips; 22 predecessor guard cases; 2.3.1 upgrade/uninstall three phases and six preserved sentinels. | QA lead | 18:30 |
| Both downloaded Mac disk images | PASS: two copied-app native acceptance passes; build 43691496479, replay 43698426946. macOS 15.x execution; declared minimum targets checked statically, not runtime-tested on the oldest supported OS. | Hardware acceptance lead | 18:30 |
| GPU CUDA and AUTO recovery | PASS: actual `16df` Portable CUDA/AUTO evidence accepted for carryforward because the relevant core is unchanged; not relabeled exact-source execution. | Hardware acceptance lead | 18:30 |
| Release draft and language placement | PASS: verified four-file metadata; 83 focused checks include all 42 language pages and causal source/placement/timing controls. | Release documentation lead | 18:30 |
| Voice acoustic capture | FAIL: exact-source Recorder captured 13.888 seconds and Base CPU transcription delivery passed after a harness-only cache fix. Normal speech matched five contiguous reference words (eight required); the louder attempt matched 14 but had 103 clipped samples. The cause remains unisolated; an environment cause or product defect is not proved. | Hardware acceptance lead | 19:30 |
| Persian text-to-speech output | IN PROGRESS: the existing exact-source 8 GiB job is running; worker stop is 19:10 and the hardware result is due 19:15. Generation and WAV acceptance await that existing handoff. The earlier 4 GiB load failure does not describe this current attempt. | Hardware acceptance lead | 19:15 |
| Statistics live service | PASS: backend `7f52c475` serves 100% with v2, R2 and minute cron. Old/new canary storage and diagnostic clues, seven marker-exclusion checks, two byte-equal archived objects, repeat idempotence and the empty archive twice passed. Actual scheduled cron passed at 19:07; the natural statistics snapshot exited zero with worker status OK at 19:04. | Release integration lead | 19:07 |
| Statistics remaining acceptance | IN PROGRESS: complete the remaining paced request matrix and actual-client acceptance from the already passing live service gates. | Release integration lead | 20:00 |
| Site preparation and checks | PASS: all four verified sizes on 42 language pages; 176 focused site/release/hygiene checks and 84 language/viewport render checks. English/Persian release frames and download cards inspected. Draft version/date and country-table CRLF checks corrected; pinned Babel 2.18.0 data matches. Publication date remains a separate publish-time change. | Release documentation lead | 18:30 |
| Corresponding FFmpeg source | PASS: existing 12,040,788-byte source attachment matches both platform pins, FFmpeg 9.0.2 release identity, SHA-256 and required source/license members; offline helper verification passed. | Release documentation lead | 18:30 |
| Final release verdict | OPEN: reconcile voice disposition, statistics outcome and publication checks. Passing artifact QA does not close these rows. | Release integration lead | 20:30 |
| Publication action | OPEN: the maintainer performs the final publication action after the release verdict; the prepared publish-time metadata remains separate from the frozen app payload. | Maintainer | 20:30 |

Artifact values are in [the unpublished release draft](releases/2.4.0.md).
Preparation and remaining publication steps are in
[release-page readiness](../RELEASE-PAGE-READY.md).
