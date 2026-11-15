# 2.4.0 release page — DRAFT / ARTIFACTS VERIFIED

Publication remains unapproved. Release payload source:
`7197cd21af46574aeb4c302b733076be78dfdade`.
All four download rows in [the release draft](docs/releases/2.4.0.md) now contain
actual shipping filenames, byte sizes, SHA-256 values and that source revision.
Windows values come from the final exact-source QA intake; both Mac values agree
with independent QA readback and the downloaded-image native acceptance.
The documentation branch revision is not the payload source.

See [public release readiness](docs/RELEASE_READINESS_2.4.0.md) for the passing
checks, open causes, single owners and clock deadlines. The draft is not a
release authorization or a statement that every feature has native acceptance.

## Prepared files

- `docs/releases/2.4.0.md`: release draft, verified four-file artifact table,
  feature bullets, reporter thanks and invitation to report problems.
- `docs/img/promo-release.svg`: existing artwork and embedded fonts, saved presets
  and subtitle quality review, a 36-second cycle, all 320 property/step holds at
  least as long as the 33.6-second baseline, and an active reduced-motion poster.
- `site/index.html` and the 41 translated home pages: three translated 2.4 blocks
  inside `#whats-new`, with earlier release history retained. Persian interface
  catalogs are complete; Gemini interface translations need no separate owner review.
- `site/facts.json`, `site/llms.txt`, `site/llms-full.txt`, `site/sitemap.xml`:
  unpublished draft facts and dates of draft edits. Site size/date fields still
  use `TODO-FINAL-SHA` until the approved publication metadata pass.
- `tools/check_release_page.py`, `tests/test_release_page_240.py` and the existing
  timing fixture: offline artifact-source, language placement and animation checks.
  Hygiene checks retain the exact readiness-file exception and root-file limit.

## Validation

Focused release/hygiene selection: 83 passed, including all 42 language pages,
artifact-source mismatch controls for every file, partial-metadata rejection,
feature-placement mutations and animation hold-duration negative controls.
The final rerun command and result are retained in the private delivery record.

The earlier combined non-live site/documentation run had 172 passed and 2 failed:
the legacy published-version/date check rejects the unpublished date marker;
the country-table freshness check used Babel 2.15.0 rather than its generator's
2.18.0 and reproduced the unchanged-baseline mismatch. These remain named
publication/environment checks, not passing release gates. Earlier standalone
draft, documentation, hygiene, translation and generated-full-text checks passed.
Headless previews covered both changed feature frames and reduced motion;
zero running reduced-motion animations does not establish native app rendering.

## Exact-source accepted evidence

All four workflows succeeded for the payload revision: CI
[43691496406](https://github.com/Milomilo777/whisper-transcriber-suite/actions/runs/43691496406),
Windows installer
[43691496465](https://github.com/Milomilo777/whisper-transcriber-suite/actions/runs/43691496465),
macOS
[43691496479](https://github.com/Milomilo777/whisper-transcriber-suite/actions/runs/43691496479),
and CodeQL
[43691496474](https://github.com/Milomilo777/whisper-transcriber-suite/actions/runs/43691496474).
Existing terminal receipts and actual shipping-byte verification qualify these
four files; the workflow result alone is not byte verification.

Downloaded Mac replay
[43698426946](https://github.com/Milomilo777/whisper-transcriber-suite/actions/runs/43698426946)
passed copied-app native checks on Intel and Apple silicon, two passes total.
Execution used macOS 15.x. Minimum targets (Intel 12, Apple silicon 14) were
checked statically; oldest-supported-system launch and visible-window rendering
are not inferred. Windows acceptance includes 14 native smoke passes with zero
skips, 22 predecessor guard cases, and the 2.3.1 upgrade/uninstall's three phases
and six preserved sentinels. GPU evidence is explicitly carried forward from
`16df0244ae43454d34c97a388754446fc3ab99ff` with unchanged core, not a new run.
Voice and statistics limitations remain in the public readiness table.

## Open publication work

- Resolve the named voice and statistics causes or obtain an explicit maintainer
  disposition; publication remains owner-only.
- Adopt the prepared private catalog snapshot before site regeneration; the
  existing private generator and catalogs remain the build source.
- Fill approved site sizes and publication date; replace remaining date/size
  `TODO-FINAL-SHA` fields only with approved metadata, then run the final
  documentation/site checks and rendered-page editorial acceptance.
- Verify the FFmpeg corresponding-source attachment against
  `platform/ffmpeg-source.json` before release creation.

Update/version endpoints remain `site/app_config.json` and `core/updates.py`.
Any publish-time endpoint change needs separate review and is applied last,
after publication approval and release verification.

## Future publishing steps — chief only, after owner approval

1. Integrate this documentation unit; preserve the payload source identity and
   reuse the verified four shipping files. Adopt the reviewed private catalogs,
   regenerate full text and validate translations with the existing private tools.
2. Obtain explicit owner publication approval, review the final notes/assets,
   complete site metadata and final checks, and remove draft qualification only
   when approved. A documentation-only commit does not rebuild the payload.
3. Use the documented approved-release tag procedure for the approved final
   commit. Preserve all existing published tags, assets and download counts.
4. Verify corresponding FFmpeg source, publish the four verified packages and
   source attachment through the chief's approved release procedure, then verify
   the published files and URLs before the site deployment trigger.
5. Verify the deployment and all 42 language pages. Apply any separately reviewed
   publish-time endpoint change last and verify installed-app update behavior.

Nothing in this draft authorizes tagging, pushing, uploading or deployment.
