from __future__ import annotations

import json
from typing import BinaryIO


def write_message(stream: BinaryIO, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
    stream.write(header)
    stream.write(body)
    stream.flush()


def read_message(stream: BinaryIO) -> dict | None:
    header = b""
    while b"\r\n\r\n" not in header:
        chunk = stream.read(1)
        if not chunk:
            return None
        header += chunk
    header_text = header.decode("utf-8")
    for line in header_text.split("\r\n"):
        if line.lower().startswith("content-length:"):
            length = int(line.split(":", 1)[1].strip())
            body = stream.read(length)
            return json.loads(body.decode("utf-8"))
    raise ValueError("Missing Content-Length header.")

