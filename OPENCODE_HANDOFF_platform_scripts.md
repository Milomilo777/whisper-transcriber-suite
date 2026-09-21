# OpenCode handoff — non-Windows packaging/install script review

Branch: `opencode/platform-scripts-review` (local only; not pushed, master untouched).

Scope (all five files read in full, four changed):

- `platform/linux/install.sh`
- `platform/linux/update.sh`
- `platform/linux/uninstall.sh`
- `platform/macos/install.command`
- `platform/macos/unblock.command` (reviewed, no change needed)

Method: static review only. No installer was executed end-to-end; no macOS
artifact was built or dispatched; no Linux install was run. Every script
passes `bash -n`. One changed function was additionally exercised in an
isolated harness (details in fix 1). Other fixes are argued from POSIX/bash
semantics and the scripts' own control flow, not from a full run.

## Real bugs found and fixed

### 1. `platform/macos/install.command` — `set -e` aborts the installer when ffplay is absent, or when `brew install ffmpeg` fails

`link_ffmpeg_into_bin()` ended each loop iteration with:

    [ -n "$p" ] && ln -sf "$p" "$REPO_ROOT/bin/$f"

as the last command of a `for f in ffmpeg ffprobe ffplay` loop. When the
last test is false — no `ffplay` on PATH, which the script's own comment
anticipates ("missing from some minimal static builds") — the `&&` list
returns 1, the loop returns 1, the function returns 1, and `set -e` kills
the script at the call site (lines 95/100) *before* the `.app` bundle and
CLI launcher are written. Same abort after a failed `brew install ffmpeg`,
which silently defeats the explicit `brew install ffmpeg || warn` intent,
and when only one of the three tools is missing. A first-run user gets a
Terminal window that closes with no launchers installed.

Fix: `if [ -n "$p" ]; then ln -sf ...; fi`. A `for`/`if` whose condition is
false returns 0, so the function no longer signals failure; a real `ln`
failure still aborts under `set -e`.

Confidence: verified by execution of the changed function in isolation —
extracted it from the real file with `sed`, ran under `set -euo pipefail`
with stub `ffmpeg`/`ffprobe` on PATH and no `ffplay`. Fixed version returns
0 and the shell continues; the old version exits 1 before the next line.
The installer itself was not run.

### 2. `platform/macos/install.command` — temp directory leaks on every static-ffmpeg run

`TMP="$(mktemp -d)"` (line 108) is never removed; three zip downloads plus
extracted binaries (~100 MB) stay in the per-user temp dir. The Linux
installer cleans up its equivalent; this one forgot.

Fix: `rm -rf "$TMP"` at the end of the same branch, after the temp dir's
last use. Every download/unzip/copy failure inside the branch is already
guarded with `|| ok=0` / `|| ffplay_ok=0`, so all handled failures reach
the cleanup; only an interrupt can still leave the dir (same as Linux).

### 3. `platform/linux/update.sh` — `[ -d .git ]` silently skips the source update in a git worktree

In a linked worktree (and in a submodule) `.git` is a file, not a
directory, so the test is false and the updater silently does no `git pull`
at all — it only refreshes dependencies. Worktrees are in active use on
this project.

Fix: `[ -e .git ]`. Directory checkouts behave identically; a worktree now
pulls its own branch (`--ff-only`, still failure-safe).

### 4. `platform/linux/update.sh` — dangling venv aborts with a cryptic error instead of the install-first message

`[ -d "$VENV" ]` accepts a venv whose `bin/python` symlink is broken, e.g.
after the distro upgrades Python in place. `activate` still sources fine,
then `python -m pip ...` runs the dangling symlink, and `set -e` exits with
a bare command-not-found instead of the intended "no virtualenv found —
run install.sh first" guidance.

Fix: test `[ -x "$VENV/bin/python" ]`. A healthy stdlib venv always has an
executable `bin/python`; a broken one now takes the existing friendly error
path.

### 5. `platform/linux/uninstall.sh` — `rm -rf` target not sanity-checked

`rm -rf "$REPO_ROOT/.venv"` ran unconditionally, unlike `install.sh`, which
refuses to proceed unless `$REPO_ROOT/gui.py` exists. If the script is ever
copied, symlinked, or reached from an unexpected tree whose two-levels-up
contains a `.venv`, it deletes it blind.

Fix: same `gui.py` guard as `install.sh`, before any removal. Normal use in
an intact checkout is unaffected.

### 6. `platform/linux/install.sh` — unquoted `Exec=` path in the generated .desktop entry

`Exec=$BIN_LOCAL/whisper-transcriber-suite` breaks launching if `$HOME`
contains a space: the desktop environment splits the path at the space. The
Desktop Entry spec permits double-quoted arguments.

Fix: `Exec="$BIN_LOCAL/whisper-transcriber-suite"`. `Icon=` was deliberately
left unquoted — per spec its value is a literal path, not a command line, so
quotes would become part of the path.

## Considered and deliberately not changed

- `find ... | head -n1` in `platform/linux/install.sh` under `pipefail`:
  SIGPIPE could theoretically abort it, but the johnvansickle tarball always
  contains exactly one `ffmpeg-*-static` directory, so `head` causes no
  second write. A `-print -quit` rewrite would add a BusyBox-find
  compatibility question for an unreachable failure; dropped.
