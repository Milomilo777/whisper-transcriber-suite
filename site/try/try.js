// /try/: pick a file, decode it to 16 kHz mono here, and let try-worker.js transcribe it in the browser.
// Privacy rule (tested by the site tests): this file makes no network request; the audio only goes to the worker.
import { cues, splitLong, toSrt, toVtt } from './try-format.js?v=20261020a';

const card = document.querySelector('[data-try]');
const fileInput = document.querySelector('[data-file]');
const drop = document.querySelector('[data-drop]');
const fileInfo = document.querySelector('[data-file-info]');
const runBtn = document.querySelector('[data-run]');
const langSel = document.querySelector('[data-language]');
const progressBox = document.querySelector('[data-progress]');
const bar = document.querySelector('[data-bar]');
const statusLine = document.querySelector('[data-status]');
const errorBox = document.querySelector('[data-error]');
const resultBox = document.querySelector('[data-result]');
const textOut = document.querySelector('[data-text]');
const netWarn = document.querySelector('[data-net-warn]');
const modelInfo = document.querySelector('[data-model-info]');
const langNote = document.querySelector('[data-lang-note]');
const awakeNote = document.querySelector('[data-awake]');
const baseSize = document.querySelector('[data-base-size]');

const SIZES = { tiny: '41 MB', base: '77 MB', 'base-persian': '105 MB' };
const MODEL_IDS = {
  tiny: 'onnx-community/whisper-tiny',
  base: 'onnx-community/whisper-base',
  'base-persian': 'armantee/whisper-base-persian-onnx',
};
// Languages the small browser models get badly wrong: say so, and point to the desktop app.
const WEAK = { persian: 'Persian', arabic: 'Arabic', hindi: 'Hindi', korean: 'Korean', turkish: 'Turkish',
  vietnamese: 'Vietnamese' };
const PHONE = window.matchMedia('(pointer: coarse)').matches;
const MAX_SECONDS = (PHONE ? 5 : 10) * 60;

let file = null;
let duration = 0;
let chunks = [];
let worker = null;
let busy = false;
let started = 0;
let tick = 0;
let wakeLock = null;
let hiddenAt = 0;

function show(el, on) { el.hidden = !on; }
function setError(text) { errorBox.textContent = text; show(errorBox, Boolean(text)); }
function model() {
  // Persian gets the Persian-trained Base model; Tiny stays the generic one.
  const m = document.querySelector('input[name="model"]:checked').value;
  return m === 'base' && langSel.value === 'persian' ? 'base-persian' : m;
}

// Phones pause a page whose screen turns off, and the transcription with it: keep the screen on while it runs.
async function keepAwake() {
  if (!busy || wakeLock || !('wakeLock' in navigator) || document.hidden) return;
  try {
    wakeLock = await navigator.wakeLock.request('screen');
    wakeLock.addEventListener('release', () => { wakeLock = null; });
  } catch (e) { /* refused (battery saver): the note still asks to keep the page open */ }
}

function letSleep() {
  if (wakeLock) wakeLock.release().catch(() => {});
  wakeLock = null;
}

function onVisibility() {
  if (!busy) return;
  if (document.hidden) {
    hiddenAt = Date.now();
    return;
  }
  keepAwake();  // the browser drops the lock when the page is hidden
  if (hiddenAt) {
    awakeNote.textContent = `This page was in the background for ${minutes((Date.now() - hiddenAt) / 1000)}. `
      + 'A phone may pause a page in the background; the transcription goes on now. Keep this page open until it finishes.';
    hiddenAt = 0;
  }
}

