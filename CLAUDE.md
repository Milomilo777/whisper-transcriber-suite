# Whisper Project — durable instructions for any Claude Code session

This file is auto-loaded into every Claude Code session opened
inside this repository. Read it on first turn; follow it for the
whole session.

## Commit + push cadence — DURABLE RULE

Commit **locally and often** so nothing is lost to a power outage /
crash — every coherent feature, fix, refactor, non-trivial docs change,
or test batch gets its own local commit as soon as it passes pyright +
the relevant tests.

**PUSH immediately, in the same session, right after every commit**
(2026-08-14, owner request — this REVERSES the older 2026-05-26
"batch pushes, don't push after every commit" rule below; that rule
no longer applies). Do not accumulate commits locally waiting for a
batch — each commit gets pushed as soon as it lands.

<details>
<summary>Superseded 2026-05-26 rule (kept for history only — do not follow)</summary>

Push in batches, not after every commit (owner request: *"keep
changing things locally so nothing is lost, but send several changes
together to the repo/branch so it doesn't get noisy"*). Accumulate a
few related commits locally, then push them together.

</details>

**Release cadence: slow down.** Do NOT cut a new version for every small
change (2026-05-26, owner: *"half or a third the speed"*). Batch several
features/fixes into one release. This release-cadence rule is unchanged
by the 2026-08-14 push-cadence update above — pushing to `master`
promptly is independent from cutting a new tagged release.

So: frequent local commits → immediate push, same session → infrequent release.

Atomic-commit hygiene:

- One coherent change per commit, even if that means 6–8 small
  commits in a row.
- Commit messages follow the project's existing style: imperative
  subject ≤ 70 chars, blank line, body explaining the *why*.
- Don't squash commits across logical groups.

## Changelog entries — keep them short (2026-07-04, owner request)

`docs/CHANGELOG.md` bullets must stay skimmable: 1–3 sentences —
what broke/changed + the fix, not a root-cause narrative. The full
investigation (repro steps, why it happened, alternatives considered)
belongs in the commit message and/or `docs/SESSION_HANDOFF_NEXT.md`,
never in the changelog itself.

## New capabilities need real-hardware testing before release (2026-08-14, owner request)

Every time a new capability is added, it must be exercised for real on
this development machine before it ships — not just covered by unit
tests with stubs/mocks. This machine has a real microphone that is
always on and connected, so any mic-dependent path (the Live tab,
`core/recorder.py`, anything gated on `sounddevice`/`pyaudiowpatch`)
must actually be run against that real microphone, not merely asserted
importable.

**Why:** a colleague testing the Live tab hit `sounddevice not
installed — pip install sounddevice to enable microphone recording.
Cannot record audio live`. A real run on real hardware before release
would have caught this gap before it reached a user.

**How to apply:** before calling a new feature release-ready, actually
drive it end-to-end on this machine (real mic input for audio-capture
features, a real file for a new format/backend, etc.), in addition to
the existing pyright + pytest gate — the automated gate does not
substitute for this.

## Release assets must track every bug fix (2026-07-04, owner request)

Any bug fix that touches shipped code is not actually "done" until the
affected release assets are rebuilt and re-uploaded — a fix sitting
only in source control doesn't help a user running the installed app.
Default: rebuild + `gh release upload vX.Y.Z ... --clobber` the
Windows Setup-Standard + Portable at minimum (see `docs/BUILD.md`
"Rebuild without bumping the version"). **Do NOT rebuild macOS** —
see the "macOS builds — NEVER" section below; that rule overrides
this one for macOS specifically, even though `core/` and `app/` are
cross-platform.

When a build is about to start (PyInstaller / Inno Setup):

- Make sure every modified file is either committed or
  deliberately scratch (and noted in CLAUDE.md context as
  "intentionally not committed yet — see <commit X>").

## Permitted operations

The repository is now a **single mainline: `master`**. On 2026-05-25 the
`chore/cleanup-hardening` and `basic-edition` branches were folded in and
deleted; their tips are preserved as the tags
`archive/cleanup-hardening-final` and `archive/basic-edition`, and the
old pre-merge master as `archive/master-pre-merge`. master carries the
v1.3.5 release. Pre-authorised for all future hands-off sessions:

  - `git push origin master`

Cutting a release (`git tag`, `gh release create`/`edit`) is NOT on this
list — see "Cutting a release" below.

The following remain forbidden unless the user explicitly
asks for them in the current session:

  - Building or dispatching a macOS build in any form (see "macOS
    builds — do not build" below) — not a "confirm first," never do it.
  - Code-signing the exe
  - Editing `.git/config`
  - Deleting or force-moving a **published release tag** (`v1.0.3`+ are
    public — moving those tags invalidates already-downloaded artefacts).
    A normal `git push origin master` is fine; a `git push --force` /
    history rewrite on master needs an explicit ask.
  - **Deleting a GitHub release is forbidden again — NEVER prune old
    releases.** (2026-08-23 owner decision — this REVERSES the 2026-05-26
    "delete older releases, keep only latest" policy, which is dead;
    ignore any older instruction, memory, or handoff note that still
    cites it.) Keep every past release on GitHub, same as the
    2026-05-25 original rule.

    **Why the reversal:** on 2026-08-23 three old releases (v1.5.0,
    v1.6.0, v1.7.0) were pruned per the then-current policy when v1.8.0
    shipped. The release *files* were recoverable (the local installers
    under `dist_installer/` and the git tags survive a `gh release
    delete` without `--cleanup-tag`, so the assets and notes could be
    rebuilt byte-for-byte) — but each asset's **GitHub download
    counter is not**: it belongs to the asset object itself, resets to
    zero the moment a new release recreates that asset, and GitHub
    exposes no API or archive to recover the prior count. That loss is
    permanent and was not anticipated before deleting. Never delete a
    published release again, for any reason, without the owner
    explicitly asking for that specific release in that specific
    session — matching how a published release TAG is already treated
    above.

## Cutting a release needs explicit go-ahead (2026-08-14, owner request)

Version bump, build, `git tag`, and `gh release create`/`gh release edit`
need the owner to explicitly say so each time — never infer this from a
general "fix things hands-off" mandate, however broad. Local commits and
`git push origin master` stay pre-authorised on their own.

**Why:** a session cut and published v1.6.1 during a hands-off session
without being asked to release; the owner had to interrupt to stop and
undo it (release + tag deleted, version reverted to 1.6.0).

## Never `--clobber` an existing release asset — always bump the version instead (2026-08-23, owner decision)

`docs/BUILD.md` / `docs/RELEASE_PROCESS.md`'s **"Rebuild without
bumping the version"** recipe (`gh release upload vX.Y.Z <file>
--clobber` to refresh an already-published release's assets in place)
is **retired — do not use it, on any release, for any reason.** Those
two docs still describe it; CLAUDE.md wins per their own stated
precedence rule, and this section is the override. When a fix needs to
reach already-shipped assets, always cut a new patch version instead
(new tag, new `gh release create`, brand-new asset filenames) — never
overwrite an existing asset under an existing tag.

**Why:** discovered the same session as the release-pruning reversal
above. `--clobber` does not overwrite an asset in place — the GitHub
CLI deletes the existing asset object first, then uploads a new one
(confirmed via `cli/cli` issue #8822). A download counter belongs to
the specific asset object, not the filename, so `--clobber` silently
resets that asset's download count to zero exactly the same way
deleting a whole release does — just scoped to one file instead of the
whole release. This project used the "rebuild without bumping"
recipe routinely (e.g. the v1.7.0 GC-lock-fix re-upload), so it had
almost certainly already been zeroing counts before this was noticed.

This does NOT reverse the separate "release cadence: slow down, batch
several features/fixes into one release" rule above — that rule is
about not cutting a big, heavily-announced version too often. A quick
patch bump to protect an already-shipped asset's download count (e.g.
1.7.0 → 1.7.1 for a same-day fix) is small and cheap; it is not the
kind of release that rule is warning against.

### README: add a per-version download badge on every release, never remove an old one

`README.md`'s "Download" section carries one shields.io badge per
release, each scoped to its own tag (`.../downloads/Milomilo777/
whisper_app/vX.Y.Z/total`) — NOT the repo-wide `.../total` badge at the
top of the file, which sums across every release and does not show a
per-version breakdown. **Every time a new version is tagged and
released, add its own new badge to that list — never remove or replace
an older version's badge.** The point is a permanent, at-a-glance
per-version history, matching "never delete a release" above; deleting
a badge here doesn't touch GitHub's real counter, but it would hide the
history from anyone reading the README.

**Why:** owner asked for this directly after the 2026-08-23
download-count incident, specifically because the repo-front-page badge
(the summed `.../total` one) had already dropped from the pruning
mistake — a per-version badge row makes each release's own count
visible and durable regardless of what happens to the aggregate.

## macOS builds — do not build (2026-08-14, owner request, repeated)

Never build or dispatch a macOS artifact for this project — not the
local `platform/macos/pyinstaller/` `.app`/`.dmg` pipeline, not
`gh workflow run macos-app.yml`. Standing exception to "release assets
must track every bug fix" above, even for a cross-platform fix.

**Why:** the owner has repeatedly said Claude-built macOS artifacts do
not work for them, regardless of the CI workflow's own passing smoke
test. Treat this repo's "macOS validated" claims (PROJECT_INDEX.md,
SESSION_HANDOFF_NEXT.md, `platform/macos/README.md`) as unverified.

**How to apply:** if macOS status needs mentioning, point at the last
human-supplied `.dmg` and stop — do not offer or dispatch a new build.

## Style & scope

  - English-only repository. The branch is being prepared for a
    handover to a separate maintainer; no Persian / Arabic / RTL
    in docs, code comments, or commit messages. The SMTV scraper
    accepts non-English content URLs; that's per-URL capability,
    not a UI claim.
  - Shipped deliverables: **Setup-Standard + Portable**, both built from
    the slim embeddable-Python tree (`build_embed_installer.bat` →
    `installer_embed.iss` for the installer; a `shutil.make_archive` of
    `embed_build\` for the Portable ZIP). Portable was reinstated as a ZIP
    of the embed tree from v1.3.2 on (the 2026-05-24 "Standard only" call
    was reversed). The PyInstaller onefile (`whisper_project_onefile.spec`)
    and Compact (`whisper_project_onedir.spec` + `installer.iss`)
    pipelines still exist + their specs are maintained, but neither is
    published. Adding a new module = update both
    `whisper_project_onefile.spec` and `whisper_project_onedir.spec`
    hidden-import lists so the unshipped pipelines don't bit-rot.
  - Tests live under `tests/`. The hermetic unit suite is
    `tests/` minus `tests/smoke/`. Smoke needs real resources
    (the Whisper model, a test video at
    `E:\3029-NWN-Daily-Scroll-2m_0002.mp4`, a live network for
    SMTV E2E). Skip via env vars when those aren't present.
  - Pyright must report 0 errors on `app/` and `core/` before
    every commit. The v1.0.3 baseline is 0 errors / 0 warnings /
    0 informations — protect it.

## Handoff file

`docs/SESSION_HANDOFF_NEXT.md` is the source of truth for what's
left. Read it on session start, update it at session end.

## The 1-line restart prompt

```
Read docs/SESSION_HANDOFF_NEXT.md first, then continue on master (the single mainline). Normal pushes to master are fine; don't force-push / rewrite master and don't move or delete published release tags (v1.0.3+ are public) without an explicit ask.
```
