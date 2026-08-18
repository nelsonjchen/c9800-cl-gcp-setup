#!/usr/bin/env python3
"""Render supported XPath MDT subscriptions from the TDL inventory."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--source-address", required=True)
    parser.add_argument("--receiver-ip", required=True)
    parser.add_argument("--receiver-port", type=int, default=57500)
    parser.add_argument("--include-notes", action="store_true")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if args.include_notes:
        print("! TDL URI inventory is retained in the manifest for mapping.")
        print(f"! Controller compatibility: {manifest['compatibility']['tdl_uri_filter']}")
        print("! Only validated XPath equivalents are rendered as active CLI.")

    for item in manifest["validated_xpath_equivalents"]:
        print(f"telemetry ietf subscription {item['subscription_id']}")
        print(" encoding encode-kvgpb")
        print(f" filter xpath {item['xpath']}")
        print(f" source-address {args.source_address}")
        print(" stream yang-push")
        if item["policy"] == "on-change":
            print(" update-policy on-change")
        else:
            print(f" update-policy periodic {item['period_ms']}")
        print(
            f" receiver ip address {args.receiver_ip} {args.receiver_port} "
            "protocol grpc-tcp"
        )
        print("!")


if __name__ == "__main__":
    main()
