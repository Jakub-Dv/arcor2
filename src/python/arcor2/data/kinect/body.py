from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from dataclasses_jsonschema import JsonSchemaMixin


@dataclass
class BodyCount(JsonSchemaMixin):
    status: Optional[int] = None
    result: Optional[int] = None
    message: Optional[str] = None


__all__ = ["BodyCount"]
