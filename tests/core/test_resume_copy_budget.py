"""Resume preparation must not consume network time or recopy owned bytes."""
from pathlib import Path
from types import SimpleNamespace
import os
import pytest
from core import model_download as md, verified_download as vd
from tests.core.test_model_download import Server, downloader, entry
from tests.core.test_shared_download_ownership import target  # noqa: F401
from tests.core.test_private_partial_copy import hide_link_count


def test_slow_local_prefix_copy_is_outside_the_network_rate_window(tmp_path, monkeypatch):
    data = b"synthetic payload " * 4096
    (tmp_path / "model.bin.part").write_bytes(data[:32768])
    clock = [1000.0]
    copy = vd._copy_prefix
    def slow(*args, **kwargs):
        result = copy(*args, **kwargs)
        clock[0] += 125.0
        return result
    monkeypatch.setattr(vd, "_copy_prefix", slow)
    with Server(data=data) as server:
        client = downloader(server.url)
        client._rate_clock = lambda: clock[0]
        assert client.download("fixture/tiny", tmp_path, entry(data))
        assert len(server.gets) == 1
    assert (tmp_path / "model.bin").read_bytes() == data


def test_reconnects_do_not_recopy_the_same_owned_prefix(tmp_path, monkeypatch):
    data = b"synthetic payload " * 4096
    part = tmp_path / "model.bin.part"; part.write_bytes(data[:32768])
    copies = []; copy = vd._copy_prefix
    def observed(*args, **kwargs):
        copies.append(args[2]); return copy(*args, **kwargs)
    monkeypatch.setattr(vd, "_copy_prefix", observed)
    with Server(data=data, actions=[{"status": 503}, {"status": 503}]) as server:
        client = md.ModelDownloader(hosts=[server.url], retry_delays=(0, 0, 0),
                                    allow_loopback_redirects=True)
        assert client.download("fixture/tiny", tmp_path, entry(data))
        assert len(server.gets) == 3
    assert copies == [32768]
    assert (tmp_path / "model.bin").read_bytes() == data


def test_free_space_covers_sequential_copy_then_remaining_transfer(target, monkeypatch):
    prefix = len(target.data) * 3 // 4
    target.part.write_bytes(target.data[:prefix])
    free = vd._FREE_SPACE_MARGIN + prefix + 1024
    monkeypatch.setattr(vd.shutil, "disk_usage", lambda _: SimpleNamespace(free=free))
    target.run()
    assert target.dest.read_bytes() == target.data


@pytest.mark.parametrize("stale_metadata", [False, True])
def test_replaced_partial_is_detached_again_before_retry(tmp_path, monkeypatch, stale_metadata):
    data = b"synthetic payload " * 4096
    part = tmp_path / "model.bin.part"; part.write_bytes(data[:32768])
    original = tmp_path / "synthetic-original.bin"; original.write_bytes(data[:32768])
    copies = []; copy = vd._copy_prefix
    def observed(*args, **kwargs):
        copies.append(args[2]); return copy(*args, **kwargs)
    monkeypatch.setattr(vd, "_copy_prefix", observed)
    with Server(data=data, actions=[{"status": 503}]) as server:
        client = md.ModelDownloader(hosts=[server.url], retry_delays=(0,),
                                    allow_loopback_redirects=True)
        wait = client._wait
        def replace_before_retry(*args):
            previous = part.lstat()
            part.unlink(); part.hardlink_to(original)
            hide_link_count(monkeypatch, original)
            if stale_metadata:
                stat = os.stat
                stale = [True]
                def cached(path, *args, **kwargs):
                    if (str(path) == str(part) and stale[0]
                            and kwargs.get("follow_symlinks") is False):
                        stale[0] = False
                        return previous
                    return stat(path, *args, **kwargs)
                monkeypatch.setattr(os, "stat", cached)
            # This scenario replaces the path once; unrelated file retries do
            # not create a new generation on every permission-error wait.
            monkeypatch.setattr(client, "_wait", wait)
        monkeypatch.setattr(client, "_wait", replace_before_retry)
        try:
            assert client.download("fixture/tiny", tmp_path, entry(data))
        finally:
            assert original.read_bytes() == data[:32768]
    assert copies == [32768, 32768]
    assert original.read_bytes() == data[:32768]
    assert (tmp_path / "model.bin").read_bytes() == data


