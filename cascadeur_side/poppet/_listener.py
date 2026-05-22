"""Non-blocking TCP listener for Poppet, driven by QTimer inside Cascadeur's PySide event loop.

This is the file that solves the architectural risk flagged in the PDF spec §4
("a persistent, looping network socket halts user interface drawing cycles and
causes app hangs"). The pattern:

  - Bind a non-blocking listening socket.
  - Register a QTimer that fires every TICK_MS into Cascadeur's running Qt loop.
  - On each tick: accept new connections (non-blocking), drain partial reads
    from each connection, dispatch complete messages, write framed responses.

No threads. No blocking calls. The Qt loop stays responsive.

Tries PySide2 first (Cascadeur ships PySide2 in current builds), falls back to
PySide6 if a future version ships Qt 6.
"""

import socket

try:
    from PySide2 import QtCore  # type: ignore
except ImportError:  # pragma: no cover
    from PySide6 import QtCore  # type: ignore

from . import _framing
from ._dispatchers import dispatch


class _ConnState:
    """Per-connection read buffer + parse state."""

    def __init__(self, conn, addr):
        self.conn = conn
        self.addr = addr
        self.buf = b""
        self.want = None  # None = need 64-byte header; int = need N body bytes

    def drain_and_parse(self):
        """Pull all available bytes from the socket, yield complete messages."""
        try:
            while True:
                chunk = self.conn.recv(8192)
                if not chunk:
                    raise ConnectionResetError("peer closed")
                self.buf += chunk
        except BlockingIOError:
            pass

        messages = []
        while True:
            if self.want is None:
                if len(self.buf) < _framing.HEADER_LEN:
                    break
                try:
                    self.want = _framing.parse_header(self.buf[:_framing.HEADER_LEN])
                except Exception as e:
                    raise RuntimeError("bad header: {}".format(e))
                self.buf = self.buf[_framing.HEADER_LEN:]
            if len(self.buf) < self.want:
                break
            body = self.buf[:self.want]
            self.buf = self.buf[self.want:]
            self.want = None
            import json
            messages.append(json.loads(body.decode("utf-8")))
        return messages

    def send(self, message):
        self.conn.sendall(_framing.encode(message))

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


class PoppetListener(QtCore.QObject):
    """Singleton TCP listener wrapped in a QObject so QTimer can parent to it."""

    _instance = None

    def __init__(self, host, port, tick_ms, scene_provider):
        super(PoppetListener, self).__init__()
        self.host = host
        self.port = port
        self.tick_ms = tick_ms
        self.scene_provider = scene_provider
        self.listen_sock = None
        self.connections = []
        self.timer = None

    @classmethod
    def instance(cls):
        return cls._instance

    @classmethod
    def is_running(cls):
        return cls._instance is not None

    def start(self):
        if PoppetListener._instance is not None:
            raise RuntimeError("listener already running")
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setblocking(False)
        s.bind((self.host, self.port))
        s.listen(8)
        self.listen_sock = s
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(self.tick_ms)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        PoppetListener._instance = self
        print("[poppet] listener started on {}:{}".format(self.host, self.port))

    def stop(self):
        if self.timer is not None:
            self.timer.stop()
            self.timer.deleteLater()
            self.timer = None
        for c in self.connections:
            c.close()
        self.connections = []
        if self.listen_sock is not None:
            try:
                self.listen_sock.close()
            except Exception:
                pass
            self.listen_sock = None
        if PoppetListener._instance is self:
            PoppetListener._instance = None
        print("[poppet] listener stopped")

    def _tick(self):
        # 1. Accept any pending connections.
        try:
            while True:
                conn, addr = self.listen_sock.accept()
                conn.setblocking(False)
                self.connections.append(_ConnState(conn, addr))
                print("[poppet] accepted {}".format(addr))
        except BlockingIOError:
            pass
        except Exception as e:
            print("[poppet] accept error: {}".format(e))

        # 2. Drain each existing connection.
        for c in list(self.connections):
            try:
                messages = c.drain_and_parse()
            except (ConnectionResetError, ConnectionError):
                c.close()
                self.connections.remove(c)
                continue
            except Exception as e:
                try:
                    c.send({"status": "error", "message": "framing: {}".format(e)})
                except Exception:
                    pass
                c.close()
                self.connections.remove(c)
                continue

            for msg in messages:
                scene = self.scene_provider()
                response = dispatch(msg, scene)
                try:
                    c.send(response)
                except Exception:
                    c.close()
                    if c in self.connections:
                        self.connections.remove(c)
                    break
