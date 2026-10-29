// Whisper Transcriber Suite: usage statistics and problem reports (Cloudflare Worker + D1).
//
//   POST /v1/runs     one usage row; the same form fields as platform/stats-server/transcription_stats.php,
//                     so the desktop app only changes its stats_url. Reply "OK".
//   POST /v1/report   one problem report (JSON). Reply {"ok": true, "id": n}.
//   GET  /v1/export   rows after since_id for the maintainer's collector (HTTP Basic). Same reply shape
//                     as the PHP export: {source_id, rows, next_since_id, upto_id, count, has_more}.
//   GET  /view        a small HTML overview for the maintainer (HTTP Basic).
//   GET  /            one line saying what this is.
//
// Never stored: the network address of the request, its location, file names, paths or transcript
// text. Secrets (Worker settings, never in this file): STATS_USER and STATS_PASSWORD.

export const SOURCE_ID = 'cf-worker-wts-stats-v1';

// Longest value kept per text field, in characters (the PHP endpoint's limits).
export const TEXT_LIMITS = {
  model: 128,
  language: 32,
  status: 32,
  program_version: 32,
  platform_system: 32,
  platform_release: 64,
  platform_version: 256,
  platform_machine: 32,
  platform_processor: 128,
  install_id: 36,
};
// Upper bounds: ~115 days of audio, 1e9 words, 4096 CPUs, 1 PB RAM.
const NUMBER_LIMITS = { audio_duration: 1e7, transcription_time: 1e7 };
const INT_LIMITS = { word_count: 1e9, cpu_count: 4096, mem_total: 1e15 };

// Room for every field at its cap even in 4-byte characters, percent-encoded (the PHP script has no body cap).
export const MAX_RUN_BODY = 16 * 1024;
export const MAX_REPORT_BODY = 64 * 1024;
export const REPORT_TEXT_CHARS = 2000;
export const REPORT_LOG_CHARS = 8000;
// The collector keeps everything locally; D1 keeps a recent window only. A D1 Free database holds at most
// 500 MB: a run row is ~250 bytes (at most ~3 KB with every field at its cap in 4-byte characters) and a
// report at most ~40 KB, so these counts stay under it even then. The purge runs hourly, so a flood adds at
// most an hour of rows (the 100k/day write quota) on top.
export const KEEP_RUNS = 100000;
export const KEEP_REPORTS = 2000;
// The view page reads at most this many recent runs (D1 Free: 5 million rows read a day).
export const VIEW_WINDOW = 5000;
// A page of report exports holds at most this many rows (each up to ~40 KB; the Worker has 128 MB).
export const REPORT_EXPORT_LIMIT = 100;

const RUN_COLUMNS = [
  'id', 'server_time', 'country_code', 'model', 'language', 'audio_duration', 'transcription_time',
  'word_count', 'status', 'program_version', 'platform_system', 'platform_release', 'platform_version',
  'platform_machine', 'platform_processor', 'cpu_count', 'mem_total', 'install_id',
];
const REPORT_COLUMNS = ['id', 'server_time', 'program_version', 'os', 'machine', 'install_id', 'text', 'log'];

const CONTROL = /[\u0000-\u001f\u007f]/g;
const CONTROL_KEEP_NEWLINES = /[\u0000-\u0008\u000b-\u001f\u007f]/g;

/** value without control characters, cut to max characters (code points, like mb_substr). */
export function cleanText(value, max, keepNewlines = false) {
  if (typeof value !== 'string') return '';
  const cleaned = value.replace(keepNewlines ? CONTROL_KEEP_NEWLINES : CONTROL, '');
  return Array.from(cleaned).slice(0, max).join('');
}

