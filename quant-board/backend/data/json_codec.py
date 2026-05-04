from __future__ import annotations

import base64
import gzip
from typing import Any

from backend.utils import json_dumps, json_loads


COMPRESSED_TEXT_PREFIX = "__qb_gzip_b64__:"
DEFAULT_COMPRESSION_THRESHOLD = 4096


def dumps_json_field(value: Any, *, threshold: int = DEFAULT_COMPRESSION_THRESHOLD) -> str:
    text = value if isinstance(value, str) else json_dumps(value)
    if text.startswith(COMPRESSED_TEXT_PREFIX) or len(text.encode("utf-8")) <= threshold:
        return text
    compressed = gzip.compress(text.encode("utf-8"))
    encoded = base64.b64encode(compressed).decode("ascii")
    return f"{COMPRESSED_TEXT_PREFIX}{encoded}"


def loads_json_field(value: str | None, fallback: Any = None) -> Any:
    text = decompress_text_field(value)
    return json_loads(text, fallback)


def decompress_text_field(value: str | None) -> str:
    text = str(value or "")
    if not text.startswith(COMPRESSED_TEXT_PREFIX):
        return text
    encoded = text[len(COMPRESSED_TEXT_PREFIX) :]
    try:
        return gzip.decompress(base64.b64decode(encoded.encode("ascii"))).decode("utf-8")
    except Exception:
        return text


def compressed_length(value: Any, *, threshold: int = DEFAULT_COMPRESSION_THRESHOLD) -> int:
    return len(dumps_json_field(value, threshold=threshold).encode("utf-8"))
