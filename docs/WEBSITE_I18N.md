# The website in other languages

The website (`site/`) is written in English. `tools/site_i18n.py` builds a copy of each page in
every interface language of the app under `site/<lang>/` (for example `site/de/`, `site/pt-br/`),
from a translation catalog per language in `site-i18n/<lang>.json`. Why it works this way:
[ADR 0013](DECISIONS.md).

## How it works

- **Segments.** The English pages are cut into segments: the text of each block (a heading, a
  paragraph, a button label), translatable attributes (`alt`, `title`, `aria-label`, the meta
  descriptions), FAQ and article text in the JSON-LD blocks, and the strings `js/main.js` writes
  (`<script id="i18n-strings">`). Inline tags inside a block become numbered placeholders:
  `Click <1>Star</1> at the top <2/>` keeps the link and the icon. Elements marked
  `translate="no"`, `data-auto` (release facts) or `data-i18n-skip`, and `<code>`, stay as they are.
- **Catalogs.** `site-i18n/<lang>.json` maps the first 16 hex digits of the SHA-256 of an English
  segment to `{"src": English, "tr": translation, "by": who translated it, "rev": who reviewed it}`.
  When an English sentence changes, only that sentence needs a new translation; until then it
  shows in English on the translated page.
- **Publishing.** A language is built only when its catalog covers at least 90 % of the segments
  (`PUBLISH_SHARE`); once its folder exists it stays published until it drops below 50 %
  (`KEEP_SHARE`), so an English edit cannot orphan its pages. `SITE_I18N_ONLY=fa,de` limits a build
  to those languages. The build also writes the language menu, the `hreflang` links, the sitemap
  entries and the list of published languages in `site/functions/index.js`, for English too.
- **First visit.** `site/functions/index.js` answers requests for `/`: it sends a visitor to their
  language by country (see the comment at the top of the file); `js/lang.js` remembers a language
  picked in the menu and shows the "this page is in your language" note.

## Commands

```bash
python tools/site_i18n.py status             # segments and words; translated share per language
python tools/site_i18n.py export de de.json   # the German segments that still need a translation
python tools/site_i18n.py import de de.json --by "your name"   # merge them (validated)
python tools/site_i18n.py build              # write site/<lang>/…, menus, hreflang, sitemap
python tools/site_i18n.py check              # exit 1 if a built file is stale (also a test)
python tools/site_country_lang.py            # regenerate the country table (needs babel==2.18.0)
```

`import` refuses a translation whose placeholders differ from the English segment, are not
properly nested, or that contains raw HTML, and lists the refused keys.

## Correcting a translation

Edit the `"tr"` value in `site-i18n/<lang>.json` (keep every `<n>`, `</n>` and `<n/>` exactly once),
run `python tools/site_i18n.py build`, and commit both the catalog and the built pages. Or open an
issue with the page address and the better wording.

## Changing the English pages

Edit only the English files (`site/index.html` and the guide pages), then run
`python tools/site_i18n.py build`. Never edit a file under `site/<lang>/`: the next build overwrites
it. New text appears in English on the other pages until its segments are translated (`status`
shows how many are missing). A new page needs a row in `PAGES` in `tools/site_i18n.py`.

## Tests

`tests/test_site_i18n.py`: the built pages are current, the English build is unchanged, a
translation never changes the page structure (property test with random translations),
placeholder validation, URL handling, and the redirect rules (`node` needed for the last one).
