#!/usr/bin/env python3
"""Start the local Duo web bridge over USB and, when enabled, Wi-Fi."""

import argparse
import ipaddress
import signal
import ssl
import threading
from contextlib import ExitStack
from http.server import ThreadingHTTPServer
from pathlib import Path

from bridge_http import make_handler
from codex_session import Codex


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument("--session-file", type=Path)
    parser.add_argument("--port", type=int, default=38457)
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--lan-ip", type=ipaddress.IPv4Address)
    parser.add_argument("--tls-cert", required=True, type=Path)
    parser.add_argument("--tls-key", required=True, type=Path)
    args = parser.parse_args()
    workspace = args.workspace.resolve(strict=True)
    token = args.token_file.read_text().strip()
    if not workspace.is_dir() or len(token) < 32:
        parser.error("缺少有效的工作目录或连接令牌")
    if args.lan_ip and (not args.lan_ip.is_private or args.lan_ip.is_loopback):
        parser.error("局域网连接需要本机私有 IPv4 地址")
    signal.signal(signal.SIGTERM, lambda *_: exit(0))
    with ExitStack() as cleanup:
        codex = Codex(workspace, args.codex, args.session_file)
        cleanup.callback(codex.close)
        handler = make_handler(codex, token)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(args.tls_cert, args.tls_key)
        def listen(host, port):
            server = cleanup.enter_context(ThreadingHTTPServer((host, port), handler))
            server.socket = context.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
            return server

        server = listen("127.0.0.1", args.port)
        if args.lan_ip:
            lan_server = listen(str(args.lan_ip), args.port + 1)
            threading.Thread(target=lan_server.serve_forever, name="duo-wifi", daemon=True).start()
            cleanup.callback(lan_server.shutdown)
        server.serve_forever()


if __name__ == "__main__":
    main()
