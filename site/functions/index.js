// Cloudflare Pages Function for "/" only: send a first-time visitor to the website in their language.
//
//   1. ?lang=en (the "View in English" link) -> remember English, show the English page.
//   2. A wts_lang cookie (set when someone picks a language in the menu) wins over everything else.
//   3. Search engines, link previews and scripts (no Accept-Language) always get the English page.
//   4. Otherwise the visitor's country (request.cf.country) gives candidate languages
//      (COUNTRY_LANGS, from Unicode CLDR); the browser's Accept-Language picks among them, and a
//      published language other than English that the browser prefers wins over them. No match ->
//      English where it is a candidate, else the country's first language. English, an unknown
//      country or a language not yet published -> the English page.
//
// A redirect is a 302 to /<lang>/?auto=1 (the page then says why it is in that language) and is never
// cached, because it depends on the visitor. Every language page stays reachable at its own address
// for everyone, and nothing is stored on the server. Any error falls back to the English page.

// "bot" must end a word and not be the phone brand Cubot: Googlebot/2.1 and bingbot/ match,
// "CUBOT X30" does not. The named fetchers carry no "bot" in their User-Agent; names that also
// appear in the in-app browsers of real people (KakaoTalk, Daum, Viber, Tumblr) are left out.
const BOT_UA = new RegExp([
  '(?<!cu)bot\\b', 'crawl', 'spider', 'slurp', 'preview', 'headless', 'lighthouse', 'monitor',
  'google-(inspectiontool|extended|read-aloud|pagerenderer|site-verification|safety)', 'googleother',
  'apis-google', 'mediapartners-google', 'feedfetcher-google', 'chatgpt-user', 'claude-(user|web|searchbot)',
  'anthropic-ai', 'perplexity-user', 'meta-external', 'cohere-ai', '\\byeti\\b', 'daumoa', 'qwantify',
  'yandex(images|metrika|direct|webmaster)', 'mastodon/', 'cardyb', 'kakaotalk-scrap', 'slack-imgproxy',
  'iframely', 'flipboardproxy', 'github-camo', 'pingdom', 'statuscake', 'gtmetrix', 'ptst/', 'newsblur',
  'wkhtml', 'phantomjs', 'jsdom', 'w3c_validator', 'curl', 'wget', 'python[-/]', 'httpclient', 'okhttp',
  'axios', 'node-fetch', 'undici', 'libwww', 'scrapy', 'postman', 'httpie', 'go-http-client', '^java/',
  'facebookexternalhit', 'whatsapp', 'embedly', 'pinterest', 'vkshare', 'quora',
].join('|'), 'i');
const COOKIE = 'wts_lang';
const YEAR = 60 * 60 * 24 * 365;

// published:start (tools/site_i18n.py build)
const PUBLISHED = ['en'];
// published:end

