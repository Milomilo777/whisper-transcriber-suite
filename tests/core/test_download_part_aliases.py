"""A resume pathname must not grant ownership of another file's bytes."""
from pathlib import Path
import builtins

import pytest

from core import model_download as md, verified_download as vd
from tests.core.test_shared_download_ownership import target  # noqa: F401
from tests.core.test_model_download import Server, downloader, entry


def test_an_existing_hardlinked_partial_never_modifies_the_other_name(target):
    original = target.dest.parent / "synthetic-owner-original.bin"
    before = target.data[:513]
    original.write_bytes(before)
    target.part.hardlink_to(original)
    assert original.stat().st_nlink == 2
    error = None
    try:
        target.run()
    except Exception as caught:
        error = caught
    assert original.read_bytes() == before, "Downloading must not append through an unrelated file alias"
    assert not target.dest.exists()
    assert target.requests() == 0
    assert isinstance(error, (vd.DownloadError, md.mm.HuggingFaceDownloadError, md.mm.ModelDestinationNotWritable))


def test_an_ordinary_private_partial_can_still_resume(target):
    target.part.write_bytes(target.data[:513])
    assert target.part.stat().st_nlink == 1
    target.run()
    assert target.dest.read_bytes() == target.data and not target.part.exists()


@pytest.mark.parametrize("existing", [False, True], ids=["exclusive-create", "resume-open"])
def test_alias_inserted_at_open_never_truncates_or_appends_to_the_other_file(target, monkeypatch, existing):
    original = target.dest.parent / "synthetic-original-at-open.bin"
    before = target.data[:513]
    original.write_bytes(before)
    if existing:
        target.part.write_bytes(before)
    real_open = builtins.open
    swaps = []

    def swap_then_open(path, mode="r", *args, **kwargs):
        if Path(path) == target.part and mode in {"wb", "ab", "r+b", "x+b"} and not swaps:
            swaps.append(True)
            target.part.unlink(missing_ok=True)
            target.part.hardlink_to(original)
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", swap_then_open)
    error = None
    try:
        target.run()
    except Exception as caught:
        error = caught
    assert swaps == [True] and original.read_bytes() == before
    assert not target.dest.exists()
    assert isinstance(error, (vd.DownloadError, md.mm.HuggingFaceDownloadError, md.mm.ModelDestinationNotWritable))


def test_an_existing_symlink_partial_is_not_followed(target):
    original = target.dest.parent / "synthetic-symlink-target.bin"
    before = target.data[:513]
    original.write_bytes(before)
    try:
        target.part.symlink_to(original)
    except OSError as error:
        if getattr(error, "winerror", None) == 1314:
            pytest.skip("This Windows account cannot create file symlinks")
        raise
    error = None
    try:
        target.run()
    except Exception as caught:
        error = caught
    assert original.read_bytes() == before and not target.dest.exists()
    assert target.requests() == 0
    assert isinstance(error, (vd.DownloadError, md.mm.HuggingFaceDownloadError, md.mm.ModelDestinationNotWritable))


def test_a_different_single_link_file_inserted_at_open_is_preserved(target, monkeypatch):
    original = target.dest.parent / "synthetic-replacement-original.bin"
    before = b"different single-link file"
    original.write_bytes(before)
    target.part.write_bytes(target.data[:513])
    old_part = target.part.with_name("saved-original-part")
    real_open = builtins.open
    swaps = []

    def replace_then_open(path, mode="r", *args, **kwargs):
        if Path(path) == target.part and mode in {"r+b", "ab", "wb"} and not swaps:
            swaps.append(True)
            target.part.rename(old_part)
            original.replace(target.part)
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", replace_then_open)
    error = None
    try:
        target.run()
    except Exception as caught:
        error = caught
    assert swaps == [True] and target.part.stat().st_nlink == 1
    assert target.part.read_bytes() == before and not target.dest.exists()
    assert old_part.read_bytes() == target.data[:513]
    assert isinstance(error, (vd.DownloadError, md.mm.HuggingFaceDownloadError, md.mm.ModelDestinationNotWritable))


def test_ignored_range_restart_alias_cannot_modify_another_file(tmp_path, monkeypatch):
    data = b"complete model data\n" * 1024
    dest = tmp_path / "model.bin"
    part = vd.part_path(dest)
    prefix = data[:513]
    part.write_bytes(prefix)
    original = tmp_path / "synthetic-restart-target.bin"
    before = b"unrelated preserved bytes"
    original.write_bytes(before)
    restart = part.with_name("." + part.name + ".restart")
    monkeypatch.setattr(vd.offline, "require_online", lambda *args: None)
    with Server(data=data, actions=[{"status": 200}]) as server:
        client = downloader(server.url)
        real_open = client._open

        def response_with_alias(*args, **kwargs):
            response = real_open(*args, **kwargs)
            if not kwargs.get("probe", False):
                restart.hardlink_to(original)
            return response

        monkeypatch.setattr(client, "_open", response_with_alias)
        error = None
        try:
            client.download("fixture/tiny", tmp_path, entry(data))
        except Exception as caught:
            error = caught
    assert original.read_bytes() == before
    assert part.read_bytes() == prefix and not dest.exists()
    assert isinstance(error, (vd.DownloadError, md.mm.HuggingFaceDownloadError, md.mm.ModelDestinationNotWritable))


def test_rejected_host_rollback_cannot_truncate_a_linked_original(tmp_path, monkeypatch):
    data = b"complete model bytes\n" * 2048
    part = vd.part_path(tmp_path / "model.bin")
    prefix = data[:513]
    part.write_bytes(prefix)
    original = tmp_path / "synthetic-rollback-original.bin"
    before = b"unrelated preserved bytes\n" * 512
    original.write_bytes(before)
    saved = tmp_path / "saved-good-prefix.bin"
    monkeypatch.setattr(vd.offline, "require_online", lambda *args: None)
    with Server(data=data) as server:
        client = downloader(server.url)

        def reject_with_alias(*args):
            part.rename(saved)
            part.hardlink_to(original)
            raise md._HostUnavailable("synthetic rejected response bytes", reject_bytes=True)

        monkeypatch.setattr(client, "_transfer", reject_with_alias)
        with pytest.raises(md.mm.HuggingFaceDownloadError):
            client.download("fixture/tiny", tmp_path, entry(data))
    assert original.read_bytes() == before
    assert saved.read_bytes() == prefix and not (tmp_path / "model.bin").exists()
