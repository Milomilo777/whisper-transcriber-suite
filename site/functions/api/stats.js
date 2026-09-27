// Cloudflare Pages Function: public visit + download counters for the website.
//
//   GET  /api/stats  -> {"visits": n|null, "downloads": n|null}
//   POST /api/stats  -> counts one visit, then returns the same shape
//
// Visits live in a D1 database bound to the Pages project as VISITS_DB
// (Settings -> Bindings). Without the binding, visits is null and the page
// hides that number. Nothing personal is stored: no IP, no cookie, only a
// single integer. The page itself posts at most once per browser per day.
//
// Downloads = the sum of every release asset's GitHub download count,
// cached at the edge for an hour so GitHub's API sees at most a few calls.

const VISITS_START = 1350; // visits recorded on the previous site address
const REPO = 'Milomilo777/whisper-transcriber-suite';
const BOT_UA = /bot|crawl|spider|slurp|preview|headless|lighthouse|monitor|curl|wget|python|httpclient/i;

let schemaReady = false;

async function ensureSchema(db) {
  if (schemaReady) return;
  await db.batch([
    db.prepare('CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL)'),
    db.prepare("INSERT OR IGNORE INTO counters (name, value) VALUES ('visits', ?)").bind(VISITS_START),
  ]);
  schemaReady = true;
}

async function visits(env, count) {
  const db = env.VISITS_DB;
  if (!db) return null;
  try {
    await ensureSchema(db);
    const row = count
      ? await db.prepare("UPDATE counters SET value = value + 1 WHERE name = 'visits' RETURNING value").first()
      : await db.prepare("SELECT value FROM counters WHERE name = 'visits'").first();
    return row ? row.value : null;
  } catch (e) {
    return null;
  }
}

async function downloads(ctx) {
  const cache = caches.default;
  const key = new Request('https://stats.internal/downloads');
  const hit = await cache.match(key);
  if (hit) return (await hit.json()).downloads;
  try {
    let total = 0;
    for (let page = 1; page <= 10; page++) {
      const r = await fetch(`https://api.github.com/repos/${REPO}/releases?per_page=100&page=${page}`, {
        headers: { 'User-Agent': 'whisper-transcriber-suite-site', Accept: 'application/vnd.github+json' },
      });
      if (!r.ok) return null;
      const batch = await r.json();
      for (const rel of batch) for (const a of rel.assets) if (!a.name.endsWith('.sha256')) total += a.download_count;
      if (batch.length < 100) break;
    }
    const body = JSON.stringify({ downloads: total });
    ctx.waitUntil(cache.put(key, new Response(body, { headers: { 'Cache-Control': 'max-age=3600' } })));
    return total;
  } catch (e) {
    return null;
  }
}

export async function onRequest(ctx) {
  const { request, env } = ctx;
  if (request.method !== 'GET' && request.method !== 'POST') {
    return new Response(null, { status: 405, headers: { Allow: 'GET, POST' } });
  }
  const isBot = BOT_UA.test(request.headers.get('User-Agent') || '');
  const count = request.method === 'POST' && !isBot;
  const [v, d] = await Promise.all([visits(env, count), downloads(ctx)]);
  return new Response(JSON.stringify({ visits: v, downloads: d }), {
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  });
}
