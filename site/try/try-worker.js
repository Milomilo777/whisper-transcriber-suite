// Runs Whisper inside the browser (transformers.js, ONNX Runtime WebAssembly or WebGPU) for /try/.
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

// Small runs everywhere (WebAssembly). Large v3 Turbo runs on the graphics card (WebGPU), close to the desktop app's
// quality: on FLEURS the Whisper paper's large models make about half the word errors of Small in most languages.
// Tiny and Base were dropped (2026-10-26): too many mistakes in most languages (Base: 86 % WER in Persian).
const MODELS = {
  small: 'onnx-community/whisper-small',
  large: 'onnx-community/whisper-large-v3-turbo_timestamped',
};
// Large: a 4-bit encoder and decoder (about 730 MB) on every graphics card. The fp16 encoder needs shader-f16, which
// many laptop GPUs lack, and Transformers.js v4 loses most of the transcript with it (issue 1590); the fp32 encoder
// (2.5 GB) never finished loading on an integrated GPU (2026-10-26 test).
const OPTIONS = {
  small: { device: 'wasm', dtype: 'q8' },
  large: { device: 'webgpu', dtype: { encoder_model: 'q4', decoder_model_merged: 'q4' } },
};
// Whisper can fall into loops on hard audio (one word repeated 150 times on a phone call):
// never repeat the same 4 tokens inside one 30-second window.
const NO_REPEAT = 4;
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
      if (OPTIONS[msg.model].device === 'webgpu' && !(self.navigator.gpu && await self.navigator.gpu.requestAdapter())) {
        // the code lets the page show this in its own language
        throw Object.assign(new Error('this browser has no WebGPU, which the Large model needs. Pick Small'),
          { code: 'no-webgpu' });
      }
      asr = await pipeline('automatic-speech-recognition', id, {
        ...OPTIONS[msg.model],
        progress_callback: (p) => {
          if (p && p.status === 'progress' && typeof p.loaded === 'number' && typeof p.total === 'number') {
            self.postMessage({ type: 'download', file: p.file, loaded: p.loaded, total: p.total });
          }
        },
      });
      loaded = id;
    }
    self.postMessage({ type: 'transcribing' });
    const out = await asr(msg.audio, {
      language: msg.language || null,
      task: 'transcribe',
      chunk_length_s: 30,
      stride_length_s: 5,
      return_timestamps: true,
      no_repeat_ngram_size: NO_REPEAT,
    });
    self.postMessage({ type: 'done', text: out.text || '', chunks: out.chunks || [] });
  } catch (err) {
    self.postMessage({ type: 'error', code: (err && err.code) || '', message: String((err && err.message) || err) });
  }
};
