import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fakeD1 } from './fake-d1.mjs';
import worker, {
  handle, purgeOld, cleanText, cleanNumber, esc, MAX_RUN_BODY, MAX_REPORT_BODY, REPORT_TEXT_CHARS,
  REPORT_LOG_CHARS, KEEP_RUNS,
} from '../src/index.js';

const BASE = 'https://stats.example.test';
const USER = 'maintainer';
const PASS = 'correct-horse-battery-staple-42';

function env(extra = {}) {
  return { DB: fakeD1(), STATS_USER: USER, STATS_PASSWORD: PASS, ...extra };
}

function basic(user, pass) {
  return 'Basic ' + Buffer.from(`${user}:${pass}`).toString('base64');
}

function req(path, init = {}) {
  return new Request(BASE + path, init);
}

// What core/stats.py build_stats_payload sends (form-encoded).
function appPayload(overrides = {}) {
  return new URLSearchParams({
    form_submitted: '1', country: 'AU', model: 'faster-whisper-small', language: 'fa',
    audio_duration: '125.5', transcription_time: '33.2', word_count: '812', status: 'completed',
    program_version: '2.3.0 (Windows)', platform_system: 'Windows', platform_release: '10',
    platform_version: '10.0.19045', platform_machine: 'AMD64',
    platform_processor: 'Intel64 Family 6 Model 158', cpu_count: '8', mem_total: '17087848448',
    install_id: '0f8fad5b-d9cb-469f-a165-70867728950e', ...overrides,
  });
}

function postRun(e, params, extraInit = {}) {
  return handle(req('/v1/runs', {
    method: 'POST', body: params.toString(),
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, ...extraInit,
  }), e);
}

function postReport(e, body) {
  return handle(req('/v1/report', {
    method: 'POST', body: typeof body === 'string' ? body : JSON.stringify(body),
    headers: { 'Content-Type': 'application/json' },
  }), e);
}

function rows(e, table) {
  return e.DB.raw.prepare(`SELECT * FROM ${table} ORDER BY id`).all().map((r) => ({ ...r }));
}

test('a real app payload is stored with every field and the reply is OK', async () => {
  const e = env();
  const res = await postRun(e, appPayload());
  assert.equal(res.status, 200);
  assert.equal(await res.text(), 'OK\n');
  const [row] = rows(e, 'runs');
  assert.equal(row.country_code, 'AU');
  assert.equal(row.model, 'faster-whisper-small');
  assert.equal(row.language, 'fa');
  assert.equal(row.audio_duration, 125.5);
  assert.equal(row.word_count, 812);
  assert.equal(row.mem_total, 17087848448);
  assert.equal(row.install_id, '0f8fad5b-d9cb-469f-a165-70867728950e');
  assert.match(row.server_time, /^\d{4}-\d\d-\d\dT/);
});

test('nothing identifying is stored: no address column exists and sent extras are ignored', async () => {
  const e = env();
  await handle(req('/v1/runs', {
    method: 'POST', body: appPayload({ file_name: 'C:/Users/Mo/secret.mp4', client_ip: '1.2.3.4' }).toString(),
    headers: { 'CF-Connecting-IP': '203.0.113.9', 'Content-Type': 'application/x-www-form-urlencoded' },
  }), e);
  const stored = JSON.stringify(rows(e, 'runs'));
  for (const leak of ['secret.mp4', '1.2.3.4', '203.0.113.9']) assert.ok(!stored.includes(leak), leak);
});

test('text fields are capped and control characters removed, like the PHP endpoint', async () => {
  const e = env();
  await postRun(e, appPayload({ model: 'm\u0000o\u001fd\u007fel' + 'x'.repeat(500), language: '\u{1F600}'.repeat(40) }));
  const [row] = rows(e, 'runs');
  assert.ok(row.model.startsWith('model'));
  assert.equal(Array.from(row.model).length, 128);
  assert.equal(Array.from(row.language).length, 32); // code points, not UTF-16 halves
  assert.ok(!/[\u0000-\u001f\u007f]/.test(row.model));
});

