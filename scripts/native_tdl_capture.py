#!/usr/bin/env python3
"""Capture Cisco native-TDL bytes without pretending to decode the wire format.

Catalyst Center's ``encode-tdl`` / ``stream native`` payload is not kvGPB.
This utility is deliberately a transparent lab capture endpoint: it accepts
TCP or TLS, records every received chunk as JSONL, and keeps the raw bytes so
the native session framing can be inspected or decoded later.
"""

import argparse
import base64
import hashlib
import json
import socket
import ssl
import threading
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def write_event(output, event):
    with output.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, sort_keys=True) + "\n")
        stream.flush()


def serve_connection(connection, peer, output, tls_enabled):
    connection.settimeout(60)
    connection_event = {
        "kind": "connection",
        "received_at": now(),
        "peer": f"{peer[0]}:{peer[1]}",
        "tls": tls_enabled,
    }
    write_event(output, connection_event)
    try:
        chunk_number = 0
        while True:
            payload = connection.recv(1024 * 1024)
            if not payload:
                break
            chunk_number += 1
            event = {
                "kind": "native_tdl_chunk",
                "received_at": now(),
                "peer": f"{peer[0]}:{peer[1]}",
                "chunk": chunk_number,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "base64": base64.b64encode(payload).decode("ascii"),
            }
            write_event(output, event)
    except (ConnectionError, OSError, socket.timeout) as exc:
        write_event(
            output,
            {
                "kind": "connection_error",
                "received_at": now(),
                "peer": f"{peer[0]}:{peer[1]}",
                "error": repr(exc),
            },
        )
    finally:
        try:
            connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        connection.close()
        write_event(
            output,
            {
                "kind": "disconnect",
                "received_at": now(),
                "peer": f"{peer[0]}:{peer[1]}",
            },
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=25104)
    parser.add_argument("--output", type=Path, default=Path("native-tdl.jsonl"))
    parser.add_argument("--tls", action="store_true")
    parser.add_argument("--certfile", type=Path)
    parser.add_argument("--keyfile", type=Path)
    parser.add_argument("--cafile", type=Path)
    parser.add_argument("--require-client-cert", action="store_true")
    args = parser.parse_args()

    if args.tls and (not args.certfile or not args.keyfile):
        parser.error("--tls requires --certfile and --keyfile")
    if args.require_client_cert and not args.cafile:
        parser.error("--require-client-cert requires --cafile")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    tls_context = None
    if args.tls:
        tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        # C9800 native-TLS sessions use TLS 1.2 in the Catalyst Center
        # examples and on the 17.15 lab image.
        tls_context.minimum_version = ssl.TLSVersion.TLSv1_2
        tls_context.maximum_version = ssl.TLSVersion.TLSv1_2
        tls_context.load_cert_chain(str(args.certfile), str(args.keyfile))
        if args.cafile:
            tls_context.load_verify_locations(cafile=str(args.cafile))
        tls_context.verify_mode = (
            ssl.CERT_REQUIRED if args.require_client_cert else ssl.CERT_NONE
        )

    with socket.create_server((args.host, args.port), reuse_port=True) as server:
        print(
            json.dumps(
                {
                    "kind": "startup",
                    "host": args.host,
                    "port": args.port,
                    "tls": args.tls,
                    "output": str(args.output),
                },
                sort_keys=True,
            ),
            flush=True,
        )
        while True:
            raw_connection, peer = server.accept()
            connection = raw_connection
            if tls_context:
                try:
                    connection = tls_context.wrap_socket(raw_connection, server_side=True)
                except ssl.SSLError as exc:
                    write_event(
                        args.output,
                        {
                            "kind": "tls_error",
                            "received_at": now(),
                            "peer": f"{peer[0]}:{peer[1]}",
                            "error": repr(exc),
                        },
                    )
                    raw_connection.close()
                    continue
            threading.Thread(
                target=serve_connection,
                args=(connection, peer, args.output, bool(tls_context)),
                daemon=True,
            ).start()


if __name__ == "__main__":
    main()
