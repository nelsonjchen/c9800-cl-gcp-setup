# Cloud Run Cisco MDT gRPC demo

This service is a minimal native gRPC receiver for Catalyst 9800 MDT
dial-out. It accepts Cisco `kvGPB` messages and writes one structured JSON
record per update to Cloud Run logs.

The WLC must use a `grpc-tls` receiver pointed at the Cloud Run service host
and port `443`; a normal HTTP `POST` endpoint is not compatible with the
Cisco MDT dial-out protocol.

For a local, no-cloud receiver that writes JSONL, use
`scripts/tdl_collector.py`:

```bash
uv run --with grpcio --with cisco-mdt scripts/tdl_collector.py \
  --port 57500 --output tdl.jsonl
```

That collector prints every decoded `encoding_path` and payload, which makes
it useful for validating a broad TDL subscription set before moving the
receiver behind TLS or Cloud Run.

The inventory and renderer for the Catalyst Center-style list are:

```bash
python3 scripts/render_tdl_config.py \
  configs/catalyst_center_tdl_inventory.json \
  --source-address 10.10.0.33 \
  --receiver-ip 10.10.0.35 \
  --include-notes
```

The renderer intentionally emits only the validated kvGPB/XPath demo
subscriptions. The controller also accepts the Catalyst Center native-TDL
form (`encode-tdl`, `stream native`, and `/services;serviceName=...`), but the
Cloud Run receiver above is not a native-TDL decoder. Use
`scripts/native_tdl_capture.py` to capture the native bytes while developing a
session-aware receiver.

This service is a minimal native gRPC receiver for Catalyst 9800 MDT
gRPC dial-out. It accepts Cisco `kvGPB` messages and writes one structured
JSON record per update to Cloud Run logs.

The WLC must use a `grpc-tls` receiver pointed at the Cloud Run service host
and port `443`; a normal HTTP `POST` endpoint is not compatible with the
Cisco MDT dial-out protocol.
