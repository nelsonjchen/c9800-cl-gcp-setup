#!/usr/bin/env python2
"""
Minimal custom-data decoder for lab debugging.

Cisco's raw GCP qcow2 path invokes:
    python decode-custom-data.py <input> <decoded> <processed>

On the lab image, the stock decoder crashed because it imported a
missing internal module, `bootstrap_app`. This shim preserves the same
interface and copies the incoming payload into the expected outputs.
It also appends the payload into /varied/iosxe_config.txt so the first
boot config path has something usable to consume.
"""

import io
import os
import sys


def mkdirp(path):
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)


def main(argv):
    if len(argv) != 4:
        sys.stderr.write(
            "usage: decode-custom-data.py <input> <decoded> <processed>\n"
        )
        return 2

    src, decoded_path, processed_path = argv[1:]

    with io.open(src, "rb") as fh:
        payload = fh.read()

    for dest in (decoded_path, processed_path):
        mkdirp(dest)
        with io.open(dest, "wb") as fh:
            fh.write(payload)

    iosxe_config = "/varied/iosxe_config.txt"
    mkdirp(iosxe_config)
    with io.open(iosxe_config, "ab") as fh:
        if payload and not payload.endswith(b"\n"):
            payload += b"\n"
        fh.write(payload)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
