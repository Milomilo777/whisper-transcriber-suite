"""Real loopback CONNECT and TLS; no external model or trust-store change."""
import socket
import ssl
import threading
import time

import pytest

from core import model_download
from core.server.tls import generate_self_signed_cert


@pytest.fixture
def proxy_request(tmp_path, monkeypatch):
    cert, key = tmp_path / "certificate.pem", tmp_path / "key.pem"
    generate_self_signed_cert(cert, key, hosts=["model.test"])
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(str(cert), str(key))
    original_wrap = ssl.SSLContext.wrap_socket

    def exercise(delay=0, *, host="model.test", trust=True):
        client_context = (ssl.create_default_context(cafile=str(cert)) if trust
                          else ssl.create_default_context())
        assert client_context.verify_mode == ssl.CERT_REQUIRED
        assert client_context.check_hostname
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(3)
        address = listener.getsockname()
        stop = threading.Event()
        sockets, received, observed = [], [], []
        payload = b"controlled model bytes"

        def headers(sock):
            data = b""
            while not data.endswith(b"\r\n\r\n"):
                part = sock.recv(4096)
                if not part:
                    raise EOFError("client closed request")
                data += part
                assert len(data) <= 16384
            return data.decode("ascii")

        def serve():
            try:
                raw, _ = listener.accept()
                sockets.append(raw)
                raw.settimeout(3)
                received.append(headers(raw))
                raw.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                if stop.wait(delay):
                    return
                with server_context.wrap_socket(raw, server_side=True) as secure:
                    sockets.append(secure)
                    received.append(headers(secure))
                    secure.sendall(b"HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: "
                                   + str(len(payload)).encode()
                                   + b"\r\n\r\n" + payload)
            except (OSError, EOFError):
                # Rejected certificates and the causal timeout close the peer.
                pass
            finally:
                for sock in reversed(sockets):
                    sock.close()
                listener.close()

        def wrap(context, sock, *args, **kwargs):
            if context is client_context:
                observed.append(sock.gettimeout())
            return original_wrap(context, sock, *args, **kwargs)

        thread = threading.Thread(target=serve)
        thread.start()
        result = error = None
        started = time.monotonic()
        try:
            with monkeypatch.context() as patch:
                patch.setattr("urllib.request.getproxies",
                              lambda: {"https": f"http://{address[0]}:{address[1]}"})
                patch.setattr("urllib.request.proxy_bypass", lambda host: False)
                patch.setattr("ssl._create_default_https_context", lambda: client_context)
                patch.setattr(ssl.SSLContext, "wrap_socket", wrap)
                downloader = model_download.ModelDownloader(stall_timeout=3, retry_delays=())
                with downloader._open(f"https://{host}/model.bin", {}, None) as response:
                    result = response.read()
        except Exception as caught:
            error = caught
        finally:
            stop.set()
            thread.join(4)
            if thread.is_alive():
                for sock in sockets:
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                listener.close()
                thread.join(4)
            assert not thread.is_alive()
        assert received and received[0].startswith(f"CONNECT {host}:443 ")
        return result, error, observed, time.monotonic() - started

    return exercise


@pytest.mark.parametrize("delay", [0, 0.35])
def test_proxy_tls_accepts_a_handshake_within_configured_timeout(proxy_request, delay):
    result, error, _, _ = proxy_request(delay)
    assert error is None, error
    assert result == b"controlled model bytes"


def test_connect_restores_socket_timeout_before_tls(proxy_request):
    result, error, observed, _ = proxy_request()
    assert error is None, error
    assert result == b"controlled model bytes"
    assert observed == [3]


def test_proxy_keeps_hostname_verification(proxy_request):
    _, error, _, _ = proxy_request(host="wrong.test")
    assert error is not None and "CERTIFICATE_VERIFY_FAILED" in str(error)


def test_proxy_rejects_untrusted_certificate(proxy_request):
    _, error, _, _ = proxy_request(trust=False)
    assert error is not None and "CERTIFICATE_VERIFY_FAILED" in str(error)