test('numbers outside their bounds become 0 or the bound; bad country codes are dropped', async () => {
  const e = env();
  await postRun(e, appPayload({
    audio_duration: '-5', transcription_time: '1e400', word_count: '5e12', cpu_count: 'NaN', country: 'au',
  }));
  const [row] = rows(e, 'runs');
  assert.equal(row.audio_duration, 0);
  assert.equal(row.transcription_time, 0);
  assert.equal(row.word_count, 1e9);
  assert.equal(row.cpu_count, 0);
  assert.equal(row.country_code, '');
  assert.equal(cleanNumber(' 12.5 ', 100), 12.5);
  assert.equal(cleanNumber('0x10', 100), 0);
});

test('a form without form_submitted, a GET and an oversized body store nothing', async () => {
  const e = env();
  const p = appPayload();
  p.delete('form_submitted');
  assert.equal((await postRun(e, p)).status, 400);
  assert.equal((await handle(req('/v1/runs'), e)).status, 405);
  const big = appPayload({ platform_version: 'x'.repeat(MAX_RUN_BODY) });
  assert.equal((await postRun(e, big)).status, 413);
  assert.equal((await postRun(e, big, { headers: { 'Content-Length': '1', 'Content-Type': 'x' } })).status, 413);
  assert.equal(rows(e, 'runs').length, 0);
});

test('a problem report keeps its line breaks and is capped', async () => {
  const e = env();
  const res = await postReport(e, {
    text: 'It crashed.\nSteps:\r\n1. open\u0007', log: 'L\n'.repeat(REPORT_LOG_CHARS), os: 'Windows 10',
    machine: 'AMD64', program_version: '2.3.0', install_id: 'abc',
  });
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.ok, true);
  assert.equal(body.id, 1);
  const [row] = rows(e, 'reports');
  assert.equal(row.text, 'It crashed.\nSteps:\n1. open');
  assert.equal(row.log.length, REPORT_LOG_CHARS);
  assert.equal(row.os, 'Windows 10');
  const long = await postReport(e, { text: 'y'.repeat(REPORT_TEXT_CHARS + 50) });
  assert.equal(long.status, 200);
  assert.equal(rows(e, 'reports')[1].text.length, REPORT_TEXT_CHARS);
});

test('bad reports are refused with a reason and store nothing', async () => {
  const e = env();
  assert.equal((await postReport(e, '{not json')).status, 400);
  assert.equal((await postReport(e, '[1,2]')).status, 400);
  const empty = await postReport(e, { text: ' \n\u0000 ' });
  assert.equal(empty.status, 400);
  assert.equal((await empty.json()).error, 'text is empty');
  assert.equal((await postReport(e, { text: 'x'.repeat(MAX_REPORT_BODY) })).status, 413);
  assert.equal((await handle(req('/v1/report'), e)).status, 405);
  assert.equal(rows(e, 'reports').length, 0);
});

test('the view and the export need the maintainer password', async () => {
  const e = env();
  for (const path of ['/view', '/v1/export']) {
    const none = await handle(req(path), e);
    assert.equal(none.status, 401);
    assert.match(none.headers.get('WWW-Authenticate'), /^Basic /);
    assert.equal((await handle(req(path, { headers: { Authorization: basic(USER, PASS + 'x') } }), e)).status, 401);
    assert.equal((await handle(req(path, { headers: { Authorization: basic('other', PASS) } }), e)).status, 401);
    assert.equal((await handle(req(path, { headers: { Authorization: 'Basic %%%' } }), e)).status, 401);
    assert.equal((await handle(req(path, { headers: { Authorization: basic(USER, PASS) } }), e)).status, 200);
  }
});

test('a missing or weak secret never opens the view, even to a matching header', async () => {
  for (const extra of [{ STATS_PASSWORD: '' }, { STATS_PASSWORD: 'short' }, { STATS_USER: undefined }]) {
    const e = env(extra);
    const auth = basic(e.STATS_USER ?? '', e.STATS_PASSWORD ?? '');
    assert.equal((await handle(req('/view', { headers: { Authorization: auth } }), e)).status, 401);
  }
});

