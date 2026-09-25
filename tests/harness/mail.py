"""A stand-in mail server that keeps what it is sent, so tests can read the password reset codes."""

import email
import email.policy
import re
import socketserver
import threading
import time


class MailSink:
    """Speaks just enough SMTP for the app's smtplib to deliver a message, and keeps every message it receives.

    Pass `env` to a server to send its reset emails here (plain SMTP, no login).
    """

    def __init__(self):
        self.messages = []
        sink = self

        class Session(socketserver.StreamRequestHandler):
            def reply(self, line):
                self.wfile.write(line.encode() + b'\r\n')

            def handle(self):
                self.reply('220 sink ready')
                while True:
                    line = self.rfile.readline()
                    if not line:
                        return
                    verb = line[:4].decode('ascii', 'replace').upper()
                    if verb == 'DATA':
                        self.reply('354 end with a line holding only a dot')
                        lines = []
                        while True:
                            line = self.rfile.readline()
                            if not line or line in (b'.\r\n', b'.\n'):
                                break
                            # The sender doubles a leading dot so a line of one dot cannot end the message early.
                            lines.append(line[1:] if line.startswith(b'.') else line)
                        sink.messages.append(email.message_from_bytes(b''.join(lines), policy=email.policy.default))
                        self.reply('250 kept')
                    elif verb == 'QUIT':
                        self.reply('221 bye')
                        return
                    elif verb in ('EHLO', 'HELO', 'MAIL', 'RCPT', 'RSET', 'NOOP'):
                        self.reply('250 ok')
                    else:
                        self.reply('502 not implemented')

        self.server = socketserver.ThreadingTCPServer(('127.0.0.1', 0), Session)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.env = {'SMTP_HOST': '127.0.0.1', 'SMTP_PORT': str(self.port), 'SMTP_SECURITY': 'none',
                    'SMTP_FROM': 'Workout Tracker <tracker@example.test>'}
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def to(self, address):
        """Every message sent to this address so far, oldest first."""
        return [message for message in list(self.messages) if message['To'] == address]

    def wait(self, address, count, timeout=10, poll=None):
        """The newest message to `address` once it has had `count`, or None after `timeout` seconds.

        `poll` is called while waiting instead of sleeping; a browser test passes `cdp.pause` so the page keeps running.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            received = self.to(address)
            if len(received) >= count:
                return received[-1]
            (poll or time.sleep)(0.2)
        return None

    @staticmethod
    def code(message):
        """The 6-digit code in a reset email, or None."""
        found = re.search(r'\b(\d{6})\b', message.get_content()) if message else None
        return found.group(1) if found else None

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
