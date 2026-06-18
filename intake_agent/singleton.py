"""Single-instance guard.

Prevents two copies (e.g. the autostart tray plus a hand-launched GUI) from
watching the same inbox and double-processing files. Implemented by binding a
loopback socket: the OS releases it automatically when the process exits, so
there are no stale lock files to clean up after a crash.
"""

from __future__ import annotations

import socket

_PORT = 49222  # arbitrary high port on loopback


class SingleInstance:
    def __init__(self, port: int = _PORT):
        self._port = port
        self._sock: socket.socket | None = None

    def acquire(self) -> bool:
        """Return True if we are the only instance; False if one is already running."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            s.bind(("127.0.0.1", self._port))
            s.listen(1)
            self._sock = s
            return True
        except OSError:
            s.close()
            return False

    def release(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None
