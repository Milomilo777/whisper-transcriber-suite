"""Pin the built-in model catalog using Hub metadata and bytes from pinned commits.

Run from the repository root: python tools/build_model_manifest.py --output core/model_manifest.json
An injected fetcher returns bytes for a URL, keeping the builder tests offline.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

# Direct script execution puts tools/ first. The command is run from the repo root.
if __name__ == "__main__":
    sys.path.insert(0, str(Path.cwd()))

from core.model_download import parse_entry
from core.model_manager import MODEL_REGISTRY
from core.verified_download import urlopen_https_only

_PATTERNS = ("config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*")


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "WhisperTranscriberSuite"})
    with urlopen_https_only(request, timeout=30) as response:
        return response.read()


def build_manifest(fetcher: Callable[[str], bytes] = fetch_bytes) -> dict:
    """LFS hashes come from the primary API; ordinary Git files are hashed from bytes.

    Extra hosts are deliberately empty. Add one only after verifying every pinned
    file against it; repository names alone do not establish mirror equivalence.
    """
    result = {}
    for repo in sorted({item["hf_repo"] for item in MODEL_REGISTRY.values()}):
        base = "https://huggingface.co/" + urllib.parse.quote(repo, safe="/")
        metadata = json.loads(fetcher("https://huggingface.co/api/models/" +
                                      urllib.parse.quote(repo, safe="/") + "?blobs=true"))
        commit = metadata["sha"]
        files = {}
        for item in metadata["siblings"]:
            name = item["rfilename"]
            if not any(fnmatch.fnmatchcase(name, pattern) for pattern in _PATTERNS):
                continue
            lfs = item.get("lfs")
            if lfs:
                size, digest = lfs["size"], lfs["sha256"]
                if item.get("size", size) != size:
                    raise ValueError(f"Conflicting file sizes for {repo}/{name}")
            else:
                body = fetcher(f"{base}/resolve/{commit}/{urllib.parse.quote(name)}")
                size, digest = len(body), hashlib.sha256(body).hexdigest()
                if item.get("size", size) != size:
                    raise ValueError(f"Short response for {repo}/{name}")
            files[name] = {"size": size, "sha256": digest}
        if not {"model.bin", "config.json"} <= files.keys():
            raise ValueError(f"Missing runtime files in {repo}")
        raw = {"commit": commit, "files": files, "hosts": []}
        parse_entry(raw)
        result[repo] = raw
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("core/model_manifest.json"))
    args = parser.parse_args()
    manifest = build_manifest()
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, args.output)
    print(f"Pinned {len(manifest)} model repositories in {args.output}")


if __name__ == "__main__":
    main()
