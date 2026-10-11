import pytest
import urllib.error
from unittest.mock import patch, MagicMock
from core.integrations import smtv
from core import offline

def test_clean_url():
    assert smtv.clean_url("  \u200bhttps://suprememastertv.com/\u200f ") == "https://suprememastertv.com/"

def test_is_smtv_url():
    assert smtv.is_smtv_url("https://suprememastertv.com/en1/v/123.html") is True
    assert smtv.is_smtv_url("https://www.suprememastertv.com/") is True
    assert smtv.is_smtv_url("http://evil.com/") is False

def test_parse_episode_id():
    assert smtv.parse_episode_id("https://suprememastertv.com/en1/v/123456.html") == ("en", "123456")
    assert smtv.parse_episode_id("https://suprememastertv.com/en1/v/12.html") is None

def test_fetch_episode_offline(monkeypatch):
    monkeypatch.setattr(offline, "is_offline", lambda: True)
    with pytest.raises(smtv.SmtvError, match="Offline"):
        smtv.fetch_episode("https://suprememastertv.com/en1/v/123456.html")

def test_fetch_episode_network_error():
    with patch("urllib.request.urlopen") as mock_urlopen:
        fp_mock = MagicMock()
        err = urllib.error.HTTPError("url", 404, "Not Found", {}, fp_mock)
        mock_urlopen.side_effect = err
        
        with pytest.raises(smtv.SmtvError, match="HTTP 404"):
            smtv.fetch_episode("https://suprememastertv.com/en1/v/123456.html")
        assert fp_mock.close.called

def test_best_url_for_mode():
    episode = smtv.SmtvEpisode(
        vid="123",
        title="Title",
        page_url="url",
        lang_prefix="en",
        files=[
            smtv.SmtvFile(quality="audio", relative_path="a.mp3", download_url="http://a"),
            smtv.SmtvFile(quality="1080p", relative_path="v.mp4", download_url="http://v")
        ]
    )
    assert smtv.best_url_for_mode(episode, "audio") == "http://a"
    assert smtv.best_url_for_mode(episode, "video-best") == "http://v"
    
    with pytest.raises(smtv.SmtvError, match="no video file"):
        smtv.best_url_for_mode(smtv.SmtvEpisode("1", "T", "U", "e", []), "video-best")

def test_sanitise_filename():
    assert smtv._sanitise_filename("A/B\\C:D*E?F\"G<H>I|J") == "A_B_C_D_E_F_G_H_I_J"
    assert smtv._sanitise_filename("CON") == "_CON"
    # Ensure ? is stripped out
    assert not set('<>:"/\\|?*') & set(smtv._sanitise_filename('a\ud800b?c'))

def test_warn_time_range_unsupported(caplog):
    smtv.warn_time_range_unsupported("http://url")
    assert "Time-range download is not supported" in caplog.text

