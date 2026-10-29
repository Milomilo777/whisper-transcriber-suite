-- D1 schema for the wts-stats Worker. Apply with:
--   npx wrangler d1 execute wts-stats --remote --file=schema.sql
-- Idempotent: safe to run again. No secondary indexes on purpose: on the D1 free plan every index
-- write counts against the 100k rows-written/day quota; reads and deletes go by id instead. No
-- AUTOINCREMENT either (it writes sqlite_sequence on every insert); ids still only grow, because the
-- purge deletes the oldest rows and never the newest.

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY,
  server_time TEXT NOT NULL,
  country_code TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  language TEXT NOT NULL DEFAULT '',
  audio_duration REAL NOT NULL DEFAULT 0,
  transcription_time REAL NOT NULL DEFAULT 0,
  word_count INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT '',
  program_version TEXT NOT NULL DEFAULT '',
  platform_system TEXT NOT NULL DEFAULT '',
  platform_release TEXT NOT NULL DEFAULT '',
  platform_version TEXT NOT NULL DEFAULT '',
  platform_machine TEXT NOT NULL DEFAULT '',
  platform_processor TEXT NOT NULL DEFAULT '',
  cpu_count INTEGER NOT NULL DEFAULT 0,
  mem_total INTEGER NOT NULL DEFAULT 0,
  install_id TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY,
  server_time TEXT NOT NULL,
  program_version TEXT NOT NULL DEFAULT '',
  os TEXT NOT NULL DEFAULT '',
  machine TEXT NOT NULL DEFAULT '',
  install_id TEXT NOT NULL DEFAULT '',
  text TEXT NOT NULL,
  log TEXT NOT NULL DEFAULT ''
);