function languageNote() {
  const name = WEAK[langSel.value];
  const persian = model() === 'base-persian';
  baseSize.textContent = persian ? SIZES['base-persian'] : SIZES.base;
  let text = '';
  if (persian) {
    text = 'Persian uses a Base model trained for Persian (Apache-2.0, by C1Tech). Phone calls and noisy audio are still '
      + 'hard for a small model in the browser; the free desktop app is far more accurate.';
  } else if (langSel.value === 'persian') {
    text = 'Tiny is the general model and gets Persian badly wrong. Pick Base: for Persian it is a model trained for Persian.';
  } else if (name) {
    text = `The small models that fit in a browser make many mistakes in ${name}. For real work, use the free desktop `
      + 'app with a large model.';
  }
  langNote.textContent = text;
  show(langNote, Boolean(text));
}
function minutes(sec) { return `${Math.floor(sec / 60)}:${String(Math.round(sec % 60)).padStart(2, '0')}`; }

function mediaDuration(f) {
  // Read the length from the file's header via a media element, before decoding the whole file.
  return new Promise((resolve) => {
    const el = document.createElement(f.type.startsWith('video') ? 'video' : 'audio');
    const url = URL.createObjectURL(f);
    el.preload = 'metadata';
    el.onloadedmetadata = () => { URL.revokeObjectURL(url); resolve(el.duration); };
    el.onerror = () => { URL.revokeObjectURL(url); resolve(NaN); };
    el.src = url;
  });
}

async function pick(f) {
  setError('');
  show(resultBox, false);
  file = null;
  runBtn.disabled = true;
  if (!f) return;
  const d = await mediaDuration(f);
  if (Number.isFinite(d) && d > MAX_SECONDS) {
    fileInfo.textContent = '';
    setError(`This file is ${minutes(d)} long. The browser version stops at ${MAX_SECONDS / 60} minutes; the free desktop app transcribes files of any length.`);
    return;
  }
  file = f;
  duration = Number.isFinite(d) ? d : 0;
  fileInfo.textContent = `${f.name}${duration ? ` (${minutes(duration)})` : ''}`;
  runBtn.disabled = busy;
}

async function decode(f) {
  const ctx = new AudioContext({ sampleRate: 16000 });
  try {
    const buf = await ctx.decodeAudioData(await f.arrayBuffer());
    if (buf.duration > MAX_SECONDS + 1) throw new Error('too long');
    const out = new Float32Array(buf.length);
    for (let c = 0; c < buf.numberOfChannels; c++) {
      const ch = buf.getChannelData(c);
      for (let i = 0; i < ch.length; i++) out[i] += ch[i] / buf.numberOfChannels;
    }
    return out;
  } finally {
    ctx.close();
  }
}

function save(kind) {
  const base = (file ? file.name.replace(/\.[^.]+$/, '') : 'transcript') || 'transcript';
  const body = kind === 'srt' ? toSrt(splitLong(cues(chunks, duration))) : kind === 'vtt' ? toVtt(splitLong(cues(chunks, duration))) : textOut.value + '\n';
  const type = kind === 'vtt' ? 'text/vtt' : kind === 'srt' ? 'application/x-subrip' : 'text/plain';
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([body], { type: `${type};charset=utf-8` }));
  a.download = `${base}.${kind}`;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

function finish() {
  busy = false;
  hiddenAt = 0;
  letSleep();
  clearInterval(tick);
  runBtn.disabled = !file;
}

const files = new Map();  // model file -> [loaded, total]: the download progress over all files

function onMessage(event) {
  const m = event.data || {};
  if (m.type === 'download') {
    show(progressBox, true);
    files.set(m.file, [m.loaded, m.total]);
    let loaded = 0, total = 0;
    files.forEach(([l, t]) => { loaded += l; total += t; });
    bar.max = total;
    bar.value = loaded;
    statusLine.textContent = `Downloading the speech model: ${Math.round(loaded / 1048576)} of ${Math.round(total / 1048576)} MB`;
  } else if (m.type === 'transcribing') {
    bar.removeAttribute('value');
    started = Date.now();
    const say = () => { statusLine.textContent = `Transcribing in this browser… ${minutes((Date.now() - started) / 1000)} so far (it can take about as long as the audio, or longer on a phone).`; };
    say();
    clearInterval(tick);
    tick = setInterval(say, 1000);
  } else if (m.type === 'done') {
    chunks = m.chunks;
    textOut.value = (m.text || '').trim();
    show(resultBox, true);
    show(progressBox, false);
    statusLine.textContent = '';
    finish();
    if (!textOut.value) setError('No speech was found in this file.');
  } else if (m.type === 'error') {
    show(progressBox, false);
    statusLine.textContent = '';
    setError(`It did not work in this browser: ${m.message}. The desktop app handles this file.`);
    finish();
  }
}

