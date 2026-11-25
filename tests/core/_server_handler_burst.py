"""Observe every connection decision and handler in a loopback burst."""
import socketserver
import threading
import time


class HandlerBurst:
    def __init__(self, monkeypatch, server_type, connections):
        self._changed = threading.Condition()
        self._connections = connections
        self._processed = 0
        self._dispatched = 0
        self._finished = 0
        self._live = 0
        self.peak = 0
        process = server_type.process_request
        dispatch = socketserver.ThreadingMixIn.process_request
        handle = server_type.process_request_thread
        release = server_type._release_slot

        def process_request(server, request, address):
            try:
                return process(server, request, address)
            finally:
                with self._changed:
                    self._processed += 1
                    self._changed.notify_all()

        def dispatch_request(server, request, address):
            if isinstance(server, server_type):
                with self._changed:
                    self._dispatched += 1
            return dispatch(server, request, address)

        def handle_request(server, request, address):
            with self._changed:
                self._live += 1
                self.peak = max(self.peak, self._live)
            try:
                return handle(server, request, address)
            finally:
                with self._changed:
                    self._live -= 1
                    self._finished += 1
                    self._changed.notify_all()

        def release_slot(server, *args):
            # Stretch the overlap between evicted handlers and replacements.
            time.sleep(0.4)
            return release(server, *args)

        monkeypatch.setattr(server_type, "process_request", process_request)
        monkeypatch.setattr(socketserver.ThreadingMixIn, "process_request", dispatch_request)
        monkeypatch.setattr(server_type, "process_request_thread", handle_request)
        monkeypatch.setattr(server_type, "_release_slot", release_slot)

    def wait_processed(self):
        with self._changed:
            assert self._changed.wait_for(lambda: self._processed == self._connections, timeout=10)

    def wait_finished(self):
        with self._changed:
            assert self._changed.wait_for(lambda: self._finished == self._dispatched, timeout=10)
