from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from arcor2_kinect_azure.aggregations import Direction
from dataclasses_jsonschema import JsonSchemaMixin


@dataclass
class DirectionModel(JsonSchemaMixin):
    x: Optional[float]
    y: Optional[float]
    z: Optional[float]
    horizontal_speed: Optional[float]
    vertical_speed: Optional[float]
    depth_speed: Optional[float]

    @classmethod
    def from_direction(cls, direction: Direction) -> DirectionModel:
        return cls(
            x=direction.x,
            y=direction.y,
            z=direction.z,
            horizontal_speed=direction.horizontal_speed,
            vertical_speed=direction.vertical_speed,
            depth_speed=direction.depth_speed,
        )


__all__ = ["DirectionModel"]
