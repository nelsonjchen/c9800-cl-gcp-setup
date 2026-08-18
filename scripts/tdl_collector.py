#!/usr/bin/env python3
"""Small native Cisco MDT gRPC collector for TDL/YANG-Push demos.

Run with:

    uv run --with grpcio --with cisco-mdt scripts/tdl_collector.py \
      --port 57500 --output tdl.jsonl

The C9800 must use a ``grpc-tcp`` receiver pointed at this listener. This is
the Cisco MDT bidirectional gRPC protocol; it is not an HTTP webhook.
"""

import argparse
import json
import os
import signal
import sys
import threading
from concurrent import futures
from datetime import datetime, timezone

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

import grpc
from cisco_mdt import MDTgRPCServer, proto


SCALAR_FIELDS = (
    "string_value",
    "bool_value",
    "uint32_value",
    "uint64_value",
    "sint32_value",
    "sint64_value",
    "double_value",
    "float_value",
    "bytes_value",
)


def scalar_value(field):
    for attribute in SCALAR_FIELDS:
        if field.HasField(attribute):
            value = getattr(field, attribute)
            if attribute == "bytes_value":
                try:
                    return value.decode()
                except UnicodeDecodeError:
                    return value.hex()
            return value
    if field.timestamp:
        return field.timestamp
    return None


def add_value(container, name, value):
    if name in container:
        previous = container[name]
        if isinstance(previous, list):
            previous.append(value)
        else:
            container[name] = [previous, value]
    else:
        container[name] = value


def decode_fields(fields):
    named = {}
    unnamed = []
    for field in fields:
        value = scalar_value(field)
        if value is None and field.fields:
            value = decode_fields(field.fields)
        if field.name:
            add_value(named, field.name, value)
        else:
            unnamed.append(value)

    if named and not unnamed:
        return named
    if unnamed and not named:
        return unnamed
    if named and unnamed:
        named["_items"] = unnamed
        return named
    return None


def jsonable(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, bytes):
        try:
            return value.decode()
        except UnicodeDecodeError:
            return value.hex()
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return repr(value)


def iso_timestamp(timestamp_ns):
    if not timestamp_ns:
        return datetime.now(timezone.utc).isoformat()
    return datetime.fromtimestamp(timestamp_ns / 1_000_000_000, timezone.utc).isoformat()


class Collector:
    def __init__(self, output_path=None, path_prefix=None):
        self.output_path = output_path
        self.path_prefix = path_prefix
        self.output_lock = threading.Lock()
        self.output_file = open(output_path, "a", encoding="utf-8") if output_path else None

    def close(self):
        if self.output_file:
            self.output_file.close()

    def emit(self, event):
        line = json.dumps(jsonable(event), sort_keys=True)
        with self.output_lock:
            print(line, flush=True)
            if self.output_file:
                self.output_file.write(line + "\n")
                self.output_file.flush()

    def callback(self, request):
        if request.errors:
            self.emit(
                {
                    "received_at": datetime.now(timezone.utc).isoformat(),
                    "kind": "mdt_error",
                    "request_id": request.ReqId,
                    "errors": str(request.errors),
                }
            )
            return

        try:
            telemetry = proto.telemetry_bis_pb2.Telemetry()
            telemetry.ParseFromString(request.data)
            path = telemetry.encoding_path or ""
            if self.path_prefix and not path.startswith(self.path_prefix):
                return
            self.emit(
                {
                    "received_at": datetime.now(timezone.utc).isoformat(),
                    "kind": "mdt_update",
                    "request_id": request.ReqId,
                    "bytes": len(request.data),
                    "encoding_path": path,
                    "message_timestamp": iso_timestamp(telemetry.msg_timestamp),
                    "data": decode_fields(telemetry.data_gpbkv),
                }
            )
        except Exception as exc:  # keep the stream alive for one bad payload
            self.emit(
                {
                    "received_at": datetime.now(timezone.utc).isoformat(),
                    "kind": "mdt_parse_error",
                    "request_id": request.ReqId,
                    "bytes": len(request.data),
                    "error": repr(exc),
                }
            )


def build_server(port, collector):
    servicer = MDTgRPCServer()
    servicer.add_mdt_callback(collector.callback)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    proto.mdt_dialout_pb2_grpc.add_gRPCMdtDialoutServicer_to_server(servicer, server)
    server.add_insecure_port(f"[::]:{port}")
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=57500)
    parser.add_argument("--output", help="Optional JSONL output file")
    parser.add_argument(
        "--path-prefix",
        help="Optional encoding-path prefix to keep, such as /ewlc_oper/",
    )
    args = parser.parse_args()

    collector = Collector(args.output, args.path_prefix)
    server = build_server(args.port, collector)
    server.start()
    print(json.dumps({"kind": "startup", "port": args.port}), flush=True)

    stopped = threading.Event()

    def stop_handler(signum, frame):
        del signum, frame
        stopped.set()

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    try:
        stopped.wait()
    finally:
        server.stop(grace=2)
        collector.close()


if __name__ == "__main__":
    sys.exit(main())