test('the view escapes what people typed and sends no-store + a strict CSP', async () => {
  const e = env();
  await postReport(e, { text: '<script>alert(1)</script> & "q"', log: '<img src=x onerror=alert(2)>' });
  await postRun(e, appPayload({ model: '<b>bold</b>' }));
  const res = await handle(req('/view', { headers: { Authorization: basic(USER, PASS) } }), e);
  const html = await res.text();
  assert.ok(!html.includes('<script>alert'));
  assert.ok(!html.includes('<img src=x'));
  assert.ok(!html.includes('<b>bold</b>'));
  assert.ok(html.includes('&lt;script&gt;alert(1)&lt;/script&gt; &amp; &quot;q&quot;'));
  assert.equal(res.headers.get('Cache-Control'), 'no-store');
  assert.match(res.headers.get('Content-Security-Policy'), /default-src 'none'/);
  assert.equal(esc(`'`), '&#39;');
});

test('the export pages through rows in the PHP export shape', async () => {
  const e = env();
  for (let i = 0; i < 5; i++) await postRun(e, appPayload({ word_count: String(i) }));
  const auth = { headers: { Authorization: basic(USER, PASS) } };
  const first = await (await handle(req('/v1/export?since_id=0&limit=2', auth), e)).json();
  assert.deepEqual(first.rows.map((r) => r.id), [1, 2]);
  assert.equal(first.next_since_id, 2);
  assert.equal(first.upto_id, 5);
  assert.equal(first.has_more, true);
  assert.equal(first.count, 2);
  assert.ok(first.source_id);
  await postRun(e, appPayload()); // id 6 arrives during paging: the fixed upper bound keeps it for later
  const second = await (await handle(req('/v1/export?since_id=2&limit=1000&upto_id=5', auth), e)).json();
  assert.deepEqual(second.rows.map((r) => r.id), [3, 4, 5]);
  assert.equal(second.has_more, false);
  assert.equal(second.rows[0].word_count, 2);
  assert.ok(!('client_ip' in second.rows[0]));
});

test('the export of reports and its parameter checks', async () => {
  const e = env();
  await postReport(e, { text: 'one' });
  const auth = { headers: { Authorization: basic(USER, PASS) } };
  const out = await (await handle(req('/v1/export?kind=reports', auth), e)).json();
  assert.equal(out.rows[0].text, 'one');
  assert.equal(out.kind, 'reports');
  for (const q of ['kind=users', 'since_id=-1', 'limit=0', 'limit=1001', 'since_id=abc', 'upto_id=1e3']) {
    assert.equal((await handle(req('/v1/export?' + q, auth), e)).status, 400, q);
  }
});

test('the purge keeps the newest rows and ids keep growing afterwards', async () => {
  const e = env();
  const db = e.DB.raw;
  const insert = db.prepare("INSERT INTO runs (id, server_time) VALUES (?, '2026-01-01T00:00:00Z')");
  for (const id of [1, 2, KEEP_RUNS + 1, KEEP_RUNS + 3]) insert.run(id);
  await purgeOld(e.DB);
  assert.deepEqual(rows(e, 'runs').map((r) => r.id), [KEEP_RUNS + 1, KEEP_RUNS + 3]);
  await postRun(e, appPayload());
  assert.equal(rows(e, 'runs').at(-1).id, KEEP_RUNS + 4);
});

test('other paths and methods', async () => {
  const e = env();
  const root = await handle(req('/'), e);
  assert.equal(root.status, 200);
  assert.match(await root.text(), /statistics endpoint/);
  assert.equal((await handle(req('/v1/runs/'), e)).status, 405); // trailing slash = same route
  assert.equal((await handle(req('/admin'), e)).status, 404);
  assert.equal((await handle(req('/', { method: 'POST', body: 'x' }), e)).status, 405);
});

test('an internal error answers 500 without details', async () => {
  const broken = { ...env(), DB: { prepare() { throw new Error('D1 down: SELECT secret'); } } };
  const orig = console.error;
  console.error = () => {};
  try {
    const res = await worker.fetch(req('/v1/runs', { method: 'POST', body: appPayload().toString() }), broken);
    assert.equal(res.status, 500);
    assert.equal(await res.text(), 'ERROR\n');
  } finally {
    console.error = orig;
  }
});

test('cleanText keeps line breaks and tabs only when asked', () => {
  assert.equal(cleanText('a\nb\tc', 10), 'abc');
  assert.equal(cleanText('a\r\nb\tc\u0007', 10, true), 'a\nb\tc');
  assert.equal(cleanText(42, 10), '');
});
