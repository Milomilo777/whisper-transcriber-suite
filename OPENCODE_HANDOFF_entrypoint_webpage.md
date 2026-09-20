# Handoff — `opencode/entrypoint-webpage-review`

Scope (from `git diff <merge-base>..HEAD`, i.e. `master...HEAD`): `gui.py`
(`serve --port` handling), `core/server/static/index.html` (LAN page
sinks), plus two new test files `tests/core/test_gui_serve_args.py` and
`tests/core/test_web_page_escaping.py`.

> NOTE on `git diff master..HEAD`: it also shows a large deletion in
> `docs/SESSION_HANDOFF_NEXT.md`. That is NOT a branch change — `master`
> advanced after this branch forked (8+ doc commits since merge-base).
> `git diff master...HEAD` (three-dot, true branch diff) is the 4-file
> set above. Left the doc file untouched.

## First pass (DeepSeek V4.1 Flash, commit 4fa0138) — what it did

1. `gui.py`: new `_port_number()` argparse type for `serve --port`,
   rejects out-of-range/non-integer up front (was `type=int`).
2. `index.html` `start()` catch: `e.message` now wrapped in
   `escapeHtml()` before `setSubmitStatus()` → `innerHTML`.
3. `index.html` `renderSubmit()`: `(j.progress || 0)` → 
   `(Number(j.progress) || 0)` in the `style="width:..."` sink.

## Second-pass independent re-check (muse-spark-1.3-contributor, 2026-09-20)

### Verified from the first pass (prove-it discipline, all confirmed REAL)

- **Port crash**: `socket.bind(('127.0.0.1', 70000))` raises
  `OverflowError`, and `run_server` (`core/server/__init__.py:355`)
  catches only `OSError` — crash path confirmed live. Old `type=int`
  parses `70000` fine, so pre-fix CLI died with traceback. New
  `_port_number('70000')` raises `ArgumentTypeError`. ✔
- **`e.message` fix**: temporarily reverted line 405 to raw `e.message`
  → `test_server_error_messages_are_escaped` FAILS; restored → passes. ✔
- **Progress fix**: temporarily reverted line 431 to raw `j.progress`
  → `test_progress_widths_go_through_number` FAILS; restored → passes. ✔
  (`Number()` output can never contain quotes, so no style-attribute
  breakout; `NaN || 0` → `0`. The other two bars already had it —
  test pins all 3.)
- Worktree confirmed clean after the revert/restore cycle.

### Wrong with the first pass (prose, not code)

Commit message claims the two fixed sinks were "setSubmitStatus's
fetch-failure e.message, and the matching resultStatus.innerHTML catch
handler". The `loadResult()` catch (`resultStatus.innerHTML ...
escapeHtml(e.message)`, line 550) was **already escaped at merge-base**
(by the 2026-07-18 fixpack) — it was not fixed by this branch. The real
second fix was the `renderSubmit` progress-bar `Number()` coercion, a
*style* sink, not an `innerHTML` sink. Fixes themselves are correct;
the description mislabels one of them. Noted here so nobody goes
looking for a `resultStatus` change in this diff.

### New bug found and fixed (missed by first pass, same class + function)

**Config-file `server_port` bypassed `_port_number` entirely.**
`_cli_serve` line 169 did `int(cfg.get("server_port", 8765))` with no
validation, so a hand-edited `config.json` with `70000`/`-1` flowed
verbatim into `run_server` → same uncaught `OverflowError` traceback.
Non-numeric values (`"abc"`, `null`) died in `int()` with
`ValueError`/`TypeError` tracebacks. Proven live: patched
`load_config` → `{'server_port': 70000, ...}` + `serve` (no `--port`)
forwarded `70000` straight to `run_server` (captured via monkeypatch),
and real `run_server(port=70000, load_model=False)` raises
`OverflowError` that escapes its `except OSError`.

**Fix** (`gui.py`, `_cli_serve`): explicit `--port` still uses the
already-validated `args.port`; the config fallback is now coerced in
`try/except (TypeError, ValueError)` and range-checked `0-65535`,
printing `[cli] invalid server_port in config: ...` to stderr and
returning exit `1` (same code as `run_server`'s own bind failure)
without ever reaching the socket. **Tests**: 5 new parametrized cases
in `test_cli_serve_rejects_invalid_config_port` (`70000/-1/65536/
"not-a-port"/None`) asserting rc `1`, `run_server` never called, and
the key name on stderr.

### Adversarial review — checked and deliberately NOT changed

- `j.status` raw in `renderSubmit`/`renderResult` innerHTML: server-side
  fixed enum (`STATUS_*` constants only, `jobs.py`), never user input.
  Not attacker-reachable. The `statusTxt` variants the tests pin only
  append a boolean-derived `" (paused)"`. No change.
- `j.job_id` raw in `data-id`/`data-open` attributes: `uuid4().hex`
  (`[0-9a-f]{32}`), quote-free by construction. No change.
- `--max-upload-mb` / config negative/zero: `httpd.py:517` clamps with
  `min(max(1, ...), ABS_MAX)`. Already safe. No change.
- `tokenQuery`/`downloadLink`: token and `fmt` go through
  `encodeURIComponent`, display name through `escapeHtml`. Clean.
- `find_available_port` (GUI auto-port path): already range-guards
  `1 <= preferred <= 65535` before probing, falls back to ephemeral.
  Safe against range (garbage *types* would still raise in `int()`,
  but that path belongs to the GUI toggle, outside this branch's
  CLI+page scope — flagged, not fixed here).
- `_port_number` edge inputs: `" 80 "`/`"+80"` → harmless valid ports;
  `"8_0"` → `int()` → `80`, valid; 5000-digit strings → `ValueError`
  → clean argparse error. No crash vector.

## Final verification (this pass, on final tree)

- `pyright app core`: **0 errors, 0 warnings, 0 informations**.
- `pytest tests/ --ignore=tests/smoke`: **exit 0** — 2203 collected,
  0 failures, 1 skip (`test_proc.py:80`, pre-existing POSIX-only path
  skipped on Windows).
- `git status`: only `gui.py`, `tests/core/test_gui_serve_args.py`,
  and this handoff file modified/added vs `4fa0138`; `index.html` and
  `test_web_page_escaping.py` restored byte-identical after revert
  proofs (verified via `git status` clean mid-pass).

Outcome: first pass was genuinely good (all 3 fixes real and proven);
one same-class vector missed, now fixed with tests. No further known
issues in this scope.

## Process note (2026-09-20 ~19:48–19:50): working tree was externally reverted mid-pass

After the fix was implemented and verified (16 focused tests green,
end-to-end proof done), `gui.py` + `test_gui_serve_args.py` were found
reverted to `4fa0138` content (file mtimes 19:48:38 / 19:50:15, no
stash, no reflog entry — i.e. a working-tree overwrite, not a git
operation of this session). A second `opencode` process (PID 1884,
started 19:48:44) is live on this machine alongside this session's own
(PID 1595) — likely source, left alone per policy. Untracked handoff
draft survived. Both edits were re-applied verbatim and the full gate
re-run below is on the re-applied tree, committed immediately after.