async function run() {
  if (!file || busy) return;
  busy = true;
  runBtn.disabled = true;
  setError('');
  show(resultBox, false);
  show(progressBox, true);
  awakeNote.textContent = 'wakeLock' in navigator
    ? 'The screen stays on while this runs. Keep this page open until it finishes.'
    : 'Keep this page open and the screen on until it finishes: a phone pauses pages in the background.';
  keepAwake();
  bar.removeAttribute('value');
  statusLine.textContent = 'Reading the file…';
  let audio;
  try {
    audio = await decode(file);
  } catch (e) {
    show(progressBox, false);
    setError('This browser cannot read the sound of this file. Try an MP3, WAV or M4A, or the desktop app.');
    finish();
    return;
  }
  if (!worker) {
    worker = new Worker(new URL('./try-worker.js?v=20261020b', import.meta.url), { type: 'module' });
    worker.onmessage = onMessage;
    worker.onerror = (e) => onMessage({ data: { type: 'error', message: e.message || 'the worker stopped' } });
  }
  statusLine.textContent = 'Preparing the speech model…';
  worker.postMessage({ type: 'run', model: model(), language: langSel.value, audio }, [audio.buffer]);
}

async function cacheNote() {
  const m = model();
  let cached = false;
  try {
    const cache = await caches.open('transformers-cache');
    cached = (await cache.keys()).some((r) => r.url.includes(MODEL_IDS[m]));
  } catch (e) { /* no Cache API: say nothing about the cache */ }
  modelInfo.textContent = cached
    ? 'This model is already in this browser: no download needed.'
    : `The model (${SIZES[m]}) is downloaded once from Hugging Face when you press Transcribe, then kept in this browser.`;
}

function init() {
  if (!card || typeof WebAssembly !== 'object' || !window.Worker || !window.AudioContext) {
    if (card) {
      card.hidden = false;
      card.innerHTML = '<p class="try-err">This browser cannot run the speech model. Try a current Chrome, Edge, Firefox or Safari, or the free desktop app.</p>';
    }
    return;
  }
  card.hidden = false;
  // Whisper in the browser does not detect the language: start from the browser's own language.
  const want = (navigator.language || 'en').slice(0, 2).toLowerCase();
  const names = { en: 'english', ar: 'arabic', zh: 'chinese', fr: 'french', de: 'german', hi: 'hindi', id: 'indonesian',
    it: 'italian', ja: 'japanese', ko: 'korean', fa: 'persian', pt: 'portuguese', ru: 'russian', es: 'spanish',
    tr: 'turkish', vi: 'vietnamese' };
  if (names[want]) langSel.value = names[want];
  const c = navigator.connection;
  show(netWarn, Boolean(c && (c.saveData || c.type === 'cellular' || /(^|-)2g|3g/.test(c.effectiveType || ''))));
  fileInput.addEventListener('change', () => pick(fileInput.files[0]));
  drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', (e) => {
    e.preventDefault();
    drop.classList.remove('over');
    if (e.dataTransfer.files[0]) pick(e.dataTransfer.files[0]);
  });
  document.querySelectorAll('input[name="model"]').forEach((r) => r.addEventListener('change', () => {
    languageNote();
    cacheNote();
  }));
  langSel.addEventListener('change', () => { languageNote(); cacheNote(); });
  document.addEventListener('visibilitychange', onVisibility);
  languageNote();
  runBtn.addEventListener('click', run);
  document.querySelectorAll('[data-save]').forEach((b) => b.addEventListener('click', () => save(b.dataset.save)));
  document.querySelector('[data-copy]').addEventListener('click', () => navigator.clipboard && navigator.clipboard.writeText(textOut.value));
  cacheNote();
}

init();
