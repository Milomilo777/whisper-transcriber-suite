// Cloudflare Pages Function for "/" only: send a first-time visitor to the website in their language.
//
//   1. ?lang=en (the "View in English" link) -> remember English, show the English page.
//   2. A wts_lang cookie (set when someone picks a language in the menu) wins over everything else.
//   3. Search engines, link previews and scripts always get the English page, never a redirect.
//   4. Otherwise the visitor's country (request.cf.country) gives candidate languages
//      (COUNTRY_LANGS, from Unicode CLDR); the browser's Accept-Language picks among them, else the
//      first one. English, an unknown country or a language not yet published -> the English page.
//
// A redirect is a 302 to /<lang>/?auto=1 (the page then says why it is in that language) and is never
// cached, because it depends on the visitor. Every language page stays reachable at its own address
// for everyone, and nothing is stored on the server. Any error falls back to the English page.

const BOT_UA = /bot|crawl|spider|slurp|preview|headless|lighthouse|monitor|curl|wget|python|httpclient|facebookexternalhit|whatsapp|embedly|pinterest|vkshare|quora/i;
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
  const t = tag.toLowerCase();
  if (/^zh-(tw|hk|mo|hant)/.test(t)) return 'zh-TW';
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
      const q = params.map((p) => p.trim()).find((p) => p.startsWith('q='));
      return { tag: tag.trim(), q: q ? parseFloat(q.slice(2)) || 0 : 1, i };
    })
    .filter((x) => x.tag && x.tag !== '*' && x.q > 0)
    .sort((a, b) => b.q - a.q || a.i - b.i)
    .map((x) => siteCode(x.tag));
}

function cookieValue(header, name) {
  for (const part of (header || '').split(';')) {
    const [k, ...v] = part.trim().split('=');
    if (k === name) return decodeURIComponent(v.join('='));
  }
  return null;
}

// The language "/" should show: a published code, 'en' meaning the English page itself.
export function pickLanguage({ country, acceptLanguage, cookie, userAgent, published = PUBLISHED, table = COUNTRY_LANGS }) {
  if (cookie && published.includes(cookie)) return cookie;
  if (!userAgent || BOT_UA.test(userAgent)) return 'en';
  const candidates = (table[(country || '').toUpperCase()] || []).filter((c) => c === 'en' || published.includes(c));
  if (!candidates.length) return 'en';
  // a candidate pt-BR also matches a browser that only says "pt", and the other way round
  const loose = (c) => (c === 'pt-BR' ? 'pt' : c);
  for (const want of acceptLanguages(acceptLanguage)) {
    const hit = candidates.find((c) => c === want || loose(c) === loose(want));
    if (hit) return hit;
  }
  return candidates[0];
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
    const code = pickLanguage({
      country: request.cf && request.cf.country,
      acceptLanguage: request.headers.get('Accept-Language'),
      cookie: cookieValue(request.headers.get('Cookie'), COOKIE),
      userAgent: request.headers.get('User-Agent') || '',
    });
    if (code === 'en') return next();
    const fromCookie = cookieValue(request.headers.get('Cookie'), COOKIE) === code;
    const target = `/${code.toLowerCase()}/${fromCookie ? '' : '?auto=1'}`;
    return new Response(null, {
      status: 302,
      headers: { Location: target, 'Cache-Control': 'private, no-store', Vary: 'Cookie, Accept-Language' },
    });
  } catch (e) {
    return next();
  }
}
