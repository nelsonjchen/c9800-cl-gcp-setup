#!/usr/bin/env python3
"""Minimal Cloud Run receiver for Cisco Catalyst MDT gRPC dial-out."""

import json
import os
import signal
import threading
import time
from concurrent import futures
from datetime import datetime, timezone

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

import grpc
from cisco_mdt import MDTgRPCServer, proto


def scalar_value(field):
    for attribute in (
        "string_value",
        "bool_value",
        "uint32_value",
        "uint64_value",
        "sint32_value",
        "sint64_value",
        "double_value",
        "float_value",
        "bytes_value",
    ):
        if field.HasField(attribute):
            value = getattr(field, attribute)
            if attribute == "bytes_value":
                try:
                    return value.decode()
                except Exception:
                    return value.hex()
            return value
    if field.timestamp:
        return str(field.timestamp)
    return None


def field_names(fields):
    names = []
    for field in fields:
        if field.name:
            names.append(field.name)
        if field.fields:
            names.extend(field_names(field.fields))
    return names


def field_value(field):
    value = scalar_value(field)
    if value is not None:
        return value
    if field.fields:
        children = [field_value(child) for child in field.fields]
        if field.name:
            return {field.name: children}
        return children
    return None


def received_at():
    return datetime.now(timezone.utc).isoformat()


class CloudRunPrinter:
    def callback(self, request):
        if request.errors:
            print(
                json.dumps(
                    {
                        "received_at": received_at(),
                        "kind": "mdt_error",
                        "request_id": request.ReqId,
                        "errors": str(request.errors),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            return

        try:
            telemetry = proto.telemetry_bis_pb2.Telemetry()
            telemetry.ParseFromString(request.data)
            data = [field_value(field) for field in telemetry.data_gpbkv]
            event = {
                "received_at": received_at(),
                "kind": "mdt_update",
                "request_id": request.ReqId,
                "bytes": len(request.data),
                "encoding_path": telemetry.encoding_path,
                "message_timestamp_ns": telemetry.msg_timestamp,
                "field_names": field_names(telemetry.data_gpbkv),
                "data": data,
            }
            print(json.dumps(event, default=str, sort_keys=True), flush=True)
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "received_at": received_at(),
                        "kind": "mdt_parse_error",
                        "request_id": request.ReqId,
                        "bytes": len(request.data),
                        "error": repr(exc),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )


def build_server(port, printer):
    servicer = MDTgRPCServer()
    servicer.add_mdt_callback(printer.callback)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    proto.mdt_dialout_pb2_grpc.add_gRPCMdtDialoutServicer_to_server(servicer, server)
    server.add_insecure_port(f"[::]:{port}")
    return server


def main():
    port = int(os.environ.get("PORT", "8080"))
    server = build_server(port, CloudRunPrinter())
    server.start()
    print(json.dumps({"kind": "startup", "port": port}), flush=True)

    stop_event = threading.Event()

    def stop_handler(signum, frame):
        del signum, frame
        stop_event.set()

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    finally:
        server.stop(grace=2)


if __name__ == "__main__":
    main()
