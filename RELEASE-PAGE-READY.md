# 2.4.0 release page — DRAFT / HASHES PENDING

This is a prepared draft, not publication approval. Exact-source builds and automated workflows passed. Artifact names, sizes,
SHA-256 values and downloaded-artifact acceptance remain pending.
`TODO-FINAL-SHA` is deliberately visible wherever final artifact data is unknown.
Expected download filenames and URLs are provisional until compared with final CI.
Release payload source: `7197cd21af46574aeb4c302b733076be78dfdade`.
Both Mac rows now have exact-source verified values; Windows rows remain
`TODO-FINAL-SHA`. The earlier Windows values
were for a different source and cannot be carried forward. Fill rows only from
QA's exact-source POST_PUSH table. The checker binds every filled hash to this
release source, not to the documentation branch commit.

Identify the latest draft changes with
`git log -1 --format=%H -- RELEASE-PAGE-READY.md`.

## Prepared files

- `docs/img/promo-release.svg`: existing artwork and embedded fonts, saved presets
  and subtitle quality review, a 36-second cycle, all 320 property/step holds at
  least as long as the 33.6-second baseline, and an active reduced-motion poster.
- `docs/releases/2.4.0.md`: previous release layout, accurate draft qualification,
  provisional download links, pending sizes/hashes, feature bullets and reporting
  invitation. The unverified numeric bug total is replaced with a nonnumeric heading.
- `site/index.html` and the home pages under `ar bg bn ca cs da de el es fa fi fil
  fr he hi hr hu id it ja ko lt lv ms nb nl pl pt pt-br ro ru sk sl sr sv th tr uk vi
  zh-cn zh-tw`: the same three translated 2.4 blocks in `#whats-new`, current version
  and provisional downloads, with existing 2.3 and earlier history retained.
- `site/facts.json`, `site/llms.txt`, `site/llms-full.txt`, `site/sitemap.xml`:
  draft release facts, the existing full-text generator's output from the unchanged
  README, and last-modified dates for the 42 changed home pages only. Dates in the
  sitemap describe the draft edit, not release publication.
- `tools/check_release_page.py`, `tests/test_release_page_240.py`,
  `tests/fixtures/promo-release-timing-2.3.1.json`: offline draft checks and causal
  negative controls. `tools/check_repo_hygiene.py` and its tests allow this exact
  readiness filename while preserving the general 24-file root limit.

## Validation

Focused command: `python -m pytest tests/test_release_page_240.py tests/test_repo_hygiene.py -q`.
Initial tests failed before the changes. Negative copies shorten one actual hold
below its old duration while leaving the cycle and other holds intact; shorten the
second animation in a declaration; remove one Filipino feature article while
keeping the other two; move a feature outside its release block; and move the whole
block outside `#whats-new`. Each is rejected. The exact readiness-file exception
also has a failing-before check and arbitrary-extra-file controls.

Standalone checks: `python tools/check_release_page.py` (or pass
`--baseline-svg ORIGINAL_SVG_PATH` to parse the original SVG directly),
`python tools/docs_check.py .`, and `python tools/check_repo_hygiene.py`.
The existing non-live site tests and documentation checks are run once against
the draft; final counts and any publication-phase mismatch are recorded below.
Headless previews cover both changed feature frames and reduced motion; the latter
has zero running animations. No rendering result establishes final artifact QA.

Validation results: 83 focused release/hygiene tests passed, including all 42
language pages and artifact-source mismatch controls for all four files. The
current Windows size/hash/source rows are pending; future verified rows may be
filled without changing the source-provenance tests. The earlier combined
non-live site/documentation run had 172 passed and 2 failed: the legacy published
version/date pattern rejects the intentionally unpublished `TODO-FINAL-SHA` date;
the country-table freshness test uses Babel 2.15.0 while its generator specifies
2.18.0, and reproduces a mismatch against the unchanged baseline table. These
remain open final-publication/environment checks, not passing release gates.
The standalone draft checker, documentation checker, hygiene gate, generated
translation check and generated full-text check pass.

## Persian interface and change inventory

The Persian interface catalog is complete. Gemini interface translations do not
require a separate owner review. The draft remains unpublished; publication
approval still applies to the whole release.
The private review attachment contains every changed Persian-page line in full,
with before/after line numbers and structured change groups, including the three
new translated feature sentences, current-version/download references, pending
sizes/date, current and historical heading IDs, and modification metadata.
It also contains the complete unified diff; no changed line is omitted.
Other languages have prepared translations; final editorial review is still pending.

## Open publication gates

- Pin one final candidate and passing Windows installer/Portable, both macOS DMGs,
  full-suite and required real-machine checks to that same source revision.
- Compare actual CI artifact names with the provisional links. Replace every
  `TODO-FINAL-SHA` with verified final sizes, SHA-256 values and the publication
  date in the appropriate fields; retain the draft label until approval.
