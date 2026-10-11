import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from core.integrations import smtv_books
from core import offline

def test_find():
    assert smtv_books.find("From Crisis to Peace") is smtv_books.BOOKS[0]
    assert smtv_books.find("Nonexistent") is None

def test_cache_dir():
    assert isinstance(smtv_books.cache_dir(), Path)

def test_is_official():
    assert smtv_books._is_official("https://crisis2peace.org/book.jpg") is True
    assert smtv_books._is_official("https://smchbooks.com/book.jpg") is True
    assert smtv_books._is_official("http://crisis2peace.org/book.jpg") is False
    assert smtv_books._is_official("https://evil.com/book.jpg") is False

def test_fetch_cover_caching(tmp_path, monkeypatch):
    monkeypatch.setattr(smtv_books, "cache_dir", lambda: tmp_path)
    book = smtv_books.BOOKS[0]
    cache_file = tmp_path / f"{book.key}.jpg"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_bytes(b"\xff\xd8\xff\x00\x00")
    
    # Cache hit
    data = smtv_books.fetch_cover(book)
    assert data == b"\xff\xd8\xff\x00\x00"

def test_fetch_cover_network(tmp_path, monkeypatch):
    monkeypatch.setattr(smtv_books, "cache_dir", lambda: tmp_path)
    book = smtv_books.BOOKS[0]
    
    # Network hit
    mock_response = MagicMock()
    mock_response.read.return_value = b"\xff\xd8\xffimage_data"
    mock_response.headers.get.return_value = "image/jpeg"
    
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_response
        data = smtv_books.fetch_cover(book)
        assert data == b"\xff\xd8\xffimage_data"
        assert (tmp_path / f"{book.key}.jpg").exists()

def test_fetch_cover_offline_with_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(smtv_books, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(offline, "is_offline", lambda: True)
    book = smtv_books.BOOKS[0]
    
    cache_file = tmp_path / f"{book.key}.jpg"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_bytes(b"\xff\xd8\xffcached")
    
    # Should read from cache without network
    assert smtv_books.fetch_cover(book) == b"\xff\xd8\xffcached"

def test_fetch_cover_offline_without_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(smtv_books, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(offline, "is_offline", lambda: True)
    book = smtv_books.BOOKS[0]
    
    with pytest.raises(offline.OfflineModeError):
        smtv_books.fetch_cover(book)

def test_fetch_cover_too_large(tmp_path, monkeypatch):
    monkeypatch.setattr(smtv_books, "cache_dir", lambda: tmp_path)
    book = smtv_books.BOOKS[0]
    
    mock_response = MagicMock()
    mock_response.read.return_value = b"x" * 2_000_001
    mock_response.headers.get.return_value = "image/jpeg"
    
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_response
        with pytest.raises(smtv_books.BookCoverError, match="too large"):
            smtv_books.fetch_cover(book)

def test_fetch_cover_not_an_image(tmp_path, monkeypatch):
    monkeypatch.setattr(smtv_books, "cache_dir", lambda: tmp_path)
    book = smtv_books.BOOKS[0]
    
    mock_response = MagicMock()
    mock_response.read.return_value = b"<html></html>"
    mock_response.headers.get.return_value = "text/html"
    
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_response
        with pytest.raises(smtv_books.BookCoverError, match="not a picture"):
            smtv_books.fetch_cover(book)

def test_fetch_cover_unofficial_url():
    bad_book = smtv_books.Book("bad", "Bad", "", "", "", (), "http://evil.com/img.jpg", (), "")
    with pytest.raises(smtv_books.BookCoverError, match="official book site"):
        smtv_books.fetch_cover(bad_book)
