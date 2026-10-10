import core.watcher as watcher

def test_watch_skip_reason_returns_empty_string_for_new_file():
    assert watcher.watch_skip_reason("test.mp4") == ""

def test_watch_skip_reason_returns_reason_for_burn_temp():
    assert watcher.watch_skip_reason(".burn-temp-file.mp4") == "a subtitle burn's temporary file"

def test_is_inside_handles_unicode():
    assert watcher._is_inside("/folder", b"/folder/unicode_\xe2\x98\x83.mp4")
    assert watcher._is_inside("/folder", "/folder/unicode_\u2603.mp4")

def test_is_inside_handles_outside():
    assert not watcher._is_inside("/folder", "/outside.mp4")

def test_is_inside_handles_parent():
    assert not watcher._is_inside("/folder/sub", "/folder/outside.mp4")

def test_is_inside_handles_nfd_nfc_mismatch():
    import unicodedata
    folder = "/tmp/Café"
    path = "/tmp/Café/video.mp4"
    folder_nfc = unicodedata.normalize('NFC', folder)
    path_nfd = unicodedata.normalize('NFD', path)
    assert watcher._is_inside(folder_nfc, path_nfd)
