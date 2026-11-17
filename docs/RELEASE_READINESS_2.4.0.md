# 2.4.0 release readiness

Updated 2026-11-15 at 19:09; every clock deadline below is Australia/Perth (UTC+08:00)
on that date. Payload identity and verification digests are retained in private local records.
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
| Voice acoustic capture | PASS: exact-source Recorder captured 13.888 seconds; Base CPU transcription delivery passed. The accepted louder take matched 14 contiguous reference words against the eight-word threshold; 103 clipped samples remain recorded. Chief accepted this scope at 19:14; no clean-signal or general accuracy claim follows. | Hardware acceptance lead | 19:14 |
| Persian text-to-speech output | PASS: exact-source OmniVoice CPU generation and save produced a 2.040-second Persian WAV. Peak job committed memory was 5,420,199,936 bytes (5.05 GiB), within a 5,551,566,848-byte (5.17 GiB) cap. This proves short generation/save; reference cloning, playback and a Persian quality score were outside this run. Insufficient memory is caught in the worker and reported as a generic generation error; a specific low-memory explanation is missing. | Hardware acceptance lead | 19:14 |
| Statistics live service | PASS: v2, private R2 and minute cron accepted on `7f52c475`; the subsequent Overview-only version `62c9c5d0` serves 100% with identical protocol/archive/budget sources. Old/new canary storage and clues, seven marker-exclusion paths, two byte-equal archived objects, repeat idempotence and empty input twice passed. Actual cron passed at 19:07; the existing snapshot task exited zero with worker status OK at 19:04. | Release integration lead | 19:31 |
| Statistics request and client acceptance | PASS: all 22 expected HTTP statuses matched; all columns of 12 distinct marked raw rows match the exact expected payload multiset, with zero real contribution. The isolated actual client passed 41 controls, one positive send/storage check, and zero off/stale-identity sends. All 46,286 original run IDs remain. Live rollover was outside this window; reviewed UTC vectors and live client-clock-skew cases cover the stated boundary scope. | Release integration lead | 19:31 |
| Site preparation and checks | PASS: all four verified sizes on 42 language pages; 176 focused site/release/hygiene checks and 84 language/viewport render checks. English/Persian release frames and download cards inspected. Draft version/date and country-table CRLF checks corrected; pinned Babel 2.18.0 data matches. Publication date remains a separate publish-time change. | Release documentation lead | 18:30 |
| Corresponding FFmpeg source | PASS: existing 12,040,788-byte source attachment matches both platform pins, FFmpeg 9.0.2 release identity, SHA-256 and required source/license members; offline helper verification passed. | Release documentation lead | 18:30 |
| Final release verdict | READY TO PUBLISH: technical checks passed or carry the explicitly accepted scope/limitations. The app payload remains frozen at the source above. The independent Overview-first site adjustment does not hold this verdict. | Release integration lead | 19:40 |
| Publication action | OWNER ACTION: the maintainer performs tagging, uploading and publication only after explicit owner confirmation; prepared publish-time metadata stays separate. | Maintainer | After confirmation |

Artifact values are in [the unpublished release draft](releases/2.4.0.md).
Preparation and remaining publication steps are in
[release-page readiness](../RELEASE-PAGE-READY.md).
