"""穩定的 JSON 序列化與摘要：鍵排序後再序列化，摘要不受鍵順序影響。"""

import hashlib
import json
from typing import Any


def canonical_json(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(v: Any) -> str:
    return hashlib.sha256(canonical_json(v).encode("utf-8")).hexdigest()