// country-lang:start (tools/site_country_lang.py)
const COUNTRY_LANGS = {
  "AD":["ca","es"],
  "AE":["ar","en"],
  "AF":["fa"],
  "AO":["pt"],
  "AR":["es"],
  "AT":["de","en"],
  "AW":["nl"],
  "AX":["sv"],
  "BD":["bn","en"],
  "BE":["en","nl","fr","de"],
  "BF":["fr"],
  "BG":["bg","en","ru"],
  "BH":["ar"],
  "BI":["fr"],
  "BJ":["fr"],
  "BL":["fr"],
  "BN":["ms"],
  "BO":["es"],
  "BR":["pt-BR"],
  "BV":["nb"],
  "BZ":["en","es"],
  "CA":["en","fr"],
  "CC":["ms","en"],
  "CD":["fr"],
  "CF":["fr"],
  "CG":["fr"],
  "CH":["de","en","fr","it"],
  "CI":["fr"],
  "CL":["es"],
  "CM":["fr","en"],
  "CN":["zh-CN"],
  "CO":["es"],
  "CR":["es"],
  "CU":["es"],
  "CV":["pt"],
  "CY":["el","en","tr"],
  "CZ":["cs","en","sk","de"],
  "DE":["de","en","fr"],
  "DJ":["fr"],
  "DK":["da","en","de"],
  "DO":["es"],
  "DZ":["ar","fr"],
  "EA":["es"],
  "EC":["es"],
  "EE":["ru","en","fi"],
  "EG":["ar","en"],
  "EH":["ar"],
  "ES":["es","en","ca"],
  "FI":["fi","en","sv","de"],
  "FJ":["en","hi"],
  "FR":["fr","en"],
  "GA":["fr"],
  "GB":["en","fr"],
  "GF":["fr"],
  "GI":["en","es"],
  "GN":["fr"],
  "GP":["fr"],
  "GQ":["es","fr"],
  "GR":["el","en"],
  "GT":["es"],
  "GW":["pt","fr"],
  "HK":["zh-TW","en"],
  "HN":["es"],
  "HR":["hr","en"],
  "HT":["fr"],
  "HU":["hu","en","de"],
  "IC":["es"],
  "ID":["id"],
  "IL":["he","en","ar"],
  "IN":["hi","en"],
  "IQ":["ar","en"],
  "IR":["fa"],
  "IT":["it","en","fr"],
  "JO":["ar","en"],
  "JP":["ja"],
  "KG":["ru"],
  "KM":["ar","fr"],
  "KP":["ko"],
  "KR":["ko"],
  "KW":["ar"],
  "KZ":["ru","en"],
  "LB":["ar","en","fr"],
  "LI":["de"],
  "LT":["lt","ru","en"],
  "LU":["fr","de","en","pt"],
  "LV":["lv","en","ru"],
  "LY":["ar"],
  "MA":["ar","fr"],
  "MC":["fr"],
  "MD":["ro"],
  "ME":["sr"],
  "MF":["fr"],
  "MG":["fr","en"],
  "ML":["fr"],
  "MO":["zh-TW","en"],
  "MQ":["fr"],
  "MR":["ar"],
  "MT":["en","it"],
  "MU":["fr","en"],
  "MX":["es"],
  "MY":["ms","en","zh-CN"],
  "MZ":["pt"],
  "NC":["fr"],
  "NI":["es"],
  "NL":["nl","en","de","fr"],
  "NO":["nb"],
  "OM":["ar"],
  "PA":["es"],
  "PE":["es"],
  "PF":["fr"],
  "PH":["en","fil","es"],
  "PL":["pl","en","de","ru"],
  "PM":["fr"],
  "PR":["es","en"],
  "PS":["ar"],
  "PT":["pt","en","fr"],
  "QA":["ar"],
  "RE":["fr"],
  "RO":["ro","en"],
  "RS":["sr"],
  "RU":["ru"],
  "SA":["ar"],
  "SC":["fr","en"],
  "SD":["ar","en"],
  "SE":["sv","en"],
  "SG":["en","zh-CN"],
  "SI":["sl","hr","en","de"],
  "SJ":["nb","ru"],
  "SK":["sk","cs","en","de"],
  "SM":["it"],
  "SN":["fr"],
  "SO":["ar"],
  "SR":["nl"],
  "SS":["ar","en"],
  "ST":["pt","fr"],
  "SV":["es"],
  "SY":["ar"],
  "TD":["ar"],
  "TF":["fr"],
  "TG":["fr"],
  "TH":["th","en"],
  "TL":["pt"],
  "TN":["ar","fr"],
  "TR":["tr","en"],
  "TW":["zh-TW"],
  "UA":["uk","ru"],
  "UY":["es"],
  "VA":["it"],
  "VE":["es"],
  "VN":["vi"],
  "VU":["en","fr"],
  "WF":["fr"],
  "YE":["ar"],
  "YT":["fr"]
};
// country-lang:end

// Browser language tag -> website language code.
function siteCode(tag) {
  const t = tag.toLowerCase().replace(/_/g, '-');
  if (/^zh-(.*-)?(tw|hk|mo|hant)\b/.test(t) || /^yue\b/.test(t)) return 'zh-TW';
  if (t === 'zh') return 'zh'; // a bare "zh" takes the country's script, see pickLanguage
  if (t.startsWith('zh')) return 'zh-CN';
  if (t === 'pt-br') return 'pt-BR';
  if (t.startsWith('pt')) return 'pt';
  if (/^(nb|no|nn)\b/.test(t)) return 'nb';
  if (/^(fil|tl)\b/.test(t)) return 'fil';
  if (/^(he|iw)\b/.test(t)) return 'he';
  if (/^(id|in)\b/.test(t)) return 'id';
  return t.split('-')[0];
}

// Accept-Language header -> website codes, most preferred first.
function acceptLanguages(header) {
  return (header || '')
    .split(',')
    .map((part, i) => {
      const [tag, ...params] = part.trim().split(';');
      const q = params.map((p) => p.trim().match(/^q\s*=\s*(.*)$/i)).find(Boolean);
      return { tag: tag.trim(), q: q ? Math.min(1, parseFloat(q[1]) || 0) : 1, i };
    })
    .filter((x) => x.tag && x.tag !== '*' && x.q > 0)
    .sort((a, b) => b.q - a.q || a.i - b.i)
    .map((x) => siteCode(x.tag));
}

