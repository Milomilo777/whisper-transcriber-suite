# Handoff — `opencode/server-hardening`

## First pass (DeepSeek V4.1 Flash, commit `50f66cc`, unreviewed)

Added, on top of `master`: HTTPS via stdlib-only self-signed P-256 cert
(`core/server/tls.py`, opt-in `--https` / `server_https_enabled`, default off);
outgoing completion webhooks (`JobManager(webhook_url=...)`, fire-and-forget
daemon thread, `post_webhook` reusing the inbound `is_safe_url` SSRF guard,
no-redirect opener, `--webhook` / `server_webhook_url`); an OpenAI-compatible
`/v1/models` + `/v1/audio/transcriptions` surface (multipart, `model` required,
`response_format` json/text/srt/verbose_json/vtt, Bearer-token auth, sync
wait on the single worker); GUI tab + CLI wiring; PyInstaller spec entries;
new tests `test_server_tls.py` / `test_server_webhooks.py` /
`test_server_openai.py` plus fake-server updates in `test_fixpack_bl_appui.py`.

## Second-pass independent re-check (muse-spark-1.3-contributor)

No handoff file existed, so context was derived from
`git log master..HEAD` / `git diff master..HEAD` directly.

### What was verified from the first pass, and how

- Webhook SSRF guard is load-bearing, not decorative:
  `test_post_webhook_refuses_loopback_target` (real loopback listener gets
  zero hits) and `test_post_webhook_refuses_metadata_ip` pass with the real
  guard, while `test_post_webhook_delivers_when_guard_allows` (guard mocked
  to `True`) delivers — i.e. flipping the guard flips the outcome.
- Redirects are not followed: `test_post_webhook_does_not_follow_redirects`
  proves the first endpoint is hit, the (loopback) redirect target is not,
  and the caller sees an error rather than a silent fetch.
- OpenAI surface: missing `model` → 400 with `param: "model"`, unknown
  `response_format` → 400 naming the supported formats, non-multipart and
  missing-file → 400, engine failure → 500 `server_error` envelope,
  no-token → 401 `invalid_api_key` / correct Bearer → 200 / wrong Bearer →
  401. All covered by `test_server_openai.py` and passing.
- TLS: cert generates under `tmp_path`, OpenSSL loads the pair, invalid pair
  regenerates, `build_server_ssl_context` enforces TLS ≥ 1.2, a real HTTPS
  round-trip serves `/api/health`, and a cert failure raises instead of
  serving plaintext or leaving a half-started server (`test_server_tls.py`,
  all passing).
- First-pass claims re-confirmed: `pyright app/ core/` → 0/0/0; full hermetic
  suite (`tests/`, minus `tests/smoke/`) → **2225 passed, 1 skipped**.

### What was wrong / missing in the first pass

One real gap, in the security-sensitive SSRF guard itself: `is_safe_url`
only recognised strict dotted-decimal literals via `ipaddress`. Legacy
`inet_aton`-style numerics — `http://2130706433/` (decimal),
`http://0x7f000001/`, `http://0x7f.0.0.1/`, `http://0177.0.0.1/`,
`http://127.1/` (all == 127.0.0.1) — fell through to the fail-open DNS path,
and on hosts whose `getaddrinfo` rejects those forms (this Windows box:
`getaddrinfo` fails for all of them) they were returned **allowed**
(reproduced pre-fix: all `True`). urllib on this box also fails to connect
to those forms, so direct webhook exploitability here is low — but the guard
is shared with the yt-dlp/ffmpeg URL-download path, whose stacks accept
`inet_aton` forms, so "allowed" from the guard is the wrong answer on its
face. Fixed for real (see below), not papered over.

### New bugs found and fixed (this pass)

- **SSRF guard bypass via legacy numeric IPv4** (`core/server/jobs.py`):
  added `_parse_legacy_ipv4` (decimal/0x-hex/octal parts, 1–4 parts with
  `inet_aton` range rules; non-numeric DNS names always return `None`) and
  hooked it into `is_safe_url`'s literal-IP branch. Post-fix all loopback
  numerics above → `False` even with `getaddrinfo` stubbed to fail, while
  numeric encodings of RFC-1918 addresses (`3232235521` = 192.168.0.1,
  `0xC0A80101`) still follow the dotted form's verdict (allowed — the
  documented LAN normal case). Regression tests:
  `test_is_safe_url_blocks_legacy_numeric_loopback`,
  `test_is_safe_url_numeric_private_matches_dotted_form`
  (in `tests/core/test_fixpack_D.py`, next to the other `is_safe_url` tests).

### Reviewed and deliberately left alone

- `_NoRedirectHandler.redirect_request → None`: test proves the redirect
  target is never fetched; returning `None` surfaces an error urllib
  callers already handle. No change.
- `_receive_upload` drains oversized declared bodies while
  `_reject_post_early` closes immediately: inconsistent-looking but the
  drain is a deliberate, commented Windows connection-reset trade-off on a
  pre-existing path. No change.
- `_wait_for_job` polls forever until terminal/`manager.stopped`: bounded in
  practice by the client's own HTTP timeout; adding socket-liveness checks
  would add complexity for no proven failure. Noted, not changed.
- Private RFC-1918 ranges allowed by the guard: documented, intentional
  (trusted-LAN media servers), covered by tests. Not changed.

### Final verification (this pass)

- `pyright app/ core/` → **0 errors / 0 warnings / 0 informations**.
- Hermetic suite `pytest tests/ --ignore=tests/smoke` → **2225 passed,
  1 skipped** (run with the `jobs.py` fix in place); the two new regression
  tests plus the four directly-related files re-run green afterwards.
