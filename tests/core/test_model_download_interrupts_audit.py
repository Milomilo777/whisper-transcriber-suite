"""Model downloads that stop half-way: gated repos, a full disk, catalog sizes, non-ASCII folders."""
import errno
from pathlib import Path
from unittest import mock

import pytest
import requests

from core.model_manager import (
    _approx_model_bytes,
    _describe_download_error,
    ensure_model,
)


def _config(model_path: Path) -> dict:
    return {
        "model": {"name": "tiny", "hf_repo": "systran/faster-whisper-tiny"},
        "model_path": str(model_path),
    }


def test_disk_full_frees_partial(tmp_path):
    model_path = tmp_path / "model"
    dl_dir = model_path / ".cache" / "huggingface" / "download"

    def fake_download(*args, **kwargs):
        dl_dir.mkdir(parents=True, exist_ok=True)
        (dl_dir / "hash.etag.incomplete").write_text("partial")
        raise OSError(errno.ENOSPC, "No space left on device")

    with mock.patch("faster_whisper.utils.download_model", side_effect=fake_download):
        with pytest.raises(RuntimeError) as exc_info:
            ensure_model(_config(model_path))
        assert "Not enough free disk space" in str(exc_info.value)

    assert dl_dir.is_dir()
    assert not list(dl_dir.glob("*.incomplete"))


def test_disk_full_found_in_the_cause_chain_frees_partial(tmp_path):
    model_path = tmp_path / "model"
    dl_dir = model_path / ".cache" / "huggingface" / "download"

    def fake_download(*args, **kwargs):
        dl_dir.mkdir(parents=True, exist_ok=True)
        (dl_dir / "hash.etag.incomplete").write_text("partial")
        try:
            raise OSError(errno.ENOSPC, "No space left on device")
        except OSError as disk_full:
            raise RuntimeError("download wrapper failed") from disk_full

    with mock.patch("faster_whisper.utils.download_model", side_effect=fake_download):
        with pytest.raises(RuntimeError):
            ensure_model(_config(model_path))

    assert not list(dl_dir.glob("*.incomplete"))


def test_non_ascii_path(tmp_path):
    model_path = tmp_path / "مجلد" / "model"

    def fake_download(*args, **kwargs):
        model_path.mkdir(parents=True, exist_ok=True)
        (model_path / "model.bin").write_text("ok")
        (model_path / "config.json").write_text("ok")
        return True

    with mock.patch("faster_whisper.utils.download_model", side_effect=fake_download):
        res = ensure_model(_config(model_path))
        assert Path(res).exists()


@pytest.mark.parametrize("status", [401, 403])
def test_gated_model_explanation(status):
    exc = requests.exceptions.HTTPError(
        f"{status} Client Error", response=mock.Mock(status_code=status))
    msg = _describe_download_error(exc, Path("/tmp"), "huggingface.co")
    assert "authentication" in msg and "gated" in msg
    assert f"Access denied ({status})" in msg


def test_other_http_errors_keep_the_raw_text():
    exc = requests.exceptions.HTTPError("500 Server Error", response=mock.Mock(status_code=500))
    msg = _describe_download_error(exc, Path("/tmp"), "huggingface.co")
    assert "gated" not in msg


def test_approx_model_bytes_matches():
    from core.config import DEFAULT_CONFIG
    size = _approx_model_bytes(DEFAULT_CONFIG, "faster-whisper-large-v3")
    assert size > 0
    # A catalog slug, as a hand-edited config or an API override may set it.
    size2 = _approx_model_bytes({"model_catalog": {}}, "tiny")
    assert size2 > 0
    assert _approx_model_bytes({}, "no-such-model") == 0
