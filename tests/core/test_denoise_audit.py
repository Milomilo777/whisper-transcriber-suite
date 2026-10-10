import os
from core import denoise

def test_cache_key_audit_nfd_normalization(tmp_path, monkeypatch):
    # Hypothesis: _cache_key fails to normalize NFD paths, causing mismatches.
    path_nfc = str(tmp_path / "caf\u00e9.wav")
    path_nfd = str(tmp_path / "cafe\u0301.wav")
    with open(path_nfc, "wb") as f:
        f.write(b"data")
    # If the system natively creates the file at path_nfc, path_nfd might not work
    # on Linux (FileNotFoundError) inside _cache_key. We can monkeypatch os.stat.
    # We just want to check that the path hashed string is NFC normalized.
    orig_stat = os.stat
    def mock_stat(p, **kwargs):
        return orig_stat(path_nfc, **kwargs)
    
    monkeypatch.setattr(os, "stat", mock_stat)
    
    key_nfc = denoise._cache_key(path_nfc, "strong")
    key_nfd = denoise._cache_key(path_nfd, "strong")
    
    # Should assert they are equal once fixed.
    assert key_nfc == key_nfd

def test_sample_windows_audit_handles_inf():
    # Defect Hypothesis: sample_windows returns infinite start pos for inf duration.
    # Fixed to return [(0.0, 0.0)]
    assert denoise.sample_windows(float("inf")) == [(0.0, 0.0)]
    assert denoise.sample_windows(float("nan")) == [(0.0, 0.0)]

def test_denoise_audio_audit_fsync_durability(tmp_path, monkeypatch):
    # Defect Hypothesis: _apply_chain replaces files without fsyncing, which could lose data.
    # Let's mock os.fsync and check it gets called.
    fsync_called = []
    original_fsync = os.fsync
    def mock_fsync(fd):
        fsync_called.append(fd)
        original_fsync(fd)
    monkeypatch.setattr(os, "fsync", mock_fsync)
    
    # Run a mock denoise_audio
    monkeypatch.setattr(denoise, "is_available", lambda: True)
    def fake_analyze(*a, **kw):
        p = denoise.NoiseProfile(
            full=denoise.AudioStats(rms_level=-20, rms_peak=-10, noise_floor=-40, entropy=0.5),
            speech_band=denoise.AudioStats(rms_level=-20, rms_peak=-10, noise_floor=-40, entropy=0.5),
            snr_db=12.0, windows=1, window=(0, 0)
        )
        return p
    def fake_apply(src, dst, chain, **kw):
        with open(dst, "wb") as f:
            f.write(b"out")
        return True
    monkeypatch.setattr(denoise, "analyze", fake_analyze)
    monkeypatch.setattr(denoise, "_apply_chain", fake_apply)
    monkeypatch.setattr(denoise, "cache_dir", lambda: tmp_path)
    
    src = tmp_path / "in.wav"
    with open(src, "wb") as f:
        f.write(b"data")
    
    out = denoise.denoise_audio(str(src), duration_s=10.0, level="strong")
    assert len(fsync_called) > 0, "fsync was not called during replace"
    
    # Assert the returned path is actually in the cache dir, meaning it didn't just return the original src path early.
    assert out.startswith(str(tmp_path))
    assert out.endswith(".wav")
    assert out != str(src)