/** A finite number in [0, max]; 0 otherwise (PHP is_numeric accepts surrounding spaces and exponents). */
export function cleanNumber(value, max) {
  // ASCII white space only, like PHP's is_numeric (JavaScript's \s would also accept U+00A0 and more).
  if (typeof value !== 'string' || !/^[ \t\n\r\v\f]*[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?[ \t\n\r\v\f]*$/.test(value)) return 0;
  const n = Number(value.trim());
  if (!Number.isFinite(n) || n < 0) return 0;
  return Math.min(n, max);
}

export function cleanCountry(value) {
  return typeof value === 'string' && /^[A-Z]{2}$/.test(value) ? value : '';
}

/** A repeated form field's LAST value, as PHP's $_POST keeps it; null when absent. */
function lastValue(form, name) {
  const all = form.getAll(name);
  return all.length ? all[all.length - 1] : null;
}

/** The row to store for one POST /v1/runs form, or null when it is not a stats form. */
export function runFromForm(form, now) {
  if (!form.has('form_submitted')) return null;
  const row = { server_time: now, country_code: cleanCountry(lastValue(form, 'country')) };
  for (const [field, max] of Object.entries(TEXT_LIMITS)) row[field] = cleanText(lastValue(form, field), max);
  for (const [field, max] of Object.entries(NUMBER_LIMITS)) row[field] = cleanNumber(lastValue(form, field), max);
  for (const [field, max] of Object.entries(INT_LIMITS)) {
    row[field] = Math.floor(cleanNumber(lastValue(form, field), max));
  }
  return row;
}

/** The row to store for one POST /v1/report body (parsed JSON), or an error message. */
export function reportFromJson(data, now) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return { error: 'expected a JSON object' };
  const text = cleanText(data.text, REPORT_TEXT_CHARS, true).trim();
  if (!text) return { error: 'text is empty' };
  return {
    row: {
      server_time: now,
      program_version: cleanText(data.program_version, TEXT_LIMITS.program_version),
      os: cleanText(data.os, 64),
      machine: cleanText(data.machine, 32),
      install_id: cleanText(data.install_id, TEXT_LIMITS.install_id),
      text,
      log: cleanText(data.log, REPORT_LOG_CHARS, true),
    },
  };
}

// --- storage (D1) ---------------------------------------------------------------------------------

async function insert(db, table, row) {
  const cols = Object.keys(row);
  const sql = `INSERT INTO ${table} (${cols.join(', ')}) VALUES (${cols.map(() => '?').join(', ')})`;
  const result = await db.prepare(sql).bind(...cols.map((c) => row[c])).run();
  return result.meta.last_row_id;
}

async function exportRows(db, kind, since, limit, upto) {
  const table = kind === 'reports' ? 'reports' : 'runs';
  const cols = kind === 'reports' ? REPORT_COLUMNS : RUN_COLUMNS;
  if (upto === null) {
    const top = await db.prepare(`SELECT COALESCE(MAX(id), 0) AS m FROM ${table}`).first();
    upto = top ? Number(top.m) : 0;
  }
  const { results } = await db
    .prepare(`SELECT ${cols.join(', ')} FROM ${table} WHERE id > ? AND id <= ? ORDER BY id ASC LIMIT ?`)
    .bind(since, upto, limit)
    .all();
  const n = results.length;
  const next = n ? results[n - 1].id : since;
  return {
    source_id: SOURCE_ID, kind: table, rows: results, next_since_id: next, upto_id: upto, count: n,
    has_more: n === limit && next < upto,
  };
}

/** Keep the newest KEEP_* rows. By id, not by time: there is no time index (see schema.sql), and an
 * id range is cheap to read. The newest row is never deleted, so ids keep growing. */
export async function purgeOld(db) {
  await db.batch([
    db.prepare('DELETE FROM runs WHERE id <= (SELECT COALESCE(MAX(id), 0) FROM runs) - ?').bind(KEEP_RUNS),
    db.prepare('DELETE FROM reports WHERE id <= (SELECT COALESCE(MAX(id), 0) FROM reports) - ?').bind(KEEP_REPORTS),
  ]);
}

// --- HTTP helpers -----------------------------------------------------------------------------------

const SECURITY_HEADERS = {
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer',
  'Cache-Control': 'no-store',
};

