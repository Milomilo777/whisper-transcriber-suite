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

const MODELS = { tiny: 'onnx-community/whisper-tiny', base: 'onnx-community/whisper-base' };
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
    const out = await asr(msg.audio, {
      language: msg.language || null,
      task: 'transcribe',
      chunk_length_s: 30,
      stride_length_s: 5,
      return_timestamps: true,
    });
    self.postMessage({ type: 'done', text: out.text || '', chunks: out.chunks || [] });
  } catch (err) {
    self.postMessage({ type: 'error', message: String((err && err.message) || err) });
  }
};
