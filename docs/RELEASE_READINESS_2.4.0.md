# 2.4.0 release readiness

Prepared 2026-11-15; every clock deadline below is Australia/Perth (UTC+08:00)
on that date. Payload source: `7197cd21af46574aeb4c302b733076be78dfdade`.
PASS describes only the stated scope. An open or failed row requires an explicit
resolution or maintainer disposition before publication. Publication is owner-only.

| Check | Verdict and evidence or named open cause | One owner | Clock deadline |
|---|---|---|---|
| Source qualification | PASS: accepted baseline `e771` full suite 17,064 passed, 52 skipped, zero failed; exact-source delta 458 passed, zero failed; 42/42 interface catalog parity. Baseline and delta are separate runs. | QA lead | 18:30 |
| Exact-source workflows | PASS: CI 43691496406, Windows 43691496465, macOS 43691496479 and CodeQL 43691496474 all succeeded. | QA lead | 18:30 |
| Four shipping files | PASS: actual installer, Portable and both DMG bytes independently verified; all names, sizes, SHA-256 and source bindings agree with the release draft. | QA lead | 18:30 |
| Windows native acceptance | PASS: 14 smoke checks, zero skips; 22 predecessor guard cases; 2.3.1 upgrade/uninstall three phases and six preserved sentinels. | QA lead | 18:30 |
| Both downloaded Mac disk images | PASS: two copied-app native acceptance passes; build 43691496479, replay 43698426946. macOS 15.x execution; declared minimum targets checked statically, not runtime-tested on the oldest supported OS. | Hardware acceptance lead | 18:30 |
| GPU CUDA and AUTO recovery | PASS: actual `16df` Portable CUDA/AUTO evidence accepted for carryforward because the relevant core is unchanged; not relabeled exact-source execution. | Hardware acceptance lead | 18:30 |
| Release draft and language placement | PASS: verified four-file metadata; 83 focused checks include all 42 language pages and causal source/placement/timing controls. | Release documentation lead | 18:30 |
| Voice acoustic capture | FAIL / UNTESTED: prior device transport passed; latest acoustic run captured no audio because 31 compiled Python modules had a runtime-root mismatch. Intelligibility remains untested. The attended hardware window is closed; no retry is scheduled today. | Hardware acceptance lead | 20:00 |
| Persian text-to-speech output | FAIL / UNTESTED: model loading raised MemoryError under the 4 GiB job limit; no generation or WAV output exists. The attended hardware window is closed; no retry is scheduled today. | Hardware acceptance lead | 20:00 |
| Statistics cutover | OPEN: rehearsal 135 assertions and 76 driver R1/R2 checks passed; legacy v1 recovery is complete, but current v1 loses v2 diagnostic clues (three legacy checks pass, two v2-preservation checks fail). Live cutover is pending admission; earliest start 18:45. | Release integration lead | 20:15 |
| Final site metadata and checks | OPEN: unpublished size/date markers remain; approved publication date, final rendered/editorial acceptance and final site checks are pending. Earlier date-pattern failure and Babel 2.15.0/2.18.0 country-table mismatch remain explicit. | Release documentation lead | 20:30 |
| Corresponding FFmpeg source | OPEN: final corresponding-source attachment must be verified against the manifest before publication. | Release integration lead | 20:30 |
| Final release verdict | OPEN: reconcile voice disposition, statistics outcome and publication checks. Passing artifact QA does not close these rows. | Release integration lead | 20:30 |
| Publication approval | OPEN: explicit owner approval is required for tagging, uploading, pushing and deployment. | Maintainer | 20:30 |

Artifact values are in [the unpublished release draft](releases/2.4.0.md).
Preparation and remaining publication steps are in
[release-page readiness](../RELEASE-PAGE-READY.md).