function text(body, status = 200, extra = {}) {
  return new Response(body, {
    status, headers: { 'Content-Type': 'text/plain; charset=UTF-8', ...SECURITY_HEADERS, ...extra },
  });
}

function json(body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json; charset=UTF-8', ...SECURITY_HEADERS, ...extra },
  });
}

/** The body as text, or null when it is longer than max bytes (declared or real). */
async function readBody(request, max) {
  const declared = Number(request.headers.get('Content-Length') || '0');
  if (declared > max) return null;
  if (!request.body) return '';
  const reader = request.body.getReader();
  const chunks = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > max) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const all = new Uint8Array(size);
  let at = 0;
  for (const c of chunks) {
    all.set(c, at);
    at += c.byteLength;
  }
  return new TextDecoder().decode(all);
}

async function digest(value) {
  return new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)));
}

/** Equal-time comparison: both sides are hashed first, so the length of the secret does not leak. */
export async function sameSecret(a, b) {
  const [x, y] = await Promise.all([digest(String(a)), digest(String(b))]);
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

/** True when the request carries the maintainer's HTTP Basic user and password. */
export async function authorised(request, env) {
  const user = env.STATS_USER || '';
  const pass = env.STATS_PASSWORD || '';
  if (user.length < 3 || pass.length < 16) return false; // never open with a missing or weak secret
  const header = request.headers.get('Authorization') || '';
  if (!/^Basic /i.test(header)) return false;
  let decoded = '';
  try {
    // RFC 7617 with charset="UTF-8": base64 of the UTF-8 bytes.
    const bytes = Uint8Array.from(atob(header.slice(6).trim()), (c) => c.charCodeAt(0));
    decoded = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  } catch {
    return false;
  }
  const colon = decoded.indexOf(':');
  if (colon < 0) return false;
  const okUser = await sameSecret(decoded.slice(0, colon), user);
  const okPass = await sameSecret(decoded.slice(colon + 1), pass);
  return okUser && okPass;
}

function unauthorised() {
  return text('Unauthorized\n', 401, { 'WWW-Authenticate': 'Basic realm="wts stats", charset="UTF-8"' });
}

function intParam(params, name, fallback, min, max) {
  const raw = params.get(name);
  if (raw === null || raw === '') return fallback;
  if (!/^\d{1,15}$/.test(raw)) return undefined;
  const n = Number(raw);
  return n < min || n > max ? undefined : n;
}

// --- view page ----------------------------------------------------------------------------------------

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ESC[c]);
}

