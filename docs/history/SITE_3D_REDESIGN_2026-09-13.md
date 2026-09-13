# Next session, hands-free: finish the 3D landing-page redesign

Written 2026-09-13 at the end of the session that started the redesign. Read this whole file
before touching anything. It is self-contained: the previous conversation is not available.

> **State right now:** the redesign is **work in progress and uncommitted** in `site/`.
> Production (`https://whisper-transcriber-suite.online`, Cloudflare Pages building `site/`
> from `master`, no build step) still serves the previous version. `master` is clean apart
> from these WIP files plus this document and a banner at the top of `docs/SESSION_HANDOFF_NEXT.md`.

---

## 0. Rules for this run

1. **Never commit `site/` WIP to `master` and never push anything that contains it until the
   owner has seen the finished page and explicitly said to publish.** Every push to `master`
   redeploys `site/` to production within minutes.
2. **No commits and no pushes without the owner's explicit confirmation** (standing instruction
   for this work, 2026-09-13) — this overrides the repo `CLAUDE.md` "commit + push immediately"
   cadence for the redesign. Keep everything uncommitted in the working tree, and when doing any
   unrelated commit on `master`, stage explicit paths only and check `git diff --cached --stat`
   so no `site/` file slips in. If the owner confirms local commits, move the WIP to a local
   branch first (never push it: any pushed branch makes Cloudflare Pages build a public preview):
   ```
   git switch -c site-3d-redesign
   git add site docs/NEXT_SESSION_HANDS_FREE.md
   git diff --cached --stat
   git commit -m "WIP: 3D landing-page redesign (not for master yet)"
   ```
3. Pre-authorised for this run: editing `site/**` and this file, local HTTP servers, headless
   Chrome and Claude-in-Chrome captures.
   Not pre-authorised: any commit, pushing any branch, merging into `master`, touching releases,
   tags, GitHub settings or secrets.
4. `site/` is public. Never put infrastructure details, hostnames, IPs, credentials, local
   machine paths or personal data into it.
5. Repo content stays English. Conversation with the owner is Persian (see the global
   `CLAUDE.md` language rules). Subagents: `sonnet`, at most one running at a time.
6. No third-party runtime requests from the page (fonts, three.js and images are self-hosted on
   purpose; the old shields.io badges were removed). Keep it that way.

---

## 1. Owner intent (2026-09-13)

- Critique the existing landing page using the **web-design-engineer** skill from
  `https://github.com/ConardLi/garden-skills`. The owner scored the old page **4/10**: "very
  ordinary".
- Build a striking, polished, professional **3D landing page** with an exceptional first
  impression — explicitly not "something normal".
- Allowed to borrow from a real, similar 3D example or from other repositories if that is what
  it takes to improve the site dramatically.
- "The app has a logo — why wasn't it used?" → the real app logo must be used everywhere.

## 2. Critique of the previous page (skill rubric, landing-page weighting)

Overall ~4.5/10. Philosophy 6 (a faithful generic Linear-recipe execution with no brand of its
own), hierarchy 5 (h1 broke into four ragged lines, small tilted screenshot, flat identical
sections), craft 5 (7 feature cards in a 3-column grid left one orphan; screenshots showed the
old name "Whisper Project v1.5.0"; favicon glyph differed from the logo; Buy Me a Coffee link was
a `TODO` placeholder), functionality 6 (honest copy, good SEO/GEO, but no demonstration of the
core value), originality 2 (no brand moment, logo unused).
Kept from it: all real copy, the FAQ text and FAQPage JSON-LD, meta/OG/canonical tags, anchors,
`llms.txt`, `robots.txt`, `sitemap.xml`, skip link, reduced-motion support.

## 3. What exists now (WIP inventory)

