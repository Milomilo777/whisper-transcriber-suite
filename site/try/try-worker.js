// Runs Whisper inside the browser (transformers.js, ONNX Runtime WebAssembly) for /try/.
// transformers.js is loaded at an exact version from jsDelivr (npm releases there never change); a copy in
// the repository was refused by GitHub's secret scanning (a model class name looks like an API key).
// The audio arrives as samples from try.js and never leaves this worker: the only network traffic is the
// model download (Hugging Face) and the ONNX Runtime engine files (jsDelivr), both cached by the browser.
// Loaded with import(): a static cross-origin import in a module worker failed in Chrome (no error text).
const LIBRARY = 'https://cdn.jsdelivr.net/npm/@huggingface/transformers@4.3.1/dist/transformers.min.js';
let lib = null;

async function library() {
  if (!lib) {
    lib = await import(LIBRARY);
    lib.env.allowLocalModels = false;
    lib.env.useBrowserCache = true;
  }
  return lib;
}

// 'base-persian': Whisper Base fine-tuned for Persian (C1Tech/whisper_base_persian, Apache-2.0; its card reports
// it beats Whisper large-v3 on Persian), in the ONNX export made for Transformers.js. try.js picks it for Persian.
const MODELS = {
  tiny: 'onnx-community/whisper-tiny',
  base: 'onnx-community/whisper-base',
  'base-persian': 'armantee/whisper-base-persian-onnx',
};
// The Persian fine-tune lost Whisper's timestamp tokens: asked for timestamps it returns no text at all.
// It runs window by window instead, and each window becomes one timed chunk.
const NO_TIMESTAMPS = new Set(['base-persian']);
const SR = 16000;
const WINDOW = 30 * SR;
// Small models fall into loops on hard audio (one word repeated 150 times on a phone call):
// never repeat the same 4 tokens inside one 30-second window.
const NO_REPEAT = 4;

async function byWindow(audio, language) {
  const chunks = [];
  for (let i = 0; i < audio.length; i += WINDOW) {
    const piece = audio.subarray(i, i + WINDOW);
    if (piece.length < SR / 2) continue;  // a last scrap under half a second
    const out = await asr(piece, { language, task: 'transcribe', no_repeat_ngram_size: NO_REPEAT });
    const text = (out.text || '').trim();
    if (text) chunks.push({ timestamp: [i / SR, (i + piece.length) / SR], text });
  }
  return { text: chunks.map((c) => c.text).join(' '), chunks };
}
let asr = null;
let loaded = '';

self.onmessage = async (event) => {
  const msg = event.data || {};
  if (msg.type !== 'run') return;
  try {
    const id = MODELS[msg.model];
    if (!id) throw new Error('Unknown model');
    if (!asr || loaded !== id) {
      asr = null;
      const { pipeline } = await library();
      asr = await pipeline('automatic-speech-recognition', id, {
        device: 'wasm',
        dtype: 'q8',
        progress_callback: (p) => {
          if (p && p.status === 'progress' && typeof p.loaded === 'number' && typeof p.total === 'number') {
            self.postMessage({ type: 'download', file: p.file, loaded: p.loaded, total: p.total });
          }
        },
      });
      loaded = id;
    }
    self.postMessage({ type: 'transcribing' });
    const out = NO_TIMESTAMPS.has(msg.model) ? await byWindow(msg.audio, msg.language || null) : await asr(msg.audio, {
      language: msg.language || null,
      task: 'transcribe',
      chunk_length_s: 30,
      stride_length_s: 5,
      return_timestamps: true,
      no_repeat_ngram_size: NO_REPEAT,
    });
    self.postMessage({ type: 'done', text: out.text || '', chunks: out.chunks || [] });
  } catch (err) {
    self.postMessage({ type: 'error', message: String((err && err.message) || err) });
  }
};
