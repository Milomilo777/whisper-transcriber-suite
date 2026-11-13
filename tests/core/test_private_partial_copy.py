"""A reported single link is not proof of unique ownership on network storage."""
from pathlib import Path
from types import SimpleNamespace
import os
import subprocess
import sys
import errno

import pytest

from core import verified_download as vd
from core import model_download as md
from tests.core.test_model_download import Server, downloader, entry
from tests.core.test_shared_download_ownership import target  # noqa: F401


def hide_link_count(monkeypatch, original):
    """Emulate the observed SMB metadata while retaining real hardlinks/IDs."""
    identity = (original.stat().st_dev, original.stat().st_ino)
    real_stat, real_lstat, real_fstat = os.stat, os.lstat, os.fstat

    def masked(info):
        if (info.st_dev, info.st_ino) != identity:
            return info
        values = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
        values["st_nlink"] = 1
        return SimpleNamespace(**values)

    monkeypatch.setattr(os, "lstat", lambda *a, **kw: masked(real_lstat(*a, **kw)))
    monkeypatch.setattr(os, "stat", lambda *a, **kw: masked(real_stat(*a, **kw)))
    monkeypatch.setattr(os, "fstat", lambda *a, **kw: masked(real_fstat(*a, **kw)))


@pytest.mark.parametrize("offset", [0, 4, 12])
def test_hidden_alias_is_detached_before_truncation_or_append(tmp_path, monkeypatch, offset):
    original = tmp_path / "synthetic-original.bin"
    before = b"prefix bytes remain unchanged"
    original.write_bytes(before)
    partial = tmp_path / "download.part"
    partial.hardlink_to(original)
    hide_link_count(monkeypatch, original)
    with vd.open_part(partial, offset) as stream:
        stream.write(b"tail")
    assert original.read_bytes() == before
    assert partial.read_bytes() == before[:offset] + b"tail"
    assert not partial.samefile(original)


def test_hidden_alias_resumes_a_verified_http_download(target, monkeypatch):
    original = target.dest.parent / "synthetic-prefix-original.bin"
    before = target.data[:513]
    original.write_bytes(before)
    target.part.hardlink_to(original)
    hide_link_count(monkeypatch, original)
    target.run()
    assert original.read_bytes() == before
    assert target.dest.read_bytes() == target.data
    assert not target.dest.samefile(original)


@pytest.mark.parametrize("stage", ["copy", "claimed", "published"])
def test_forced_exit_recovers_the_full_prefix_before_http_range(target, stage):
    before = target.data[:513]
    target.part.write_bytes(before)
    code = r'''
import os,sys
from pathlib import Path
from core import verified_download as vd
part,stage=Path(sys.argv[1]),sys.argv[2]
copy,rename,publish=vd._copy_prefix,os.rename,vd._publish_part_exclusive
def copied(*a,**kw):
    result=copy(*a,**kw)
    if stage=='copy':os._exit(19)
    return result
def renamed(source,dest,*a,**kw):
    result=rename(source,dest,*a,**kw)
    if stage=='claimed' and Path(source)==part and Path(dest).name=='previous':os._exit(19)
    return result
def published(*a,**kw):
    result=publish(*a,**kw)
    if stage=='published':os._exit(19)
    return result
vd._copy_prefix=copied;os.rename=renamed;vd._publish_part_exclusive=published
vd.prepare_part(part,513)
raise SystemExit('Forced-exit hook was not reached')
'''
    env = {**os.environ, "PYTHONPATH": str(Path(vd.__file__).resolve().parents[1]),
           "WTS_PROFILE_DIR": str(target.dest.parent / "child-profile")}
    result = subprocess.run([sys.executable, "-c", code, str(target.part), stage],
                            env=env, capture_output=True, timeout=20)
    assert result.returncode == 19, result.stderr.decode(errors="replace")
    target.run()
    assert target.dest.read_bytes() == target.data
    assert target.ranges() == ["bytes=513-"]
    assert not list(target.part.parent.glob(f".{target.part.name}.private-*"))


def test_copy_failure_preserves_the_original_named_prefix(tmp_path, monkeypatch):
    partial = tmp_path / "download.part"
    before = b"complete saved prefix"
    partial.write_bytes(before)

    def refuse(*args):
        raise OSError("synthetic prefix copy failure")

    monkeypatch.setattr(vd, "_copy_prefix", refuse)
    with pytest.raises(OSError):
        vd.prepare_part(partial, len(before))
    assert partial.read_bytes() == before
    assert not list(tmp_path.glob(".download.part.private-*"))


def test_preparation_preserves_an_inserted_file_instead_of_replacing_it(tmp_path, monkeypatch):
    partial = tmp_path / "download.part"
    partial.write_bytes(b"prior saved prefix")
    inserted = b"unrelated synthetic original"
    publish = vd._publish_part_exclusive

    def insert_before_publish(source, target, check_cancel, **kw):
        target.write_bytes(inserted)
        return publish(source, target, check_cancel, **kw)

    monkeypatch.setattr(vd, "_publish_part_exclusive", insert_before_publish)
    with pytest.raises(FileExistsError):
        vd.prepare_part(partial, 5)
    assert partial.read_bytes() == inserted
    saved = list(tmp_path.glob(".download.part.private-*/previous"))
    assert len(saved) == 1 and saved[0].read_bytes() == b"prior saved prefix"


