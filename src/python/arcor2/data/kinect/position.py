from dataclasses import dataclass

from dataclasses_jsonschema import JsonSchemaMixin

from arcor2.data.kinect.joint import BodyJoint


@dataclass
class Position(JsonSchemaMixin):
    result: BodyJoint
    message: str


__all__ = ["Position"]
