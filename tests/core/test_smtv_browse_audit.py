import pytest
import urllib.error
from unittest.mock import patch, MagicMock
from core.integrations import smtv_browse
from core import offline

def test_language_label():
    assert smtv_browse.language_label("en") == "English"
    assert smtv_browse.language_label("fr") == "Français"
    assert smtv_browse.language_label("unknown") == "unknown"

def test_code_for_label():
    assert smtv_browse.code_for_label("English") == "en"
    assert smtv_browse.code_for_label("Français") == "fr"
    assert smtv_browse.code_for_label("French") == "fr"
    assert smtv_browse.code_for_label("unknown") == "en"

def test_page_url():
    assert smtv_browse.page_url("en", "search/") == "https://suprememastertv.com/en1/search/"
    assert smtv_browse.page_url("fr", "search/") == "https://suprememastertv.com/fr1/search/"
    assert smtv_browse.page_url("unknown", "search/") == "https://suprememastertv.com/en1/search/"

def test_search_offline(monkeypatch):
    monkeypatch.setattr(offline, "is_offline", lambda: True)
    with pytest.raises(smtv_browse.SmtvBrowseError, match="Offline"):
        smtv_browse.search()

def test_search_success():
    html_fragment = '''<div class="nums">1 to 20 of 100</div>
    <div class="sbox"><h3 class="title"><a href="../v/123.html">Title 1</a></h3>
    <span class="length">10:00</span></div>
    '''
    mock_response = MagicMock()
    mock_response.read.return_value = html_fragment.encode("utf-8")
    
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_response
        result = smtv_browse.search(page=2)
        assert result.page == 2
        assert result.total == 100
        assert len(result.items) == 1
        assert result.items[0].url == "https://suprememastertv.com/en1/v/123.html"
        assert result.items[0].duration == "10:00"

def test_search_network_error():
    with patch("urllib.request.urlopen") as mock_urlopen:
        # Generate an HTTPError to check if it's caught and (soon) closed
        fp_mock = MagicMock()
        err = urllib.error.HTTPError("url", 500, "Error", {}, fp_mock)
        mock_urlopen.side_effect = err
        
        with pytest.raises(smtv_browse.SmtvBrowseError):
            smtv_browse.search()
        assert fp_mock.close.called

def test_fetch_bytes_offline(monkeypatch):
    monkeypatch.setattr(offline, "is_offline", lambda: True)
    with pytest.raises(smtv_browse.SmtvBrowseError, match="Offline"):
        smtv_browse.fetch_bytes("https://suprememastertv.com/img.jpg")

def test_fetch_bytes_bad_url():
    with pytest.raises(smtv_browse.SmtvBrowseError, match="Refusing"):
        smtv_browse.fetch_bytes("https://evil.com/img.jpg")

def test_fetch_bytes_success():
    mock_response = MagicMock()
    mock_response.read.return_value = b"image_data"
    
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_response
        data = smtv_browse.fetch_bytes("https://suprememastertv.com/img.jpg")
        assert data == b"image_data"

def test_fetch_bytes_network_error():
    with patch("urllib.request.urlopen") as mock_urlopen:
        fp_mock = MagicMock()
        err = urllib.error.HTTPError("url", 404, "Not Found", {}, fp_mock)
        mock_urlopen.side_effect = err
        
        with pytest.raises(urllib.error.HTTPError):
            smtv_browse.fetch_bytes("https://suprememastertv.com/img.jpg")
        assert fp_mock.close.called