- `install.command` rebuilding `.venv` from scratch before pip succeeds:
  documented, intentional (must not reuse a Tk-8.5-linked venv). A
  staging-dir swap is unsafe because pip console-script shebangs (yt-dlp)
  embed the venv path and would break after a rename.
- Hardcoded `CFBundleVersion 1.3.6` in `install.command`'s Info.plist:
  PROJECT_INDEX documents this as intentionally independent of
  `core.__version__`; cosmetic only.
- `BASH_SOURCE[0]:-$0` self-location: confirmed zsh-safe (BASH_SOURCE unset
  falls back to `$0`), so executing a `.command` under any shell is fine.
- `install.sh` header comment still calls the repo private (it is public
  now): stale prose, not script logic; left for the docs pass.
- `unblock.command`: no logic bugs found; `set -euo pipefail` interactions
  are all guarded.

## Verification summary

- `bash -n` on all five scripts: clean.
- Fix 1 proven by the isolated harness above (old code aborts, new returns 0).
- Fixes 2-6: static reasoning; no runnable end-to-end test is possible on
  this Windows dev machine and running one was explicitly out of scope.
- No `.py` files touched, so pyright/pytest were not run.

## Second-pass independent re-check (muse-spark-1.3-contributor) — 2026-09-20

### What was verified from the first pass, and how

Re-read all five scripts in full plus the real `git diff master..HEAD` (the handoff
prose matches the diff exactly). Independently proved the three most significant
claimed fixes by execution, all on this machine:

- Fix 1 (`set -e` abort in `link_ffmpeg_into_bin`): extracted old vs new loop into
  harness scripts, ran under `set -euo pipefail` with stub `ffmpeg`/`ffprobe` and no
  `ffplay`. Old version exits 1 before the next line (installer dead, no launchers);
  fixed version prints through and exits 0. Claim holds.
- Fix 3 (worktree `.git`): `[ -d .git ]` skips the pull when `.git` is a file,
  `[ -e .git ]` pulls. Claim holds.
- Fix 4 (dangling venv): `[ -d "$VENV" ]` accepts a venv whose `bin/python` is
  broken, `[ -x "$VENV/bin/python" ]` rejects it while still accepting a healthy
  venv. Claim holds (dangling-symlink creation itself is restricted on this Windows
  checkout, so the Linux `-x`-follows-symlink semantics were verified by
  reconstructed present/broken cases rather than a literal dangling link).
- Fixes 2 (mac `rm -rf "$TMP"`), 5 (uninstall `gui.py` guard), 6 (quoted `Exec=`):
  confirmed correct by reading the diff; fix 6's `Icon=`-left-unquoted reasoning is
  right per the Desktop Entry spec. No execution proof possible here, same as the
  first pass. Nothing wrong found in any of the six fixes.

### New bugs found and fixed (with evidence)

1. `platform/linux/install.sh` — static-ffmpeg branch silently installs nothing
   when the upstream tarball layout changes. If `curl`+`tar` succeed but no
   `ffmpeg-*-static` directory exists, the inner `[ -n "$D" ]` is false, the outer
   branch is true, and the script prints nothing at all — then installs launchers
   and reports success with no ffmpeg and no warning. Proven with a harness running
   the branch's exact shape with stubbed `curl`/`tar` producing a renamed top-level
   dir: zero output, exit 0. Fix: `else warn "unexpected static ffmpeg archive
   layout — …"` mirroring the existing download-failure message. Post-fix harness
   prints the warning.
2. `platform/linux/install.sh` + `platform/macos/install.command` — `$TMP` leaks
   on abort paths. Both scripts' explicit `rm -rf "$TMP"` is skipped when `set -e`
   aborts first (Linux: `cp`/`chmod` are unguarded, e.g. disk-full; macOS: any
   interrupt during the curl/unzip sequence), leaving a hundreds-of-MB temp dir.
   Fix: `trap 'rm -rf "$TMP"' EXIT` immediately after each `mktemp -d`, keeping the
   existing explicit removals (double removal is harmless). Proven with a harness
   that aborts after creating the temp dir: directory is gone afterwards.

### Considered and deliberately not changed

- Uninstaller leaving `$REPO_ROOT/bin/` static binaries behind: documented behavior
  ("leaves the repo checkout"), not a silent failure. Out of scope.
- `unblock.command` having no `gui.py` guard: worst case it strips quarantine flags
  from a wrong tree — read-only-ish, low risk, no data loss. Not worth the churn.
- First pass's "considered" list re-checked: agree on all six, no additions.

### Final verification

- `bash -n` on all five scripts: clean.
- pyright on `app/` + `core/`: 0 errors / 0 warnings / 0 informations.
- `pytest tests/ --ignore=tests/smoke`: 2185 passed, 1 skipped, 1 failed in
  `tests/core/test_search_dialog.py::test_open_selected_with_no_selection_is_a_noop`;
  that test passes in isolation and no `.py` file differs from `master` on this
  branch, so the failure is a pre-existing order-dependent flake unrelated to this
  diff (shell scripts only).
