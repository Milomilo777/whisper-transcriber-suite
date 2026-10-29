# Usage stats Worker

A Cloudflare Worker with a D1 database that receives the desktop app's usage statistics and problem
reports at `https://stats.whisper-transcriber-suite.com`. It is the default `stats_url` from the
release after 2.2.0 on. Older app versions keep posting to the PHP script in
[`platform/stats-server/`](../stats-server/README.md); the maintainer's collector reads both.
Decision record: `docs/DECISIONS.md`, entry 0021.

## Endpoints

| Method and path | Who | What |
|---|---|---|
| `POST /v1/runs` | the app | One usage row. The same `application/x-www-form-urlencoded` fields as the PHP script (`form_submitted=1`, `country`, `model`, `language`, `audio_duration`, `transcription_time`, `word_count`, `status`, `program_version`, `platform_*`, `cpu_count`, `mem_total`, `install_id`), the same length caps and number bounds. Body at most 8 KB. Answers `OK`. |
| `POST /v1/report` | the app | One problem report as JSON: `text` (at most 2,000 characters, line breaks kept), optional `log` (at most 20,000 characters), `program_version`, `os`, `machine`, `install_id`. Body at most 64 KB. Answers `{"ok": true, "id": n}`. |
| `GET /v1/export` | maintainer | Rows after `since_id` (`kind=runs` or `reports`, `limit` 1-1000, `upto_id`), HTTP Basic. Same reply shape as the PHP `export.php`: `rows`, `next_since_id`, `upto_id`, `count`, `has_more`. |
| `GET /view` | maintainer | A small HTML overview (recent days, latest reports, latest runs), HTTP Basic. `no-store`, strict CSP, all text escaped. |
| `GET /` | anyone | One line saying what this is. |

Never stored: the request's IP address or location, file names, paths, URLs or transcript text.
A missing or weak secret (user under 3 or password under 16 characters) keeps `/view` and
`/v1/export` closed.

## Free-plan limits

Workers Free allows 100,000 requests a day (reset 00:00 UTC; over it the custom domain answers
error 1027 and the app's best-effort POST is dropped). D1 Free allows 100,000 rows written and
5 million rows read a day. So the schema has no secondary index and no `AUTOINCREMENT` (each would
add a write per row), and every read goes by id: the view reads at most the newest 50,000 runs, and
the daily cron (03:17 UTC) keeps the newest 2,000,000 runs and 50,000 reports. The website's
Pages Functions share the same daily request quota.

## Deploy

Needs Node.js 22.5 or newer (the tests use `node:sqlite`).

```
cd platform/stats-worker
npm ci
npm test
npx wrangler login
npx wrangler d1 execute wts-stats --remote --file=schema.sql   # first time; safe to repeat
npx wrangler deploy
npx wrangler secret put STATS_USER
npx wrangler secret put STATS_PASSWORD
```

`wrangler.toml` holds the D1 database id and the custom domain; secrets are never in the repo.
Smoke check after a deploy: `GET /` answers 200, `GET /view` without the password answers 401.

## Tests

`npm test` runs `test/worker.test.mjs` against the real `schema.sql` in an in-memory SQLite
(`test/fake-d1.mjs` stands in for D1): payload parsing and caps, the password checks, HTML
escaping, export paging and the purge.
