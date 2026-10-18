"""Python equivalent of run_all.sh; never provisions or downloads anything."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(os.path.relpath(Path(__file__).parent))
ENGINES = ",".join(["vosk-small-fa", "sherpa-whisper-tiny", "sherpa-whisper-base"] +
                   [f"whisper.cpp-{size}-{quant}" for size in ("tiny", "base", "small")
                    for quant in ("q5_1", "q8_0")])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio-dir", default=str(ROOT / "data"))
    parser.add_argument("--refs", default=str(ROOT / "data/refs.tsv"))
    parser.add_argument("--no-refs", action="store_true")
    parser.add_argument("--engines", default=ENGINES)
    parser.add_argument("--include-reference", action="store_true")
    parser.add_argument("--threads", default="1,4")
    parser.add_argument("--out-dir", default=str(ROOT / "results"))
    parser.add_argument("--timeout", type=float, default=3600)
    args = parser.parse_args()
    output = Path(args.out_dir)
    engines = args.engines + (",whisper.cpp-large-v3-turbo-q5_0" if args.include_reference else "")
    python = [sys.executable] + (["-S"] if sys.flags.no_site else [])
    command = python + [str(ROOT / "bench.py"), "--audio-dir", args.audio_dir,
                       "--engines", engines, "--threads", args.threads,
                       "--out", str(output / "fleurs-fa.json"), "--timeout", str(args.timeout)]
    if not args.no_refs:
        command += ["--refs", args.refs]
    subprocess.run(command, check=True)
    subprocess.run(python + [str(ROOT / "summarize.py"), "--json", str(output / "fleurs-fa.json"),
                            "--out", str(output / "SUMMARY.md")], check=True)
    print(f"Saved {output / 'SUMMARY.md'}")


if __name__ == "__main__":
    main()
