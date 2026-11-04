"""Windowless paired measurements through the app backend, with a frozen gate.

Run with a local model directory; no downloads are performed. Each measurement
uses a fresh process, warms the same file once, and records peak process RSS
(including model load/warm-up). GPU allocation is not measured by this tool.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import unicodedata
from typing import Any


def run_order(pairs: int) -> list[tuple[int, bool]]:
    return [(pair, setting) for pair in range(pairs)
            for setting in ((False, True) if pair % 2 == 0 else (True, False))]


def character_mode(text: str) -> bool:
    """Use CER for scripts whose words need language-specific segmentation."""
    return any(any(tag in unicodedata.name(c, '') for tag in
                   ('CJK', 'HIRAGANA', 'KATAKANA', 'THAI', 'KHMER', 'LAO', 'MYANMAR'))
               for c in text)


def normalise(text: str, chars: bool | None = None) -> list[str]:
    text = unicodedata.normalize('NFKC', text).casefold()
    if chars is None:
        chars = character_mode(text)
    text = ''.join(c if unicodedata.category(c)[0] in 'LNM' else
                   ('' if c in "'\u2019\u200c\u200d" else ' ') for c in text)
    return [c for c in text if not c.isspace()] if chars else text.split()


def edit_counts(reference: list[str], hypothesis: list[str]) -> dict[str, int]:
    """Exact Levenshtein S/D/I counts with an expanding diagonal band.

    Rolling rows bound memory. Equal-cost paths prefer substitution, deletion,
    then insertion. Common ends are removed before dynamic programming.
    """
    original_length = len(reference)
    start = 0
    while start < min(len(reference), len(hypothesis)) and reference[start] == hypothesis[start]:
        start += 1
    a, b = reference[start:], hypothesis[start:]
    end = 0
    while end < min(len(a), len(b)) and a[-end-1] == b[-end-1]:
        end += 1
    if end:
        a, b = a[:-end], b[:-end]
    n, m = len(a), len(b)
    band = max(abs(n-m), 8)
    missing = (n+m+1, 0, 0, 0)
    while True:
        prev = {j: (j, 0, 0, j) for j in range(min(m, band)+1)}
        for i in range(1, n+1):
            row = {0: (i, 0, i, 0)} if i <= band else {}
            for j in range(max(1, i-band), min(m, i+band)+1):
                cost, s, d, ins = prev.get(j-1, missing)
                change = int(a[i-1] != b[j-1])
                diagonal = (cost+change, s+change, d, ins)
                cost, s, d, ins = prev.get(j, missing)
                deletion = (cost+1, s, d+1, ins)
                cost, s, d, ins = row.get(j-1, missing)
                insertion = (cost+1, s, d, ins+1)
                row[j] = min((diagonal, deletion, insertion), key=lambda x: x[0])
            prev = row
        answer = prev.get(m, missing)
        if answer[0] <= band:
            return dict(substitutions=answer[1], deletions=answer[2],
                        insertions=answer[3], reference=original_length)
        band *= 2


def read_records(path: Path, *, repair_tail: bool = False) -> list[dict[str, Any]]:
    data = path.read_bytes()
    if data and not data.endswith(b'\n'):
        if not repair_tail:
            raise ValueError('incomplete final JSON line; resume run to repair it')
        end = data.rfind(b'\n') + 1
        print('Repairing incomplete final JSON line at byte ' + str(end), file=sys.stderr)
        with path.open('r+b') as stream:
            stream.truncate(end)
        data = data[:end]
    rows = []
    for number, line in enumerate(data.decode('utf-8-sig').splitlines(), 1):
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise ValueError(f'invalid JSON line {number}: {exc}') from exc
        if not isinstance(row, dict):
            raise ValueError(f'JSON line {number} is not an object')
        rows.append(row)
    return rows


def percentile95(values: list[float]) -> float:
    return sorted(values)[max(0, math.ceil(len(values)*.95)-1)] if values else 0.


def missing_spans(off: dict, on: dict, chars: bool) -> list[dict[str, Any]]:
    def tokens(row):
        labels, cues = [], []
        for cue in row['segments']:
            words = normalise(cue['text'], chars)
            labels.extend(words)
            cues.extend([cue] * len(words))
        return labels, cues
    a, ac = tokens(off)
    b, bc = tokens(on)
    spans = []
    for tag, i, j, k, l in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == 'equal':
            continue
        for labels, cues, lo, hi, missing in ((a, ac, i, j, 'on'), (b, bc, k, l, 'off')):
            if hi > lo:
                spans.append({'missing_from': missing, 'pair': off['pair'],
                              'start': cues[lo]['start'], 'end': cues[hi-1]['end'],
                              'text': ('' if chars else ' ').join(labels[lo:hi])})
    return spans


def score_records(records: list[dict[str, Any]], references: dict[str, str] | None = None) -> dict:
    references = references or {}
    reasons: list[str] = []
    result: dict[str, Any] = {'verdict': 'FAIL', 'reasons': reasons, 'clips': {}}
    headers = [r for r in records if r.get('type') == 'manifest']
    if len(headers) != 1:
        reasons.append('exactly one manifest is required')
        return result
    manifest = headers[0]
    files = [r['path'] for r in manifest['files']]
    pairs = manifest['options']['pairs']
    if (isinstance(pairs, bool) or not isinstance(pairs, int) or pairs < 1
            or not files or len(set(files)) != len(files)):
        reasons.append('invalid measurement manifest')
        return result
    expected = {(f, pair, setting) for f in files for pair, setting in run_order(pairs)}
    by_key = {}
    for row in records:
        if row.get('type') != 'run':
            continue
        key = (row.get('file'), row.get('pair'), row.get('setting'))
        if (key not in expected or key in by_key or not isinstance(row.get('setting'), bool)
                or row.get('manifest_id') != manifest['id']):
            reasons.append('duplicate, foreign or invalid measurement run')
            continue
        by_key[key] = row
        if (not isinstance(row.get('kwargs'), list) or not row['kwargs']
                or any(not isinstance(k, dict) or k.get('word_timestamps') is not row['setting']
                       for k in row['kwargs'])):
            reasons.append('effective word_timestamps does not match the measured setting')
    end = records[-1] if records else {}
    if (end.get('type') != 'end' or end.get('complete') is not True
            or end.get('expected_runs') != len(expected) or end.get('manifest_id') != manifest['id']
            or set(by_key) != expected):
        reasons.append('incomplete measurement or missing end marker')
    for file in files:
        clip: dict[str, Any] = {'accuracy': {}, 'cues': {}, 'spans': []}
        result['clips'][file] = clip
        rows = [r for key, r in by_key.items() if key[0] == file]
        if len(rows) != 2*pairs:
            continue
        reference = references.get(file)
        chars = character_mode(reference if reference is not None else
                               ' '.join(s['text'] for r in rows for s in r['segments']))
        clip['unit'] = 'CER' if chars else 'WER'
        ref = normalise(reference, chars) if reference is not None else []
        if not ref:
            reasons.append(file + ': reference missing or empty; accuracy is unverified')
        invalid = False
        for row in rows:
            numbers = [row.get('wall_seconds'), row.get('peak_memory_bytes')]
            if (any(isinstance(x, bool) or not isinstance(x, (int, float))
                    or not math.isfinite(x) or x <= 0 for x in numbers)
                    or not row.get('segments')):
                invalid = True
            for cue in row.get('segments', []):
                bounds = [cue.get('start'), cue.get('end')]
                if any(isinstance(x, bool) or not isinstance(x, (int, float))
                       or not math.isfinite(x) for x in bounds):
                    invalid = True
                elif bounds[0] < 0 or bounds[1] <= bounds[0]:
                    invalid = True
        if invalid:
            reasons.append(file + ': invalid resource measurement or cue bounds')
            continue
        for setting, name in ((False, 'off'), (True, 'on')):
            selected = [r for r in rows if r['setting'] is setting]
            durations = [s['end']-s['start'] for r in selected for s in r['segments']]
            cue_metrics = {'p95': percentile95(durations), 'max': max(durations),
                           'over_30': sum(d > 30 for d in durations), 'count': len(durations),
                           'text_units': [len(normalise(' '.join(s['text'] for s in r['segments']), chars))
                                          for r in selected]}
            clip['cues'][name] = cue_metrics
            if ref:
                counts = [edit_counts(ref, normalise(' '.join(s['text'] for s in r['segments']), chars))
                          for r in selected]
                total = {k: sum(c[k] for c in counts) for k in counts[0]}
                total['error_rate'] = 100*sum(total[k] for k in ('substitutions', 'deletions', 'insertions'))/total['reference']
                total['deletion_rate'] = 100*total['deletions']/total['reference']
                clip['accuracy'][name] = total
        on_cues = clip['cues']['on']
        # Apply accuracy and cue criteria to every pair, not just pooled results.
        ratios, memory = [], []
        for pair in range(pairs):
            off, on = by_key[file, pair, False], by_key[file, pair, True]
            if any(off.get(k) != on.get(k) for k in ('device', 'compute_type', 'versions')):
                reasons.append(f'{file} pair {pair}: effective engine/device differs between settings')
            ratios.append(on['wall_seconds']/off['wall_seconds'])
            memory.append(on['peak_memory_bytes']-off['peak_memory_bytes'])
            clip['spans'].extend(missing_spans(off, on, chars))
            ond = [s['end']-s['start'] for s in on['segments']]
            offd = [s['end']-s['start'] for s in off['segments']]
            if percentile95(ond) > 6.5 or percentile95(ond) > .8*percentile95(offd):
                reasons.append(f'{file} pair {pair}: cue p95 exceeds 6.5 s or lacks 20% improvement')
            if ref:
                oc = edit_counts(ref, normalise(' '.join(s['text'] for s in off['segments']), chars))
                nc = edit_counts(ref, normalise(' '.join(s['text'] for s in on['segments']), chars))
                error = lambda c: sum(c[k] for k in ('substitutions', 'deletions', 'insertions'))
                if 100*(error(nc)-error(oc))/len(ref) > .5 + 1e-9:
                    reasons.append(f'{file} pair {pair}: {clip["unit"]} increase exceeds 0.5 points')
                if 100*(nc['deletions']-oc['deletions'])/len(ref) > .25 + 1e-9:
                    reasons.append(f'{file} pair {pair}: deletion increase exceeds 0.25 points')
        if on_cues['max'] > 20 or on_cues['over_30']:
            reasons.append(file + ': cue maximum exceeds 20 s or cues exceed 30 s')
        clip['median_time_ratio'] = statistics.median(ratios)
        clip['extra_peak_memory_bytes'] = max(memory)
        clip['peak_memory_bytes'] = {name: max(r['peak_memory_bytes'] for r in rows if r['setting'] is setting)
                                     for setting, name in ((False, 'off'), (True, 'on'))}
        if clip['median_time_ratio'] > 1.20:
            reasons.append(file + ': median time ratio exceeds 1.20')
        if max(memory) > 256*2**20:
            reasons.append(file + ': extra peak memory exceeds 256 MiB')
    result['verdict'] = 'FAIL' if reasons else 'PASS'
    return result


def append_record(path: Path, record: dict) -> None:
    with path.open('a', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def peak_memory_bytes() -> int:
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
                    'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
                    'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(counters.PeakWorkingSetSize)
    import resource
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * (1 if sys.platform == 'darwin' else 1024)


def _one(spec: dict) -> dict:
    # Isolate app imports from the operator's profile. Never fetch online config.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import platformdirs
    profile = Path(spec['profile'])
    for kind in ('config', 'cache', 'data', 'state', 'log'):
        setattr(platformdirs, 'user_' + kind + '_dir',
                lambda *a, _kind=kind, **k: str(profile / _kind))
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['WHISPER_OFFLINE'] = '1'
    from core.backends.faster_whisper_be import FasterWhisperBackend
    from core.config import DEFAULT_CONFIG
    import faster_whisper
    import ctranslate2

    options = spec['options']
    backend = FasterWhisperBackend()
    backend._read_safeguards(DEFAULT_CONFIG)
    backend._device = backend._requested_device = options['device']
    backend._compute_type = options['compute_type']
    backend._load_self_healing(options['model_dir'], None)
    if options['batch_size'] > 1:
        backend._pipeline = backend._wrap_for_batched()
        if backend._pipeline is None:
            raise RuntimeError('batched measurement requires a working CUDA pipeline')
    backend._ready = True
    observations = []
    real_runner = backend._decode_runner
    class RecordingRunner:
        def __init__(self, runner):
            self.runner = runner
        def transcribe(self, audio, **kwargs):
            signature = inspect.signature(self.runner.transcribe)
            bound = signature.bind(audio, **kwargs)
            bound.apply_defaults()
            observations.append({k: v for k, v in bound.arguments.items() if k != 'audio'})
            return self.runner.transcribe(audio, **kwargs)
    def recording_runner(kwargs):
        return RecordingRunner(real_runner(kwargs))
    backend._decode_runner = recording_runner
    cfg = DEFAULT_CONFIG
    vad = None if options['no_vad'] else {
        'min_silence_duration_ms': cfg['vad_min_silence_ms'],
        'threshold': cfg['vad_threshold'], 'speech_pad_ms': cfg['vad_speech_pad_ms']}
    kwargs = dict(language=options['language'], want_words=spec['setting'],
                  vad_parameters=vad, batch_size=options['batch_size'])
    if options['warmup']:
        backend.transcribe_to_segments(spec['file'], **kwargs)
    observations.clear()
    started = time.perf_counter()
    segments, info = backend.transcribe_to_segments(spec['file'], **kwargs)
    elapsed = time.perf_counter()-started
    return {'type': 'run', 'manifest_id': spec['manifest_id'], 'file': spec['file'],
            'pair': spec['pair'], 'setting': spec['setting'], 'segments': segments,
            'kwargs': observations, 'wall_seconds': elapsed, 'peak_memory_bytes': peak_memory_bytes(),
            'language': info.language, 'device': backend.device, 'compute_type': backend.compute_type,
            'versions': {'faster_whisper': faster_whisper.__version__, 'ctranslate2': ctranslate2.__version__}}


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def run(args) -> int:
    if args.pairs < 1:
        raise ValueError('pairs must be positive')
    model = Path(args.model_dir)
    if not (model / 'model.bin').is_file():
        raise ValueError('model-dir must hold a local faster-whisper model.bin; downloads are disabled')
    files = [{'path': str(Path(f)), 'sha256': file_hash(Path(f))} for f in args.audio]
    if len({f['path'] for f in files}) != len(files):
        raise ValueError('audio files must be distinct')
    options = {k: getattr(args, k) for k in ('model_dir', 'device', 'compute_type', 'language',
                                           'batch_size', 'no_vad', 'pairs')}
    options['warmup'] = not args.cold
    manifest = {'type': 'manifest', 'files': files, 'options': options,
                'model_files': {p.name: file_hash(p) for p in sorted(model.iterdir()) if p.is_file()},
                'code': {name: file_hash(Path(name)) for name in (
                    'tools/word_timing_gate.py', 'core/backends/faster_whisper_be.py',
                    'core/transcriber.py', 'core/config.py', 'core/loop_guard.py', 'core/vad_window.py')}}
    manifest['id'] = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    output = Path(args.output)
    rows = read_records(output, repair_tail=True) if output.exists() else []
    if rows and rows[0] != manifest:
        raise ValueError('existing log has a different manifest; choose a new output file')
    if not rows:
        append_record(output, manifest)
    expected = len(files)*args.pairs*2
    expected_keys = {(f['path'], pair, setting) for f in files for pair, setting in run_order(args.pairs)}
    done = set()
    for index, row in enumerate(rows[1:], 1):
        if row.get('manifest_id') != manifest['id']:
            raise ValueError('foreign record in existing log')
        if row.get('type') == 'run':
            key = (row.get('file'), row.get('pair'), row.get('setting'))
            if key not in expected_keys or key in done or not isinstance(row.get('setting'), bool):
                raise ValueError('duplicate or invalid run in existing log')
            done.add(key)
        elif row.get('type') == 'end':
            if (index != len(rows)-1 or done != expected_keys or row.get('complete') is not True
                    or row.get('expected_runs') != expected):
                raise ValueError('incomplete or misplaced end marker')
        elif row.get('type') != 'error':
            raise ValueError('unknown record in existing log')
    profile = output.parent / (output.stem + '.profile')
    profile.mkdir(exist_ok=True)
    for file in files:
        for pair, setting in run_order(args.pairs):
            if (file['path'], pair, setting) in done:
                continue
            spec = dict(file=file['path'], pair=pair, setting=setting, options=options,
                        manifest_id=manifest['id'], profile=str(profile))
            print(f"{file['path']} pair {pair}: words {'on' if setting else 'off'}", file=sys.stderr)
            child = subprocess.run([sys.executable, str(Path(__file__)), '_one'],
                                   input=json.dumps(spec), capture_output=True, text=True, encoding='utf-8',
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if child.stderr:
                print(child.stderr, file=sys.stderr)
            if child.returncode:
                append_record(output, {'type': 'error', 'file': file['path'], 'pair': pair,
                                       'setting': setting, 'error': child.stderr, 'manifest_id': manifest['id']})
                return 1
            row = json.loads(child.stdout)
            if (row.get('type') != 'run' or row.get('manifest_id') != manifest['id']
                    or row.get('file') != file['path'] or row.get('pair') != pair
                    or row.get('setting') is not setting):
                raise ValueError('child returned an invalid measurement identity')
            append_record(output, row)
    if not rows or rows[-1].get('type') != 'end':
        append_record(output, {'type': 'end', 'manifest_id': manifest['id'],
                               'complete': True, 'expected_runs': expected})
    return 0


def main() -> int:
    if sys.argv[1:2] == ['_one']:
        spec = json.load(sys.stdin)
        result = _one(spec)
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    runner = commands.add_parser('run')
    runner.add_argument('audio', nargs='+')
    runner.add_argument('--model-dir', required=True)
    runner.add_argument('--output', required=True)
    runner.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    runner.add_argument('--compute-type', default='int8')
    runner.add_argument('--language')
    runner.add_argument('--batch-size', type=int, default=1)
    runner.add_argument('--pairs', type=int, default=4)
    runner.add_argument('--no-vad', action='store_true')
    runner.add_argument('--cold', action='store_true', help='omit warm-up; record cold measurements separately')
    scorer = commands.add_parser('score')
    scorer.add_argument('log')
    scorer.add_argument('--reference', action='append', default=[], metavar='AUDIO=TEXT_FILE')
    args = parser.parse_args()
    try:
        if args.command == 'run':
            return run(args)
        references = {}
        for value in args.reference:
            file, sep, text = value.partition('=')
            if not sep:
                raise ValueError('reference must be AUDIO=TEXT_FILE')
            references[str(Path(file))] = Path(text).read_text(encoding='utf-8-sig')
        result = score_records(read_records(Path(args.log)), references)
        print(json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False))
        print(result['verdict'])
        return 0 if result['verdict'] == 'PASS' else 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('FAIL: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
