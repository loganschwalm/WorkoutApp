"""Keeping connections from using the server up: a ceiling on how many are open at once, and deadlines on how long one may take to
send its request. Every connection holds a thread, and the socket's own timeout (REQUEST_TIMEOUT) only counts the silence between
bytes, which a client sending one byte at a time never lets run out."""

import socket
import threading
import time

from config import HEADER_TIMEOUT, MAX_CONNECTIONS, MIN_UPLOAD_RATE, REQUEST_BASE_TIME, REQUEST_MAX_TIME

BUSY = b'The server is busy. Try again.'
TURNED_AWAY = (b'HTTP/1.1 503 Service Unavailable\r\nRetry-After: 5\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: %d\r\n'
               b'Connection: close\r\n\r\n' % len(BUSY)) + BUSY


def request_allowance(content_length):
    """Seconds a request with a body of this many bytes may take from its headers to its answer: time for the body to arrive at
    MIN_UPLOAD_RATE, and for the server to answer, up to REQUEST_MAX_TIME."""
    try:
        size = max(0, int(content_length or 0))
    except ValueError:
        size = 0
    return min(REQUEST_MAX_TIME, REQUEST_BASE_TIME + size / MIN_UPLOAD_RATE)


class Connections:
    """The open connections: at most MAX_CONNECTIONS (0 for no limit), each with a deadline after which it is shut. The headers
    are due within HEADER_TIMEOUT of connecting, which a real client sends at once, so one that dribbles them in holds a thread
    for that long and no more; once they are read, the request is given the time its body needs (request_allowance)."""

    def __init__(self, ceiling=MAX_CONNECTIONS, header_timeout=HEADER_TIMEOUT):
        self.slots = threading.BoundedSemaphore(ceiling) if ceiling > 0 else None
        self.header_timeout = header_timeout
        self.deadlines = {}
        self.lock = threading.Lock()
        threading.Thread(target=self.close_overdue, name='connection-deadlines', daemon=True).start()

    def admit(self, sock):
        """Whether this new connection may be served: room under the ceiling. It then has until its headers are due."""
        if self.slots and not self.slots.acquire(blocking=False):
            return False
        self.extend(sock, self.header_timeout)
        return True

    def extend(self, sock, seconds):
        with self.lock:
            self.deadlines[sock] = time.monotonic() + seconds

    def release(self, sock):
        with self.lock:
            self.deadlines.pop(sock, None)
        if self.slots:
            self.slots.release()

    def close_overdue(self):
        while True:
            time.sleep(0.5)
            now = time.monotonic()
            with self.lock:
                overdue = [sock for sock, deadline in self.deadlines.items() if deadline <= now]
                for sock in overdue:
                    del self.deadlines[sock]
            for sock in overdue:
                try:
                    # Shut rather than closed: the thread reading it finds out and closes it itself, and no descriptor is freed
                    # (and perhaps handed to another connection) under it.
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass


# Connections being turned away at once, at most: past it a connection is simply closed, which a flood costs nothing to do.
turning_away = threading.BoundedSemaphore(32)


def turn_away(sock, close):
    """Tells a connection there is no room, and closes it with `close(sock)`. On a thread of its own for a moment, as it must
    wait for the request it sent: a socket closed with a request unread resets the connection, and the answer is lost with it."""
    if not turning_away.acquire(blocking=False):
        close(sock)
        return
    threading.Thread(target=answer_busy, args=(sock, close), daemon=True).start()


def answer_busy(sock, close):
    try:
        sock.settimeout(1)
        sock.sendall(TURNED_AWAY)
        sock.shutdown(socket.SHUT_WR)
        sock.recv(65536)
    except OSError:
        pass
    finally:
        close(sock)
        turning_away.release()
