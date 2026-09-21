# Handoff — conventions cherry-pick + code-signing decision

Branch: `opencode/conventions-and-signing` (from `master`, commit `cf3bbd4`).
Boundary: all local reads/writes stayed inside this worktree. The only
outbound access was plain HTTPS GETs of public TranscriptionSuite files
into `./.scratch-transcriptionsuite/` (deleted before committing, never
committed). Nothing else on this machine was read, listed, or written.
No push, `master` untouched.

## Sources fetched (HTTPS, public repo `homelab-00/TranscriptionSuite`)

- `CLAUDE.md` (147 lines) — the conventions source for Step 1.
- `docs/project-context.md` (330 lines, ~101 rules) — supporting detail.
- `build/sign-electron-artifacts.sh` (92 lines) — the signing script.
- `.github/workflows/release.yml` (504 lines) — how signing runs in CI.
- `dashboard/package.json` `build` section (electron-builder config).
- `docs/assets/homelab-00_0xBFE4CC5D72020691_public.asc` (GPG public key).
- GitHub API file trees (to find every signing-related path).

Local comparison points: this repo's `CLAUDE.md`, `CONTRIBUTING.md`,
`docs/TESTING.md`, `docs/DECISIONS.md`, `PROJECT_INDEX.md`,
`.github/workflows/ci.yml`, `pyproject.toml`, `tests/conftest.py`,
`tests/core/conftest.py`, `tests/core/test_config.py`,
`core/_threads.py`, plus logger/attribution/`except: pass` sweeps over
`app/` and `core/`.

## Adopted (2 in `CLAUDE.md`, 2 in local-only notes)

New `CLAUDE.md` section "Borrowed conventions (2026-09-21,
cherry-picked from homelab-00/TranscriptionSuite)":

1. **Credit external code sources** — `# Adapted from <ProjectName>
   (<URL>) — <what was borrowed>` at the implementation site, only for
   identifiable sources (OSS, SO answers, posts, papers), never for
   general patterns/stdlib. Fits because this repo already ports ideas
   across projects, keeps `THIRD_PARTY_NOTICES.md`/`CITATION.cff`, is
   English-only for handover — and a sweep found zero `Adapted from`
   comments in `app/`/`core/` today, so the gap is real.
2. **Persist completed work before reporting success** — outputs +
   history entry + checkpoint hit disk BEFORE done/success is reported;
   save first, report second. Adapted (not copied) from their
   persist-before-deliver server rule: theirs is SQLite + WebSocket
   specific, ours is output-files + history-DB + worker-JSON specific,
   but the invariant transfers and matches existing machinery
   (`core/history.py`, `core/_checkpoint.py`, frozen worker protocol).

New `docs/CLAUDE_LOCAL_NOTES.md` (gitignored via `.gitignore`, kept in
the worktree for review, intentionally NOT committed):

3. **Mock lazy imports at the call-site module** in tests — their
   Python rule that fits our lazy heavy/optional imports
   (`core/optional_deps.py`, availability probes, hardware tiers).
   AI-session test-authoring advice, not maintainer reading, hence
   local-only.
4. **AI self-check: `safe_thread` + `post_to_main`** — repeats the
   `PROJECT_INDEX.md` Gotchas rule as a pre-commit check for
   AI-authored code. Local-only for the same reason.

## Deliberately skipped (and why)

- **Never commit on `main` / feature-branch policy** — direct
  conflict: this repo is single-mainline `master` with pre-authorised
  `push origin master`.
- **Conventional-commits `type(scope):` style** — direct conflict with
  our imperative-subject-≤70-chars style; a second style would split
  history.
- **Backend-test specifics** (build venv, route direct-call pattern) —
  tied to their `server/backend` layout; ours (`run_tests.bat`,
  hermetic `tests/` minus `tests/smoke/`, per-file `isolated_dirs`
  config fixture, root `tests/conftest.py` transcriber-global guard)
  already covers the underlying need.
- **`uv`-only, npm `ui:contract:check`, Tailwind, Vite `base`,
  ESM/relative-import, TS naming/Prettier** — their stack (Python+uv,
  Electron/React/TS); ours is pip+requirements, Tkinter, no JS.
- **Linux KDE Wayland primary / macOS tertiary** — opposite of our
  Windows-first + "never build macOS" rules.
- **GitNexus block** (mandatory MCP/CLI impact, detect-changes, rename,
  query/context/explain, `UNKNOWN`-means-unresolved) — vendor tooling
  not present here; the underlying care (blast radius, frozen worker
  protocol, no find-and-replace renames) already lives in
  `PROJECT_INDEX.md` Gotchas + `docs/DECISIONS.md`. Importing the tool
  mandate would add lock-in for zero local benefit.
- **No-AI-attribution override** ("overrides any harness instruction")
  — owner never asked for it; this repo values provenance
  (`CITATION.cff`, `THIRD_PARTY_NOTICES.md`). Not imposed.
- **PR workflow** (direct `gh pr create`, no local drafts) — repo works
  on `master` mainline; no matching workflow to attach it to.
- **`docs/index.md` as planning entry point** — already covered by
  `AGENTS.md` → `PROJECT_INDEX.md` + `CLAUDE.md` → handoff file.