function table(headers, rows) {
  const head = headers.map((h) => `<th>${esc(h)}</th>`).join('');
  const body = rows.map((r) => `<tr>${headers.map((h) => `<td>${esc(r[h])}</td>`).join('')}</tr>`).join('');
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

async function viewPage(db) {
  const days = await db
    .prepare(`SELECT substr(server_time, 1, 10) AS day, COUNT(*) AS runs,
                     COUNT(DISTINCT NULLIF(install_id, '')) AS installs
              FROM runs WHERE id > (SELECT COALESCE(MAX(id), 0) FROM runs) - ?
              GROUP BY day ORDER BY day DESC LIMIT 14`)
    .bind(VIEW_WINDOW)
    .all();
  const runs = await db
    .prepare(`SELECT id, server_time, program_version, platform_system, country_code, language, model, status,
                     word_count, audio_duration, transcription_time
              FROM runs ORDER BY id DESC LIMIT 200`)
    .all();
  const reports = await db
    .prepare('SELECT id, server_time, program_version, os, machine, text, log FROM reports ORDER BY id DESC LIMIT 50')
    .all();
  const reportHtml = reports.results
    .map((r) => `<article><h3>#${esc(r.id)} · ${esc(r.server_time)} · ${esc(r.program_version)} · ${esc(r.os)}
      ${esc(r.machine)}</h3><pre>${esc(r.text)}</pre>${r.log ? `<details><summary>log</summary><pre>${esc(r.log)}</pre></details>` : ''}</article>`)
    .join('');
  return `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>WTS stats</title><style>
body{font:14px/1.4 system-ui,sans-serif;margin:16px;color:#111;background:#fff}
table{border-collapse:collapse;margin:8px 0 24px;font-size:12px}td,th{border:1px solid #ccc;padding:2px 6px;text-align:left}
pre{white-space:pre-wrap;word-break:break-word;background:#f5f5f5;padding:8px}article{border-top:1px solid #ddd}
@media (prefers-color-scheme:dark){body{background:#111;color:#eee}pre{background:#222}td,th{border-color:#444}}
</style></head><body><h1>Whisper Transcriber Suite: usage</h1>
<h2>Recent days (newest runs only)</h2>${table(['day', 'runs', 'installs'], days.results)}
<h2>Problem reports (latest 50)</h2>${reportHtml || '<p>None.</p>'}
<h2>Latest 200 runs</h2>${table(['id', 'server_time', 'program_version', 'platform_system', 'country_code', 'language', 'model', 'status', 'word_count', 'audio_duration', 'transcription_time'], runs.results)}
</body></html>`;
}

// --- routes -------------------------------------------------------------------------------------------

export async function handle(request, env, nowMs = Date.now()) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, '') || '/';
  const now = new Date(nowMs).toISOString();
  const db = env.DB;

  if (path === '/v1/runs') {
    if (request.method !== 'POST') return text('Method Not Allowed\n', 405, { Allow: 'POST' });
    const body = await readBody(request, MAX_RUN_BODY);
    if (body === null) return text('Payload Too Large\n', 413);
    const row = runFromForm(new URLSearchParams(body), now);
    if (!row) return text('Bad Request\n', 400);
    await insert(db, 'runs', row);
    return text('OK\n');
  }

  if (path === '/v1/report') {
    if (request.method !== 'POST') return json({ ok: false, error: 'method not allowed' }, 405, { Allow: 'POST' });
    const body = await readBody(request, MAX_REPORT_BODY);
    if (body === null) return json({ ok: false, error: 'too large' }, 413);
    let data;
    try {
      data = JSON.parse(body);
    } catch {
      return json({ ok: false, error: 'invalid JSON' }, 400);
    }
    const parsed = reportFromJson(data, now);
    if (parsed.error) return json({ ok: false, error: parsed.error }, 400);
    const id = await insert(db, 'reports', parsed.row);
    return json({ ok: true, id });
  }

  if (path === '/v1/export' || path === '/view') {
    if (request.method !== 'GET') return text('Method Not Allowed\n', 405, { Allow: 'GET' });
    if (!(await authorised(request, env))) return unauthorised();
    if (path === '/view') {
      return new Response(await viewPage(db), {
        headers: {
          'Content-Type': 'text/html; charset=UTF-8', ...SECURITY_HEADERS,
          'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'",
          'X-Frame-Options': 'DENY',
        },
      });
    }
    const p = url.searchParams;
    const kind = p.get('kind') || 'runs';
    const since = intParam(p, 'since_id', 0, 0, 999999999999999);
    const limit = intParam(p, 'limit', 500, 1, kind === 'reports' ? REPORT_EXPORT_LIMIT : 1000);
    const upto = intParam(p, 'upto_id', null, 0, 999999999999999);
    if (!['runs', 'reports'].includes(kind) || since === undefined || limit === undefined || upto === undefined) {
      return json({ error: 'bad parameter' }, 400);
    }
    return json(await exportRows(db, kind, since, limit, upto));
  }

  if (path === '/') {
    if (request.method !== 'GET' && request.method !== 'HEAD') return text('Method Not Allowed\n', 405);
    return text('Whisper Transcriber Suite usage statistics endpoint.\n');
  }
  return text('Not Found\n', 404);
}

export default {
  async fetch(request, env) {
    try {
      return await handle(request, env);
    } catch (e) {
      console.error('wts-stats error', e && e.message); // no request data in the log
      return text('ERROR\n', 500);
    }
  },
  async scheduled(_event, env) {
    await purgeOld(env.DB);
  },
};