def test_hidden_restart_alias_keeps_original_and_completes_download(tmp_path, monkeypatch):
    data = b"complete model bytes\n" * 1024
    part = vd.part_path(tmp_path / "model.bin")
    part.write_bytes(data[:513])
    original = tmp_path / "synthetic-restart-original.bin"
    before = b"unrelated saved bytes"
    original.write_bytes(before)
    hide_link_count(monkeypatch, original)
    monkeypatch.setattr(vd.offline, "require_online", lambda *a: None)
    with Server(data=data, actions=[{"status": 200}]) as server:
        client = downloader(server.url)
        real_open = client._open

        def insert_alias(*a, **kw):
            response = real_open(*a, **kw)
            if not kw.get("probe", False):
                part.with_name("." + part.name + ".restart").hardlink_to(original)
            return response

        monkeypatch.setattr(client, "_open", insert_alias)
        assert client.download("fixture/tiny", tmp_path, entry(data))
    assert original.read_bytes() == before
    assert (tmp_path / "model.bin").read_bytes() == data


def test_hidden_rollback_alias_never_truncates_original(tmp_path, monkeypatch):
    data = b"complete model bytes\n" * 1024
    part = vd.part_path(tmp_path / "model.bin")
    prefix = data[:513]
    part.write_bytes(prefix)
    saved = tmp_path / "saved-prefix.bin"
    original = tmp_path / "synthetic-rollback-original.bin"
    before = b"unrelated bytes\n" * 512
    original.write_bytes(before)
    hide_link_count(monkeypatch, original)
    monkeypatch.setattr(vd.offline, "require_online", lambda *a: None)
    with Server(data=data) as server:
        client = downloader(server.url)

        def reject(*a):
            part.rename(saved)
            part.hardlink_to(original)
            raise md._HostUnavailable("synthetic rejected host", reject_bytes=True)

        monkeypatch.setattr(client, "_transfer", reject)
        with pytest.raises(md.mm.HuggingFaceDownloadError):
            client.download("fixture/tiny", tmp_path, entry(data))
    assert original.read_bytes() == before
    assert saved.read_bytes() == prefix


@pytest.mark.parametrize("hardlinks", [True, False])
def test_non_windows_exclusive_publication_keeps_resume_bytes(tmp_path, monkeypatch, hardlinks):
    partial = tmp_path / "download.part"
    partial.write_bytes(b"saved prefix")
    monkeypatch.setattr(vd, "_PART_WINDOWS", False)
    if not hardlinks:
        def unsupported(*a, **kw):
            raise OSError(errno.ENOTSUP, "synthetic unavailable hardlinks")
        monkeypatch.setattr(os, "link", unsupported)
    with vd.open_part(partial, 5) as stream:
        stream.write(b"tail")
    assert partial.read_bytes() == b"savedtail"
    assert not list(tmp_path.glob(".download.part.private-*"))


@pytest.mark.parametrize("stage", ["hardlink", "copy", "record"])
@pytest.mark.parametrize("name", ["download.part", "download[1].part"])
def test_forced_exit_during_posix_publication_recovers_prefix(tmp_path, stage, name):
    partial = tmp_path / name
    before = b"complete saved prefix"
    partial.write_bytes(before)
    code = r'''
import errno,os,sys
from pathlib import Path
from core import verified_download as vd
part,stage=Path(sys.argv[1]),sys.argv[2]
link,copy,replace=os.link,vd._copy_prefix,os.replace
vd._PART_WINDOWS=False
def linked(source,target):
    if stage!='hardlink':raise OSError(errno.ENOTSUP,'synthetic unavailable hardlinks')
    link(source,target)
    os._exit(19)
def copied(reader,writer,size,check_cancel):
    if Path(writer.name)==part:
        writer.write(reader.read(3));writer.flush();os.fsync(writer.fileno())
        os._exit(19)
    return copy(reader,writer,size,check_cancel)
def replaced(source,target):
    if stage=='record' and Path(source).name=='state.next' and part.exists() and part.stat().st_size==0:
        os._exit(19)
    return replace(source,target)
os.link=linked;vd._copy_prefix=copied;os.replace=replaced
vd.prepare_part(part,len(part.read_bytes()))
raise SystemExit('Forced-exit hook was not reached')
'''
    env = {**os.environ, "PYTHONPATH": str(Path(vd.__file__).resolve().parents[1]),
           "WTS_PROFILE_DIR": str(tmp_path / "child-profile")}
    result = subprocess.run([sys.executable, "-c", code, str(partial), stage],
                            env=env, capture_output=True, timeout=20)
    assert result.returncode == 19, result.stderr.decode(errors="replace")
    info = vd.part_stat(partial, recover=True)
    assert info is not None and info.st_size == len(before)
    assert partial.read_bytes() == before
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(f".{name}.private-")]
    with vd.open_part(partial, len(before)) as stream:
        stream.write(b"tail")
    assert partial.read_bytes() == before + b"tail"