@pytest.mark.parametrize("oversized", [False, True])
def test_cached_identity_mismatch_refreshes_the_actual_prefix_size(tmp_path, monkeypatch, oversized):
    data = b"synthetic payload " * 4096
    part = tmp_path / "model.bin.part"; part.write_bytes(data[:32768])
    original = tmp_path / "synthetic-replacement-original.bin"
    original_bytes = data + b"unrelated suffix" * 1024 if oversized else data[:16384]
    original.write_bytes(original_bytes)
    handles = []; real_open, real_unlink = Path.open, Path.unlink
    def opened(path, *args, **kwargs):
        stream = real_open(path, *args, **kwargs)
        if path == part and args == ("rb",): handles.append(stream)
        return stream
    def unlinked(path, *args, **kwargs):
        if path == part: assert all(stream.closed for stream in handles), "close the probe before unlink"
        return real_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", opened)
    monkeypatch.setattr(Path, "unlink", unlinked)
    with Server(data=data, actions=[{"status": 503}]) as server:
        client = md.ModelDownloader(hosts=[server.url], retry_delays=(0,), allow_loopback_redirects=True)
        wait = client._wait
        def replaced(*args):
            previous = part.lstat()
            part.unlink(); part.hardlink_to(original)
            hide_link_count(monkeypatch, original)
            stat = os.stat; stale = [True]
            def cached(path, *args, **kwargs):
                if str(path) == str(part) and stale[0] and kwargs.get("follow_symlinks") is False:
                    stale[0] = False; return previous
                return stat(path, *args, **kwargs)
            monkeypatch.setattr(os, "stat", cached)
            monkeypatch.setattr(client, "_wait", wait)
        monkeypatch.setattr(client, "_wait", replaced)
        try:
            assert client.download("fixture/tiny", tmp_path, entry(data))
        finally:
            assert original.read_bytes() == original_bytes
        assert [value for _, value in server.gets] == ["bytes=32768-", None if oversized else "bytes=16384-"]
    assert (tmp_path / "model.bin").read_bytes() == data


@pytest.mark.parametrize("hide_links", [False, True])
def test_replacement_after_reuse_probe_cannot_truncate_an_unrelated_suffix(tmp_path, monkeypatch, hide_links):
    data = b"synthetic payload " * 4096
    part = tmp_path / "model.bin.part"; part.write_bytes(data[:32768])
    original = tmp_path / "synthetic-unrelated-original.bin"
    original_bytes = data[:32768] + b"unrelated suffix must remain" * 1024
    original.write_bytes(original_bytes)
    with Server(data=data, actions=[{"status": 503}]) as server:
        client = md.ModelDownloader(hosts=[server.url], retry_delays=(0,), allow_loopback_redirects=True)
        opened = client._open
        def replace_after_open(*args, **kwargs):
            response = opened(*args, **kwargs)
            if not kwargs.get("probe"):
                part.unlink(); part.hardlink_to(original)
                if hide_links: hide_link_count(monkeypatch, original)
            return response
        monkeypatch.setattr(client, "_open", replace_after_open)
        with pytest.raises(md.mm.HuggingFaceDownloadError):
            client.download("fixture/tiny", tmp_path, entry(data))
    assert original.read_bytes() == original_bytes
    assert not (tmp_path / "model.bin").exists()


def test_retained_alias_rechecks_free_space_after_the_copy(target, monkeypatch):
    prefix = len(target.data) * 3 // 4
    original = target.dest.parent / "synthetic-aliased-prefix.bin"
    original.write_bytes(target.data[:prefix]); target.part.hardlink_to(original)
    hide_link_count(monkeypatch, original)
    free = [vd._FREE_SPACE_MARGIN + len(target.data) - 1]
    monkeypatch.setattr(vd.shutil, "disk_usage", lambda _: SimpleNamespace(free=free[0]))
    copy = vd._copy_prefix
    def allocated(*args, **kwargs):
        result = copy(*args, **kwargs); free[0] -= args[2]; return result
    monkeypatch.setattr(vd, "_copy_prefix", allocated)
    with pytest.raises((vd.DownloadError, md.mm.InsufficientDiskSpace)):
        target.run()
    assert target.ranges() == []
    assert original.read_bytes() == target.data[:prefix]


@pytest.mark.parametrize("cancel_on_denial", [False, True])
def test_cached_probe_permission_retry_and_cancel_preserve_prefix(tmp_path, monkeypatch, cancel_on_denial):
    import threading
    data = b"synthetic payload " * 4096
    part = tmp_path / "model.bin.part"; prefix = data[:32768]; part.write_bytes(prefix)
    event = threading.Event(); denials = []; real_open = Path.open
    with Server(data=data, actions=[{"status": 503}]) as server:
        client = md.ModelDownloader(hosts=[server.url], retry_delays=(0,), allow_loopback_redirects=True)
        def opened(path, *args, **kwargs):
            if path == part and args == ("rb",) and len(server.gets) == 1 and not denials:
                denials.append(1); raise PermissionError("Synthetic cached probe denial")
            return real_open(path, *args, **kwargs)
        monkeypatch.setattr(Path, "open", opened)
        wait = client._wait
        def waited(*args):
            if denials and cancel_on_denial: event.set()
            return wait(*args)
        monkeypatch.setattr(client, "_wait", waited)
        result = client.download("fixture/tiny", tmp_path, entry(data), cancel_event=event)
        assert denials == [1]
        assert result is (not cancel_on_denial)
        if cancel_on_denial:
            assert len(server.gets) == 1
            assert part.read_bytes() == prefix
            assert not (tmp_path / "model.bin").exists()
        else:
            assert len(server.gets) == 2
            assert (tmp_path / "model.bin").read_bytes() == data