- Persian interface catalogs are complete, and Gemini interface translations
  require no separate owner review. Finish the existing editorial checks and
  verify the final rendered release page and site after final metadata is filled.
- Adopt the prepared private catalog snapshot before future site regeneration;
  the existing private generator and catalogs remain the build source.
- Rerun final documentation/site gates after final values are available. Legacy
  published-facts date checks require a real publication date, not a draft marker.

Update/version endpoints deferred unchanged: `site/app_config.json`, `core/updates.py`.
No publish-time endpoint commit is prepared. If one becomes necessary, review it
separately and apply its `publish-time only` commit last, after publication.

## Future publishing steps — chief only, after owner approval

1. Integrate this reviewed draft into the final candidate. Adopt the reviewed private
   catalogs, verify the final source pin and all release gates, and fill final artifact
   metadata. Regenerate full text with `python _local/site/tools/build_llms_full.py`;
   validate translations with `python _local/site/tools/site_i18n.py check` and
   `python -m pytest -q -o addopts="" _local/site/tests`. Run the three standalone
   commands above and review the final Persian before/after attachment.
2. With explicit owner approval to publish, remove the draft qualification and
   review the exact final notes/assets. Prepare the final merge and metadata commit
   locally, without pushing `master` yet. Confirm each artifact's source manifest
   binds the approved candidate: a documentation-only commit does not automatically
   transfer build hashes or QA results from a different payload revision.
3. Tag the approved final commit using `git tag v2.4.0 FINAL_RELEASE_SHA`, replacing
   `FINAL_RELEASE_SHA` with the verified approved commit. Push through the documented
   approved-release tag procedure (`ALLOW_TAG_PUSH=1` for `git push origin v2.4.0`).
   Do not move an existing published tag.
4. With `ARTIFACT_DIR` pointing at verified final CI files, create the new release:

   ```powershell
   python tools/fetch_ffmpeg_source.py --out "$ARTIFACT_DIR" --app-version 2.4.0 --check --platform all
   gh release create v2.4.0 --verify-tag --title "Whisper Transcriber Suite 2.4.0" --notes-file docs/releases/2.4.0.md "$ARTIFACT_DIR/WhisperTranscriberSuite-Installer-Windows-v2.4.0.exe" "$ARTIFACT_DIR/WhisperTranscriberSuite-Portable-Windows-v2.4.0.zip" "$ARTIFACT_DIR/WhisperTranscriberSuite-v2.4.0-macOS-arm64.dmg" "$ARTIFACT_DIR/WhisperTranscriberSuite-v2.4.0-macOS-x64.dmg" "$ARTIFACT_DIR/WhisperTranscriberSuite-v2.4.0-source-ffmpeg-9.0.2.tar.xz"
   ```

   The corresponding-source filename above follows `platform/ffmpeg-source.json`
   and must match the actual reviewed source artifact;
   do not execute with an assumed or missing file. Preserve published assets and counts.
5. Verify the published release, all download URLs, sizes/hashes and source attachment
   before `git push origin master`. That approved push is the site's existing Cloudflare
   Pages deployment trigger. Verify the actual deployment and all 42 language pages
   before announcing the site update, so its new links already have published assets.
6. Apply any separately reviewed `publish-time only` endpoint commit last, then verify
   installed-app update behavior against the published release. Nothing in this document
   authorizes those actions before owner approval.

## Exact-source workflow completion

All four workflows succeeded for `7197cd21af46574aeb4c302b733076be78dfdade`: CI [43691496406](https://github.com/Milomilo777/whisper-transcriber-suite/actions/runs/43691496406), Windows installer [43691496465](https://github.com/Milomilo777/whisper-transcriber-suite/actions/runs/43691496465), macOS [43691496479](https://github.com/Milomilo777/whisper-transcriber-suite/actions/runs/43691496479), and CodeQL [43691496474](https://github.com/Milomilo777/whisper-transcriber-suite/actions/runs/43691496474). Existing QA terminal receipts were checked; no workflow was dispatched or polled. This does not fill artifact hashes or establish downloaded-DMG acceptance. The Windows rows stay `TODO-FINAL-SHA` until their exact-source intake completes.

## Exact-source Mac artifact intake

Both source-bound Mac disk images were verified from the existing HW cache and independently read by QA; no second download. Build [43691496479](https://github.com/Milomilo777/whisper-transcriber-suite/actions/runs/43691496479), one downloaded-image replay [43698426946](https://github.com/Milomilo777/whisper-transcriber-suite/actions/runs/43698426946), Intel and Apple-silicon copied-app checks each passed. The release-note rows now use their actual inner-file sizes and SHA-256 values, bound to source `7197cd21af46574aeb4c302b733076be78dfdade`. Native hosts were macOS 15.x; no oldest-supported-system or visible-window rendering result is inferred. Windows byte intake, voice acceptance and stats cutover remain separate release gates.