| Path | What it is |
|---|---|
| `site/index.html` | Rewritten page. Same `<title>`, description, keywords, canonical, OG/Twitter tags (+ `og:image:width/height/alt`), same three JSON-LD blocks (SoftwareApplication gained `image` + `screenshot`). Anchors preserved: `#top #main #features #screenshots #how-it-works #download #faq #support`. Import map for three.js lives in `<head>` before the `modulepreload`. |
| `site/styles.css` | New design system (tokens at the top), self-hosted `@font-face`, all sections, responsive breakpoints 1100 / 820 / 620 / 420 px, reduced-motion overrides. |
| `site/js/main.js` | Header glass + nav scroll-spy, OS-aware primary CTA + "Recommended for you" download card, staggered scroll reveals, `data-live` gating of feature animations, bento cursor spotlight, live-caption typer, deterministic denoise waveforms, product-tour tabs (ARIA tablist, keyboard, autoplay with progress bar, 3D tilt). |
| `site/js/hero3d.js` | The WebGL hero (three.js r186). See section 4. Supports `?still=<seconds>` for deterministic single-frame captures. |
| `site/assets/logo.svg` | Exact vector twin of `assets/make_icon.py` (verified side by side against the official PNG). Used for favicon, header, footer, poster fallback, tour window. |
| `site/assets/favicon-32.png`, `apple-touch-icon.png`, `logo-512.png` | Rendered by calling `make_icon._draw_icon(size)` directly — the official drawing code. |
| `site/assets/shots/*.webp` | The five real app screenshots from `docs/img/raw-screenshot-*.png`, cropped below the stale "Whisper Project v1.5.0" title bar and menu bar, lossless WebP (6–16 KB each). The page frames them in a window chrome titled "Whisper Transcriber Suite" (the app's real title is `Whisper Transcriber Suite v<version>`, `app/app.py`). |
| `site/assets/fonts/*.woff2` | Sora (display, 400–700), Geist (body, 300–700), Geist Mono (400–600); latin + latin-ext, variable. |
| `site/assets/vendor/three/` | `three.module.min.js` (jsDelivr-minified r186, imports `./three.core.js`), `three.core.js` (minified core, renamed so that import resolves), `addons/environments/RoomEnvironment.js`, `LICENSE` (MIT). |

Unreferenced leftovers still in `site/assets/`: `features.png`, `hero.png`, `how-it-works.png`,
`screenshot-*.png` (nothing in `site/` references them any more; `social-preview.png` IS still
referenced by the OG tags and must be regenerated, see T6).

## 4. Design decisions (keep unless there is a strong reason)

```yaml
Design Read:
  artifact: single-page product landing page (static, Cloudflare Pages)
  audience: people who transcribe audio/video (journalists, researchers, podcasters, subtitlers, developers); privacy-conscious; global
  visual-language: one cinematic WebGL set piece (Active Theory recipe) on a restrained builder-tool body (Linear recipe)
  mode: redesign-overhaul (content, SEO/GEO contracts, anchors, logo and brand teal preserved)
  visual-variance: 8
  motion-intensity: 8 in the hero, 4 elsewhere
  information-density: 4
  asset-dependence: 7 (real logo, real screenshots)
  brand-fidelity: 7
```

- **Palette:** ground `#04090a`, surfaces `#071011 / #0b1617 / #112021`, hairlines
  `rgb(180 255 244 / .075–.14)`, text `#eef6f5 / #a2b5b3 / #6a807e`, brand teal `#207a80` (exact
  logo colour), luminous twin `#4ae2d2` for accents/CTA, coffee button `#ffdd00` only.
- **Type:** Sora 600 display with tight tracking (h1 up to 7.6rem, −0.052em); Geist body; Geist
  Mono for chips/timestamps. Inter was dropped on purpose (skill: generic display face).
- **Radius grammar:** panels 22px, controls 12px, chips pill. **Motion:** `cubic-bezier(.16,1,.3,1)`
  reveals, CSS-only hero entry (works without JS), scroll reveals only when `.js` is set.
- **Hero copy:** h1 "Sound in. / Text out. / Nothing leaves your machine." (third line smaller,
  gradient), lede keeps the real engine names, OS-aware CTA, proof strip `14 formats · 3 local
  engines · 0 uploads by default · $0`. All claims are true per README/FAQ.
- **Hero scene (`hero3d.js`):** the app icon built in 3D from the exact `make_icon.py`
  coordinates (extruded rounded tile, `MeshPhysicalMaterial` with clearcoat, W from cylinders +
  round joint spheres, three partial tori for the arcs) is the machine. A particle waveform
  (per-column deterministic speech envelope `speechEnvelope()`, 260×38 points desktop / 170×22
  coarse pointer) flows in from the lower right into the sound arcs; the arcs and a halo pulse
  with the amplitude arriving at the icon; SRT cue cards (canvas textures, typed-in reveal
  shader, increasing cue numbers and timestamps) rise from the icon's top. Neutral tone mapping +
  `RoomEnvironment`. Framing presets in `layout()`: wide (tile at NDC x≈0.30), medium aspect,
  portrait (tile top-centre, rig scaled). Pointer parallax, click the tile for a burst, scroll
  dolly + canvas fade (`--hero-fade`), IntersectionObserver + visibility pause, adaptive quality
  (drops DPR and particle draw range after sustained slow frames), WebGL2 check with a CSS/logo
  poster fallback, `webglcontextlost` fallback, reduced-motion renders one composed still.
- **Sections:** features as a 12-column bento with small live visuals (engine picker, format
  chips, live bars + typer, speaker rows with per-word highlight, queue bars, download→transcribe
  steps, before/after denoise sweep); product tour; 3-step "Private by architecture" pipeline;
  four download cards (Windows installer, portable ZIP, macOS DMG, source with the real 4-line
  build snippet); two-column FAQ with animated `details`; support card with the real Buy Me a
  Coffee URL `https://buymeacoffee.com/mehraz1358`.
- **Avoided on purpose (skill failure patterns):** eyebrow label above every section heading
  (added then removed), fabricated stats/testimonials, emoji icons, purple gradients, star-count
  display while the count is tiny, third-party requests.

## 5. Known issues and gaps

1. **Cue cards do not show in `?still=5.5` / `?still=11` captures.** Leading hypothesis: cues
   spawn only when the amplitude at the icon crosses 0.42 upward (plus a 2.2 s gap), and the
   3-tap smoothing keeps amplitude above 0.42 inside a phrase, so crossings happen only at phrase
   onsets (every ~3–7 s) — the stack is mostly empty. Fix direction: keep onset-triggered spawns
   (≥1.2 s apart) and add a cadence fallback (spawn every ~2.4 s while amplitude > ~0.2), then
   confirm three cards are visible at several `still` times. Also re-check card order/age: one
   live capture showed cue 1 typing at the bottom and cue 3 fully typed at the top, which does
   not match spawn order — instrument with a temporary `?debug` overlay (slot index, birth, age,
   text) before trusting any theory.
2. **`requestAnimationFrame` does not tick in the Claude-in-Chrome tab when the Chrome window is
   not in the foreground**, so live screenshots show frozen early frames (a JS probe waiting on
   rAF timed out after 45 s). Use `?still=<t>` or headless Chrome with a virtual time budget
   (section 7) for evidence.
3. Not verified yet: tablet/phone layouts (portrait framing preset especially), every section
   below the hero, reduced-motion path, keyboard path through the tour tabs/FAQ, WebGL fallback
   poster, adaptive-quality path, no horizontal overflow at 390 px.
4. `site/assets/social-preview.png` still shows the old "WHISPER PROJECT" branding.
5. `site/_headers` marks all `/assets/*` as `immutable` for 7 days although nothing is
   fingerprinted (a changed `logo.svg`/`shots/*` could stay cached for a week); `/js/*` has no
   rule.
6. `THIRD_PARTY_NOTICES.md` does not yet list three.js (MIT), Sora, Geist, Geist Mono (SIL OFL
   1.1); the font files ship without `OFL.txt`.
7. `--text-3` (`#6a807e` on `#04090a`) is borderline for small text contrast — measure it.
8. macOS card copy is deliberately vague: the latest release only carries
   `WhisperProject-v1.5.0-macOS-x64.dmg`. Do not claim arm64 builds. Never build macOS (repo
   `CLAUDE.md`).

## 6. Task list (in order)

- **T1 Safety** — section 0, rule 2: confirm the WIP is still intact (`git status --short site`
  matches section 3) and nothing of it is staged. Commit only if the owner has confirmed.
- **T2 Reload the skill** — `git clone --depth 1 https://github.com/ConardLi/garden-skills.git`
  into this session's scratchpad; read `skills/web-design-engineer/SKILL.md` and
  `references/critique-guide.md`, `failure-patterns.md`, `redesign-protocol.md`,
  `browser-acceptance.md`, `style-recipes/active-theory.md`, `style-recipes/linear.md`.
- **T3 Fix the cue timeline** (issue 1). *Done when* `?still=` captures at 4, 8, 12, 20 s each
  show 2–3 legible, non-overlapping cards below the header, typed text matching its cue number.
- **T4 Hero art direction pass** at 1440×900 and 1280×720: waveform reads clearly as audio bars,
  tile colour stays brand teal, cards never touch the header or the copy column, proof strip
  fully visible above the fold. Compare against the skill's "stunning, not functional" bar.
- **T5 Responsive + section QA** at 390×844, 768×1024, 1280×720, 1440×900 (skill
  `browser-acceptance.md` viewports): hero portrait framing, bento stacking, tour tabs wrapping,
  download cards, FAQ, support, footer; no horizontal scroll; tap targets ≥ 44 px.
- **T6 Social card:** regenerate `site/assets/social-preview.png` at 1200×630 from the new hero
  (headless capture of `?still=<good t>`; hide the header for the capture if needed). Keep the
  same path so the existing OG tags stay valid.
- **T7 Cleanup:** delete the unreferenced old PNGs listed in section 3 after re-grepping `site/`
  (including `llms.txt`, `_headers`, `sitemap.xml`) for references.
- **T8 `_headers`:** short cache (e.g. `max-age=3600`) for `/js/*`, `/assets/logo.svg`,
  `/assets/shots/*`; long `immutable` only for `/assets/vendor/*` and `/assets/fonts/*`.
- **T9 Licences:** add three.js + the three font families to `THIRD_PARTY_NOTICES.md`; add
  `site/assets/fonts/OFL.txt` (fetch the official text from the font projects).
- **T10 Accessibility + performance:** contrast check of all text tokens; keyboard walk; reduced
  motion; confirm the hero text renders before three.js loads; consider skipping WebGL when
  `navigator.connection.saveData` is on.
- **T11 Self-critique** with the skill rubric (landing-page weighting). Target ≥ 8.5/10; fix the
  top issues it finds.
- **T12 Owner-approval gate** (section 8). Stop there.

## 7. How to run and capture

```
cd site
python -m http.server 8787 --bind 127.0.0.1
```
Pages: `http://127.0.0.1:8787/` (live), `http://127.0.0.1:8787/?still=12` (deterministic frame).

Headless Chrome with virtual time (rAF and timers advance without a visible window):
```
"C:\Program Files\Google\Chrome\Application\chrome.exe" --headless=new --hide-scrollbars --window-size=1440,900 --virtual-time-budget=9000 --screenshot=<scratchpad>\hero-1440.png http://127.0.0.1:8787/?still=12
```
If the WebGL context fails in headless mode, retry with
`--use-angle=swiftshader --enable-unsafe-swiftshader`. Check a screenshot before trusting a run.

Claude-in-Chrome: fine for layout, console (`read_console_messages`) and interaction checks;
not for judging animation (issue 2). Close every tab you open.

Stop background servers before ending the session.

## 8. Owner-approval gate (end of the run)

Deliver to the owner, in Persian: the new critique score, 3–5 screenshots (desktop hero, a
mid-page section, phone hero), what changed, and anything still weak. Ask whether to publish.

Only after an explicit yes:
1. Stage the redesign on `master` with explicit paths (`site`, plus `THIRD_PARTY_NOTICES.md` and
   the handoff banner removal), or, if a `site-3d-redesign` branch was used, merge it
   (`git merge --ff-only site-3d-redesign` by default).
2. `git diff --cached --stat` / `git log -1 --stat` — confirm only intended files.
3. Push `master` (pre-authorised by the repo `CLAUDE.md` once the owner has approved the page).
4. Watch the Cloudflare Pages deploy, then verify the live domain with a real load (console
   clean, hero renders, links work). If the domain misbehaves right after deploy, see the
   Cloudflare Pages memory note about stale local DNS before assuming breakage.
5. Update memory + `docs/SESSION_HANDOFF_NEXT.md` (remove the WIP banner), delete this file.

## 9. Restart prompt

```
Open C:\Users\Owner\Desktop\whisper_app\whisper_project_direct_download_v2, read docs/NEXT_SESSION_HANDS_FREE.md completely, and execute it hands-free from T1 through T11. Work locally only: do not commit, push or merge anything, and stop at the owner-approval gate in section 8.
```
