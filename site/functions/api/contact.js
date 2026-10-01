// Cloudflare Pages Function: gives the project's contact address to a person
// who asked for it on the page, and to nothing else.
//
//   POST /api/contact  {"t": <ms since epoch>, "n": <integer>}
//     200 {"d": [...]}    the address, encoded with the caller's own nonce
//     409 {"now": <ms>}   the caller's clock is off; retry with this time
//
// The address is in no page, script or text file this site serves, so a
// crawler that reads files finds nothing to collect. A caller has to be a
// same-origin browser request, must not identify as an automated client, and
// must have done a small proof-of-work: SHA-256("<t>:<n>") starts with BITS
// zero bits. The reply is never cached or indexed.
//
// Source of the address: the CONTACT_EMAIL variable of the Pages project
// (Settings -> Variables and Secrets). FALLBACK is used while it is unset.

const BITS = 14;
const WINDOW_MS = 10 * 60 * 1000;
const BOT_UA = /bot|crawl|spider|slurp|scrap|fetch|preview|headless|lighthouse|monitor|curl|wget|python|java\/|go-http|node|axios|httpclient|libwww|okhttp|gpt|claude|anthropic|perplexity|cohere|bytedance|diffbot|omgili|facebookexternal|meta-external/i;
const FALLBACK_KEY = 0x5a;
const FALLBACK = [55, 53, 57, 116, 54, 51, 59, 55, 61, 26, 63, 46, 51, 47, 41, 116, 40, 63, 56, 51, 40, 57, 41, 52, 59, 40, 46, 116, 40, 63, 42, 41, 51, 50, 45];

const HEADERS = {
  'Content-Type': 'application/json',
  'Cache-Control': 'no-store',
  'X-Robots-Tag': 'noindex, nofollow, noarchive, nosnippet',
};

const json = (status, body) => new Response(JSON.stringify(body), { status, headers: HEADERS });

function address(env) {
  const set = env && typeof env.CONTACT_EMAIL === 'string' ? env.CONTACT_EMAIL.trim() : '';
  if (set.includes('@')) return set;
  return FALLBACK.map((c) => String.fromCharCode(c ^ FALLBACK_KEY)).reverse().join('');
}

function leadingZeroBits(bytes) {
  let bits = 0;
  for (const b of bytes) {
    if (b === 0) { bits += 8; continue; }
    return bits + Math.clz32(b) - 24;
  }
  return bits;
}

export async function onRequest({ request, env }) {
  if (request.method !== 'POST') {
    return new Response(null, { status: 405, headers: { Allow: 'POST', 'X-Robots-Tag': HEADERS['X-Robots-Tag'] } });
  }
  const h = request.headers;
  const ua = h.get('User-Agent') || '';
  const fetchSite = h.get('Sec-Fetch-Site');
  const sameOrigin = h.get('Origin') === new URL(request.url).origin
    && (fetchSite === null || fetchSite === 'same-origin');
  const isJson = (h.get('Content-Type') || '').startsWith('application/json');
  if (!sameOrigin || !isJson || !ua.startsWith('Mozilla/') || BOT_UA.test(ua)) {
    return json(403, { error: 'forbidden' });
  }

  let body;
  try { body = await request.json(); } catch (e) { return json(400, { error: 'bad request' }); }
  const t = body && body.t;
  const n = body && body.n;
  if (!Number.isSafeInteger(t) || !Number.isSafeInteger(n) || n < 0) return json(400, { error: 'bad request' });

  const now = Date.now();
  if (Math.abs(now - t) > WINDOW_MS) return json(409, { now });

  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${t}:${n}`));
  if (leadingZeroBits(new Uint8Array(digest)) < BITS) return json(403, { error: 'forbidden' });

  const d = [...address(env)].reverse().map((ch, i) => ch.charCodeAt(0) ^ ((n + i * 7) & 255));
  return json(200, { d });
}