def test_unknown_preparation_records_are_not_cleanup_permission(tmp_path):
    partial = tmp_path / "download.part"
    partial.write_bytes(b"saved prefix")
    foreign = tmp_path / ".download.part.private-unknown"
    foreign.mkdir()
    (foreign / "state.json").write_text("[]", encoding="utf-8")
    (foreign / "prefix").write_bytes(b"unrelated original")
    vd.prepare_part(partial, 5)
    assert (foreign / "prefix").read_bytes() == b"unrelated original"


def test_recovery_survives_another_exit_during_no_hardlink_publication(tmp_path):
    partial = tmp_path / "download.part"
    before = b"complete saved prefix"
    partial.write_bytes(before)
    code = r'''
import errno,os,sys
from pathlib import Path
from core import verified_download as vd
part,stage=Path(sys.argv[1]),sys.argv[2]
if stage=='claim':
    vd._publish_part_exclusive=lambda *a,**kw:os._exit(19)
    vd.prepare_part(part,len(part.read_bytes()))
else:
    vd._PART_WINDOWS=False
    def unsupported(*args):raise OSError(errno.ENOTSUP,'synthetic unavailable hardlinks')
    copy=vd._copy_prefix
    def interrupted(reader,writer,size,check_cancel):
        if Path(writer.name)==part:
            writer.write(reader.read(3));writer.flush();os.fsync(writer.fileno());os._exit(19)
        return copy(reader,writer,size,check_cancel)
    os.link=unsupported;vd._copy_prefix=interrupted
    vd.part_stat(part,recover=True)
raise SystemExit('Forced-exit hook was not reached')
'''
    env = {**os.environ, "PYTHONPATH": str(Path(vd.__file__).resolve().parents[1]),
           "WTS_PROFILE_DIR": str(tmp_path / "child-profile")}
    for stage in ("claim", "recover"):
        result = subprocess.run([sys.executable, "-c", code, str(partial), stage],
                                env=env, capture_output=True, timeout=20)
        assert result.returncode == 19, result.stderr.decode(errors="replace")
    info = vd.part_stat(partial, recover=True)
    assert info is not None and info.st_size == len(before)
    assert partial.read_bytes() == before
    assert not list(tmp_path.glob(".download.part.private-*"))


def test_sweep_preserves_an_active_prefix_preparation(tmp_path):
    partial = tmp_path / "download.part"
    partial.write_bytes(b"saved prefix")
    ready = tmp_path / "ready"
    code = r'''
import sys,time
from pathlib import Path
from core import verified_download as vd
part,ready=map(Path,sys.argv[1:])
copy=vd._copy_prefix
def held(*args):
    copy(*args)
    ready.write_text('ready')
    assert sys.stdin.buffer.read(1)==b'x'
vd._copy_prefix=held
vd.prepare_part(part,5)
'''
    env = {**os.environ, "PYTHONPATH": str(Path(vd.__file__).resolve().parents[1]),
           "WTS_PROFILE_DIR": str(tmp_path / "child-profile")}
    process = subprocess.Popen([sys.executable, "-c", code, str(partial), str(ready)],
                               env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    try:
        import time
        deadline = time.monotonic() + 15
        while not ready.exists():
            assert process.poll() is None, "Preparation child exited before taking its lease"
            assert time.monotonic() < deadline, "Preparation child did not become ready"
            time.sleep(0.02)
        vd._sweep_private_parts(partial)
        assert len(list(tmp_path.glob(".download.part.private-*/prefix"))) == 1
        assert partial.read_bytes() == b"saved prefix"
        _, stderr = process.communicate(b"x", timeout=15)
        assert process.returncode == 0, stderr.decode(errors="replace")
        assert partial.read_bytes() == b"saved"
        assert not list(tmp_path.glob(".download.part.private-*"))
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)


@pytest.mark.parametrize("producer", ["verified", "manifest"])
def test_cancel_during_prefix_copy_preserves_original_before_http(tmp_path, monkeypatch, producer):
    import hashlib
    import threading

    data = b"complete model bytes\n" * 1024
    dest = tmp_path / "model.bin"
    partial = vd.part_path(dest)
    prefix = data[:513]
    partial.write_bytes(prefix)
    cancel = threading.Event()

    def cancelled(reader, writer, size, check_cancel):
        writer.write(reader.read(3))
        cancel.set()
        check_cancel()

    monkeypatch.setattr(vd, "_copy_prefix", cancelled)
    monkeypatch.setattr(vd.offline, "require_online", lambda *a: None)
    with Server(data=data) as server:
        if producer == "verified":
            with pytest.raises(vd.DownloadCancelled):
                vd.download_verified(server.url, dest, size=len(data),
                                     sha256=hashlib.sha256(data).hexdigest(),
                                     what="test model", cancel_event=cancel)
        else:
            assert not downloader(server.url).download("fixture/tiny", tmp_path,
                                                       entry(data), cancel_event=cancel)
        assert not server.gets
    assert partial.read_bytes() == prefix
    assert not dest.exists()
    assert not list(tmp_path.glob(".model.bin.part.private-*"))
