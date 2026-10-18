"""Explicit provisioning for Windows/Linux. Never run by imports or tests."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

from runtime import write_text

ROOT = Path(__file__).resolve().parent
WHISPER_TAG = "v1.7.1"


def download(url, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        partial = destination.with_name(destination.name + ".partial")
        try:
            with urllib.request.urlopen(url, timeout=60) as source, partial.open("wb") as target:
                shutil.copyfileobj(source, target)
            os.replace(partial, destination)
        finally:
            partial.unlink(missing_ok=True)
    return destination


def extract_archive(archive_path, destination):
    """Extract ordinary files only; reject traversal, links and special files."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    base = destination.resolve()

    def target_for(name):
        relative = Path(name)
        target = destination / relative
        if relative.is_absolute() or relative.drive or ".." in relative.parts or not target.resolve().is_relative_to(base):
            raise ValueError(f"Unsafe archive path: {name}")
        return target

    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                if stat.S_ISLNK(member.external_attr >> 16):
                    raise ValueError("Archive links are unsupported")
                target = target_for(member.filename)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)
    else:
        with tarfile.open(archive_path) as archive:
            for member in archive:
                target = target_for(member.name)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(member) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)
                else:
                    raise ValueError("Archive links/special files are unsupported")


def build_whisper():
    source = ROOT / "build/whisper.cpp"
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--depth", "1", "--branch", WHISPER_TAG,
                        "https://github.com/ggerganov/whisper.cpp.git", str(source)], check=True)
    tag = subprocess.check_output(["git", "-C", str(source), "describe", "--tags", "--exact-match"], text=True).strip()
    if tag != WHISPER_TAG:
        raise ValueError(f"Expected whisper.cpp {WHISPER_TAG}, found {tag}; use a fresh build directory")
    subprocess.run(["cmake", "-S", str(source), "-B", str(source / "build"),
                    "-DCMAKE_BUILD_TYPE=Release", "-DGGML_CUDA=OFF", "-DWHISPER_CURL=OFF"], check=True)
    subprocess.run(["cmake", "--build", str(source / "build"), "--config", "Release", "--parallel", "2"], check=True)


def fetch_models(include_reference=False):
    from engines.whispercpp_engine import find_binary
    models = ROOT / "models"
    archives = models / ".downloads"
    vosk = models / "vosk-model-small-fa-0.42"
    if not vosk.is_dir():
        archive = download("https://alphacephei.com/vosk/models/vosk-model-small-fa-0.42.zip",
                           archives / "vosk-model-small-fa-0.42.zip")
        extract_archive(archive, models)
    for size in ("tiny", "base"):
        name = f"sherpa-onnx-whisper-{size}"
        if not (models / name).is_dir():
            archive = download(f"https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/{name}.tar.bz2",
                               archives / f"{name}.tar.bz2")
            extract_archive(archive, models)
    quantize = find_binary("whisper-quantize")
    sizes = ["tiny", "base", "small"] + (["large-v3-turbo"] if include_reference else [])
    for size in sizes:
        original = download(f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{size}.bin",
                            models / f"ggml-{size}.bin")
        for quant in (("q5_0",) if size == "large-v3-turbo" else ("q5_1", "q8_0")):
            output = models / f"ggml-{size}-{quant}.bin"
            if not output.exists():
                subprocess.run([str(quantize), str(original), str(output), quant], check=True)


def model_hashes(models):
    hashes = {}
    for path in sorted(Path(models).rglob("*")):
        if not path.is_file() or ".downloads" in path.parts or path.name == "SHA256SUMS.txt":
            continue
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        hashes[path.relative_to(models).as_posix()] = digest.hexdigest()
    return hashes


def write_hashes():
    hashes = model_hashes(ROOT / "models")
    if not hashes:
        raise ValueError("No model files; SHA-256 values remain unknown")
    text = "\n".join(f"{digest}  models/{path}" for path, digest in hashes.items()) + "\n"
    write_text(ROOT / "models/SHA256SUMS.txt", text)
    readme = ROOT / "README.md"
    content = readme.read_text(encoding="utf-8")
    start, end = "<!-- MODEL_SHA256_START -->", "<!-- MODEL_SHA256_END -->"
    if start in content and end in content:
        before, rest = content.split(start, 1)
        _, after = rest.split(end, 1)
        write_text(readme, before + start + "\n\n```text\n" + text + "```\n\n" + end + after)
    print(text, end="")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for action in ("all", "install", "build", "models", "hashes"):
        parser.add_argument("--" + action, action="store_true")
    parser.add_argument("--include-reference", action="store_true", help="Also fetch optional large-v3-turbo q5_0")
    args = parser.parse_args()
    if not any((args.all, args.install, args.build, args.models, args.hashes)):
        parser.print_help()
        return 0
    try:
        if args.install or args.all:
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")], check=True)
        if args.build or args.all:
            build_whisper()
        if args.models or args.all:
            fetch_models(args.include_reference)
        if args.hashes or args.models or args.all:
            write_hashes()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Setup stopped: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
