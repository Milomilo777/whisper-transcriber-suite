"""Windowless subprocess fixture for pinned-download crash/concurrency tests."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


def main():
    mode, root_name, url = sys.argv[1:4]
    root = Path(root_name).resolve()
    import platformdirs

    for name in ("user_config_dir", "user_cache_dir", "user_log_dir", "user_data_dir", "user_state_dir"):
        setattr(platformdirs, name, lambda *a, **k: str(root / "userdirs-child"))

    from core import model_download as md, model_manager as mm

    md.MANIFEST_PATH = root / "manifest.json"
    md.DEFAULT_HOSTS = (url,)
    folder = root / "model"
    weights_first = "--weights-first" in sys.argv
    if weights_first:
        source = (PROJECT_ROOT / "core/model_download.py").read_text(encoding="utf-8")
        old = 'missing.sort(key=lambda item: (item[0] == "model.bin", item[1].size))'
        assert old in source
        exec(compile(source.replace(old, old.replace(" == ", " != ")), "core/model_download.py", "exec"), md.__dict__)
        md.MANIFEST_PATH = root / "manifest.json"
        md.DEFAULT_HOSTS = (url,)

    def gate():
        (root / "ready").touch()
        deadline = time.monotonic() + 20
        while not (root / "release").exists():
            if time.monotonic() > deadline:
                raise RuntimeError("test gate expired")
            time.sleep(0.01)

    if mode == "download-gated":
        transfer = md.ModelDownloader._transfer

        def gated_transfer(self, url, part, info, cancel):
            if part.name == ("config.json.part" if weights_first else "model.bin.part"):
                gate()
            return transfer(self, url, part, info, cancel)

        md.ModelDownloader._transfer = gated_transfer
    elif mode == "hash-gated":
        replace = md.ModelDownloader._replace

        def gated_replace(self, part, final, cancel):
            if final.name == "model.bin":
                gate()
            return replace(self, part, final, cancel)

        md.ModelDownloader._replace = gated_replace

    config = {"model": {"name": "fixture", "hf_repo": "fixture/tiny"}, "model_path": str(folder)}
    try:
        result = mm.ensure_model(config)
    except RuntimeError as exc:
        print(json.dumps({"installed": False, "error": str(exc)}), flush=True)
    else:
        print(json.dumps({"installed": True, "folder": result}), flush=True)


if __name__ == "__main__":
    main()