// Every value of the cookie, in header order (a browser may send two with different paths).
function cookieValues(header, name) {
  const out = [];
  for (const part of (header || '').split(';')) {
    const [k, ...v] = part.trim().split('=');
    if (k === name) {
      try {
        out.push(decodeURIComponent(v.join('=')));
      } catch (e) {
        // a malformed value counts as no choice
      }
    }
  }
  return out;
}

// The language "/" should show: a published code, 'en' meaning the English page itself.
// Codes compare case-insensitively (a cookie may say zh-tw); the published spelling is returned.
// cookie is one value or a list of them; the first published one counts.
export function pickLanguage({ country, acceptLanguage, cookie, userAgent, published = PUBLISHED, table = COUNTRY_LANGS }) {
  const pub = new Map(['en', ...published].map((c) => [c.toLowerCase(), c]));
  const saved = [].concat(cookie || []).find((c) => pub.has(String(c).toLowerCase()));
  if (saved) return pub.get(String(saved).toLowerCase());
  // every browser sends Accept-Language; crawlers and link checkers often do not
  if (!userAgent || !acceptLanguage || BOT_UA.test(userAgent)) return 'en';
  // the table leaves out countries whose only language is English (US, AU, ...); XX and T1 = unknown
  const cc = (country || '').toUpperCase();
  const langs = table[cc] || (/^[A-Z]{2}$/.test(cc) && cc !== 'XX' ? ['en'] : []);
  // pt-BR also matches a browser that only says "pt", zh-TW one that only says "zh", and the other way round
  const loose = (c) => c.toLowerCase().replace(/^(pt|zh)-.*/, '$1');
  for (const want of acceptLanguages(acceptLanguage)) {
    const w = want.toLowerCase();
    const exact = langs.find((c) => c.toLowerCase() === w);
    const near = langs.find((c) => loose(c) === loose(w));
    // a published language the browser asks for wins over the country, except English: many people
    // use an English browser in a country whose language they read, which is why "/" asks the country
    const own = langs.length && w !== 'en' ? (w === 'zh' ? 'zh-cn' : w) : null;
    // a bare "pt" or "zh" means this country's variant; "pt-br" means itself
    const order = w.includes('-') ? [exact, own, near] : [exact, near, own];
    // a language not published yet: the next choice, then the browser's next language
    const found = order.find((c) => c && pub.has(c.toLowerCase()));
    if (found) return pub.get(found.toLowerCase());
  }
  if (!langs.length || langs.includes('en')) return 'en';
  return pub.get(langs[0].toLowerCase()) || 'en';
}

export async function onRequestGet({ request, next }) {
  try {
    const url = new URL(request.url);
    if (url.searchParams.get('lang') === 'en') {
      const res = await next();
      const out = new Response(res.body, res);
      out.headers.append('Set-Cookie', `${COOKIE}=en; Path=/; Max-Age=${YEAR}; SameSite=Lax; Secure`);
      out.headers.set('Cache-Control', 'private, no-store');
      return out;
    }
    const cookie = cookieValues(request.headers.get('Cookie'), COOKIE);
    const code = pickLanguage({
      country: request.cf && request.cf.country,
      acceptLanguage: request.headers.get('Accept-Language'),
      cookie,
      userAgent: request.headers.get('User-Agent') || '',
    });
    if (code === 'en') {
      // the English page is also an answer that depends on these headers
      const res = await next();
      const out = new Response(res.body, res);
      out.headers.set('Vary', 'Cookie, Accept-Language');
      return out;
    }
    const fromCookie = cookie.some((c) => c.toLowerCase() === code.toLowerCase());
    // keep the visitor's other query parameters (campaign tags, ?motion=off)
    const query = new URLSearchParams(url.search);
    query.delete('lang');
    if (!fromCookie) query.set('auto', '1');
    const qs = query.toString();
    const target = `/${code.toLowerCase()}/${qs ? `?${qs}` : ''}`;
    return new Response(null, {
      status: 302,
      headers: { Location: target, 'Cache-Control': 'private, no-store', Vary: 'Cookie, Accept-Language' },
    });
  } catch (e) {
    return next();
  }
}

// a HEAD request gets the same answer as GET (Pages would otherwise serve the static page)
export const onRequestHead = onRequestGet;
