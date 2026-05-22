"""Cascadeur command: Poppet → POC Tick Loop.

Architectural verification — proves QTimer + non-blocking socket + PySide event
loop don't freeze Cascadeur's UI. Run this first on a fresh install.

Behavior:
  - Binds a non-blocking socket on 127.0.0.1:53145 (collides with the real
    server if both are running — stop the real server first).
  - Logs a tick every 50ms (visible by 'tick=20' messages every second).
  - When a peer connects (e.g. `nc 127.0.0.1 53145`), sends "poppet-poc tick=N"
    and closes the connection.
  - Re-run the command to stop.

Pass criteria: viewport stays responsive (rotate, drag, click controllers) for
60+ seconds while the POC is running and a peer is connected.
"""

import socket

try:
    from PySide2 import QtCore  # type: ignore
except ImportError:  # pragma: no cover
    from PySide6 import QtCore  # type: ignore


PORT = 53145
TICK_MS = 50
LOG_EVERY = 20  # log once per second


# Module-level state so re-running run() toggles.
_state = {"timer": None, "sock": None, "ticks": 0}


def command_name():
    return "Poppet.POC Tick Loop"


def run(scene):
    if _state["timer"] is not None:
        _stop()
    else:
        _start()


def _start():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setblocking(False)
    try:
        s.bind(("127.0.0.1", PORT))
    except OSError as e:
        print("[poppet-poc] bind failed (port {} in use?): {}".format(PORT, e))
        s.close()
        return
    s.listen(4)
    _state["sock"] = s
    _state["ticks"] = 0

    t = QtCore.QTimer()
    t.setInterval(TICK_MS)
    t.timeout.connect(_tick)
    t.start()
    _state["timer"] = t

    print("[poppet-poc] started on 127.0.0.1:{} — viewport should stay responsive.".format(PORT))
    print("[poppet-poc] connect with: nc 127.0.0.1 {}    (or any TCP client)".format(PORT))
    print("[poppet-poc] re-run the command to stop")


def _stop():
    if _state["timer"] is not None:
        _state["timer"].stop()
        _state["timer"].deleteLater()
    if _state["sock"] is not None:
        try:
            _state["sock"].close()
        except Exception:
            pass
    _state["timer"] = None
    _state["sock"] = None
    print("[poppet-poc] stopped after {} ticks".format(_state["ticks"]))
    _state["ticks"] = 0


def _tick():
    _state["ticks"] += 1
    sock = _state["sock"]
    if sock is not None:
        try:
            conn, addr = sock.accept()
            try:
                msg = "poppet-poc tick={}\n".format(_state["ticks"]).encode("ascii")
                conn.sendall(msg)
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
            print("[poppet-poc] served {}".format(addr))
        except BlockingIOError:
            pass
        except Exception as e:
            print("[poppet-poc] accept error: {}".format(e))

    if _state["ticks"] % LOG_EVERY == 0:
        print("[poppet-poc] tick={} (UI should be responsive)".format(_state["ticks"]))
