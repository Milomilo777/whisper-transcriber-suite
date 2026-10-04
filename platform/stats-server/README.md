# Usage stats server

`transcription_stats.php` receives the desktop app's opt-in usage stats
(sent by `core/stats.py`, documented in `docs/CONFIG.md`) and stores one row
per transcription in an SQLite file next to the script,
`transcription_stats.db`.

## What it stores

| Column | Content |
|---|---|
| `server_time` | when the row was written (server clock, RFC 3339) |
| `country_code` | two-letter code the app reads from the operating system's region setting; empty unless it is exactly two upper-case letters |
| `country_name` | the same code, so a viewer that shows this older column keeps working (rows written by older versions hold a full country name) |
| `file_name` | file name only; any path part is dropped |
| `model`, `language`, `status`, `program_version` | as sent by the app |
| `audio_duration`, `transcription_time` | seconds |
| `word_count` | words in the transcript |
| `platform_system`, `platform_release`, `platform_version`, `platform_machine`, `platform_processor` | Python `platform` facts about the host |
| `cpu_count`, `mem_total` | CPU count, total RAM in bytes |

Every text field is length-capped (see `$text_limits` in the script) and
stripped of control characters; numbers are clamped to a sane range.

## What it does not store

The script never reads the connection's network address, does not look it
up anywhere and makes no outbound requests. The `client_ip`,
`ip_location_json` and `platform_node` columns remain only so an existing
database keeps its old rows; new rows write an empty string into them.

Versions of this script before 2026-10 stored the IP address, a lookup of
it and the computer name. A server still running such a version keeps
doing so until it is updated. Rows written by an older version are not
changed by the update; to clear their IP data, back up the `.db` file and
then run:

```sql
UPDATE transcription_stats SET client_ip = '', ip_location_json = '', platform_node = '';
```

**Web-server access logs** are a separate matter: most web servers log every
request's IP address. That is a setting of the host (log format, retention),
not of this script.

## Deploy

1. Requirements: PHP 7.0 or newer with the `pdo_sqlite` extension
   (`mbstring` is used when present).
2. Copy `transcription_stats.php` over the old copy at the URL the app's
   `stats_url` setting points to (default in `core/config.py`). An existing
   `transcription_stats.db` next to it is reused as is; the first request
   adds the new `country_code` column. Nothing is dropped or rewritten.
3. Make sure the `.db` file cannot be downloaded over the web. Apache: add
   to the folder's existing `.htaccess` (do not replace the file):

   ```apache
   <FilesMatch "\.db$">
       Require all denied
   </FilesMatch>
   ```

   Apache 2.2 has no `Require`; use `Order allow,deny` and `Deny from all`
   inside the same block instead. nginx: `location ~ \.db$ { deny all; }`
   in the server block.
4. Check it:
   - Open the URL in a browser: it prints the endpoint name, the SQLite
     version and the accepted fields.
   - Send a test row:
     `curl -d form_submitted=1 -d country=DE -d model=test <url>` prints `OK`.
   - The newest row has `country_code` = `DE` and empty `client_ip`.
     Delete the test row afterwards.

On a database or PHP error the script answers HTTP 500 with `ERROR` and
writes the message to the host's PHP error log; the app ignores the answer
either way.

There is no rate limit and no authentication: anyone can post rows. Use the
host's own limits if that becomes a problem.
