"""Explicit opt-in FLEURS download. Importing this module is offline and stdlib-only."""
import argparse
from array import array
import csv
import io
from pathlib import Path
import random
import sys
import wave

from runtime import audio_duration, write_json, write_text

ROOT = Path(__file__).resolve().parent


def sampled_indices(total, size=300, seed=1234):
    if total < 1 or size < 1:
        raise ValueError("Dataset and sample size must be positive")
    return random.Random(seed).sample(range(total), min(size, total))


def build_long_form(paths, output, silence_s=.5):
    paths = list(paths)
    if not paths or silence_s < 0:
        raise ValueError("Long form needs files and nonnegative silence")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as target:
        target.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        for index, path in enumerate(paths):
            audio_duration(path)
            if index:
                target.writeframes(b"\0\0" * round(silence_s * 16000))
            with wave.open(str(path), "rb") as source:
                while chunk := source.readframes(16000):
                    target.writeframes(chunk)
    return audio_duration(output)


def _write_pcm(path, samples):
    # Audio(sampling_rate=16000, mono=True) supplies floating point mono samples.
    pcm = array("h", (max(-32768, min(32767, round(float(x) * 32768))) for x in samples))
    if sys.byteorder != "little":
        pcm.byteswap()
    with wave.open(str(path), "wb") as target:
        target.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        target.writeframes(pcm.tobytes())


def download_data(data_dir):
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    if list(data_dir.glob("*.wav")) or (data_dir / "refs.tsv").exists():
        raise ValueError("Use a fresh data directory; existing WAVs/references will not be overwritten")
    try:
        from datasets import Audio, load_dataset
        # Non-streaming metadata is memory-mapped; sample uniformly over the WHOLE split,
        # not the first shuffle buffer. Decode only selected rows, one at a time.
        dataset = load_dataset("google/fleurs", "fa_ir", split="test", trust_remote_code=True)
        dataset = dataset.cast_column("audio", Audio(sampling_rate=16000, mono=True))
        indices = sampled_indices(len(dataset))
        refs, source_ids = [], []
        for position, index in enumerate(indices):
            item = dataset[index]
            audio = item["audio"]
            if audio["sampling_rate"] != 16000:
                raise ValueError("FLEURS decoder did not produce 16 kHz audio")
            key = f"{position:04d}"
            path = data_dir / (key + ".wav")
            _write_pcm(path, audio["array"])
            refs.append((key, audio_duration(path), item["raw_transcription"]))
            source_ids.append(str(item.get("id", index)))
        long_paths = [data_dir / (row[0] + ".wav") for row in refs[:25]]
        duration = build_long_form(long_paths, data_dir / "long_form.wav")
        long_ref = " ".join(row[2] for row in refs[:25])
        rows = refs + [("long_form", duration, long_ref)]
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, delimiter="\t", lineterminator="\n")
        writer.writerow(["id", "duration_s", "reference"])
        writer.writerows((key, f"{seconds:.6f}", text) for key, seconds, text in rows)
        write_text(data_dir / "refs.tsv", buffer.getvalue())
        write_json(data_dir / "manifest.json", {
            "dataset": "google/fleurs", "config": "fa_ir", "split": "test",
            "seed": 1234, "sample_size": len(refs), "source_indices": indices, "source_ids": source_ids,
            "long_form": {"utterances": len(long_paths), "silence_s": .5, "duration_s": duration}})
    except Exception as error:
        # Never replace README on a network/dependency failure, and never substitute data.
        write_text(data_dir / "DOWNLOAD_ERROR.txt", f"FLEURS download failed; no substitution: {type(error).__name__}: {error}\n")
        raise
    print(f"Saved {len(refs)} FLEURS utterances and long_form ({duration:.3f} seconds) to {data_dir}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    args = parser.parse_args()
    try:
        download_data(args.data_dir)
    except Exception as error:
        parser.exit(1, f"FLEURS unavailable; stopped: {error}\n")


if __name__ == "__main__":
    main()
