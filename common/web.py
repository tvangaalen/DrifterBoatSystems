"""HTTPS and the threading server shared by the stdlib servers (the gateway and drifterd's control API)."""
from __future__ import annotations

import ssl, sys
from http.server import ThreadingHTTPServer


class QuietServer(ThreadingHTTPServer):
    daemon_threads = True
    # The listen backlog (socketserver's default 5): a page load asks for the shell, its scripts and the first API reads at
    # once, and an iPhone and an iPad opening the app together got connections refused on Windows.
    request_queue_size = 64

    def handle_error(self, request, client_address):
        # Phones dropping connections and clients that do not trust the certificate are normal, not crashes.
        if isinstance(sys.exc_info()[1], (ssl.SSLError, ConnectionError, TimeoutError)): return
        super().handle_error(request, client_address)


def tls_context(certfile, keyfile) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile, keyfile); return ctx


def use_tls(server, ctx: ssl.SSLContext) -> None:
    """Serve HTTPS. The handshake runs in the request thread, not in accept(), so one slow client cannot block the others."""
    server.socket = ctx.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