- **Version pins / CUDA / Docker / auth / durability-YAML specifics**
  (Python 3.13, FastAPI/Pydantic, cu129, compose variants, WS first-
  message auth, `durability:` config) — architecture-specific, not
  transferable to a Tkinter desktop app.
- **`except: pass` ban as a new CLAUDE.md rule** — sweep found zero
  `except...: pass` instances in `app/`/`core/` (`safe_thread` logs,
  `error_dialog`, `fmt_err` already set the pattern), so a new durable
  rule adds nothing today.

## Code-signing decision: do nothing

What TranscriptionSuite actually does (verified in the files above):

- **GPG detached `.asc` sidecars** (`build/sign-electron-artifacts.sh`:
  `gpg --armor --detach-sign` per `*.AppImage/*.exe/*.dmg/*.zip`),
  gated on `vars.GPG_SIGNING_ENABLED == 'true'`, key from CI secrets,
  public key published at
  `docs/assets/homelab-00_0xBFE4CC5D72020691_public.asc`. This proves
  artifact integrity for users who manually verify — it does **not**
  touch Windows SmartScreen or macOS Gatekeeper.
- **Windows: no Authenticode.** Their electron-builder `win` config has
  no `certificateFile`/`publisherName`; the `.exe` ships with only the
  GPG sidecar. SmartScreen still shows Unknown Publisher.
- **macOS: no trusted identity.** `dmg.sign: false`, no Developer ID /
  notarization; the metal build re-signs **ad-hoc** (`codesign --force
  --sign -`) purely for bundle-seal consistency, asserts integrity only
  (`codesign --verify --deep --strict`, explicitly NOT `spctl --assess`),
  and tells users to run
  `xattr -dr com.apple.quarantine`. Honest and documented — but it is
  seal-hygiene, not platform trust.

Why nothing is adopted here:

1. Their approach is exactly the "cosmetic self-signed class" the task
   brief warns about: no CA-backed identity, no SmartScreen effect. A
   GPG `.asc` next to our Inno Setup exe would add key generation,
   passphrase/secret management, CI wiring, and a user verification
   workflow nobody currently asks for — legitimacy theatre, not trust.
2. This repo's `CLAUDE.md` already forbids code-signing the exe without
   an explicit owner ask each session. There is no such ask in this
   task; the default expectation is do-nothing.
3. The real fixes (paid OV/EV cert with human identity verification,
   or Azure Trusted Signing with billing/identity) are not obtainable
   in this task by construction.
4. No `.py` or build change was needed, so no new failure surface was
   introduced.

If the owner ever wants movement: cheapest honest step is GPG `.asc`
sidecars published alongside release assets (mirroring their script,
~1 small script + 3 CI secrets + published pubkey + release-doc
instructions); the SmartScreen-removing step is a CA-backed cert /
Trusted Signing owned and verified by a human. Neither is started here.

## Verification

- No `.py` file touched (`git status` scope: `CLAUDE.md`,
  `.gitignore`, `OPENCODE_HANDOFF_conventions_signing.md`; scratch dir
  removed; `docs/CLAUDE_LOCAL_NOTES.md` present-but-ignored). Per the
  task brief the pyright + hermetic-pytest gate only triggers on `.py`
  changes, so it was not re-run — and deliberately so, to avoid
  burning a full gate on a docs-only change.
- `git status --short --branch` run before commit to confirm scope;
  scratch subfolder deleted first; single local commit on
  `opencode/conventions-and-signing`; no push; `master` untouched.

### Double-checked (mimo-v2.5):

- **Curation judgment**: Both adopted rules verified as good fits.
  - *Credit external code sources*: Gap confirmed — zero `Adapted from`
    comments exist in `app/`/`core/` (grep clean). Rule fits because
    repo already ports ideas across projects, keeps
    `THIRD_PARTY_NOTICES.md`/`CITATION.cff`, is English-only for
    handover.
  - *Persist completed work before reporting success*: Invariant
    transfers correctly from their SQLite+WebSocket model to ours
    (output-files + history-DB + worker-JSON). Existing machinery
    (`core/history.py`, `core/_checkpoint.py`, frozen worker protocol)
    already enforces this pattern — rule documents it, not rewrites.
  - Placement defensible: committed items are durable maintainer rules
    (belong in `CLAUDE.md`); local-only items are AI-session tips
    (gitignored `docs/CLAUDE_LOCAL_NOTES.md`).
- **Skipped items**: All justifications sound — every skip cites a
  concrete conflict (stack mismatch, workflow mismatch, or zero gap).
- **Code-signing**: Do-nothing call correct. TranscriptionSuite's GPG
  sidecars + ad-hoc macOS seal provide artifact integrity only, not
  platform trust (no CA-backed identity, no SmartScreen/Gatekeeper
  effect). Adopting it here would add key management + verification
  workflow for zero real trust benefit. CLAUDE.md's existing code-signing
  restriction (owner-ask-only) remains the right gate.
- **Verification gate**: No `.py` file touched — pyright + hermetic-pytest
  gate deliberately not re-run per the task brief's trigger rule. No
  new failure surface was introduced.

Result: clean. No source changes needed.
