from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

import numpy as np
from dataclasses_jsonschema import JsonSchemaMixin

from arcor2.logging import get_logger

log = get_logger(__name__)


class JointId(IntEnum):
    PELVIS = 0
    SPINE_NAVEL = 1
    SPINE_CHEST = 2
    NECK = 3
    CLAVICLE_LEFT = 4
    SHOULDER_LEFT = 5
    ELBOW_LEFT = 6
    WRIST_LEFT = 7
    HAND_LEFT = 8
    HANDTIP_LEFT = 9
    THUMB_LEFT = 10
    CLAVICLE_RIGHT = 11
    SHOULDER_RIGHT = 12
    ELBOW_RIGHT = 13
    WRIST_RIGHT = 14
    HAND_RIGHT = 15
    HANDTIP_RIGHT = 16
    THUMB_RIGHT = 17
    HIP_LEFT = 18
    KNEE_LEFT = 19
    ANKLE_LEFT = 20
    FOOT_LEFT = 21
    HIP_RIGHT = 22
    KNEE_RIGHT = 23
    ANKLE_RIGHT = 24
    FOOT_RIGHT = 25
    HEAD = 26
    NOSE = 27
    EYE_LEFT = 28
    EAR_LEFT = 29
    EYE_RIGHT = 30
    EAR_RIGHT = 31
    _COUNT = 32

    @classmethod
    def __len__(cls) -> int:
        return cls._COUNT


class InvalidConfidence(Exception):
    pass


class InvalidValidity(Exception):
    pass


class JointConfidence(IntEnum):
    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3

    @classmethod
    def from_joint(cls, ndarray: np.ndarray) -> int:
        value = int(ndarray[7])
        if value not in (v.value for v in cls):
            log.error(f"{cls.__name__}: {value=}")
            raise InvalidConfidence(f"Confidence joint value {value} is invalid")
        return value


class JointValid(IntEnum):
    INVALID = 0
    VALID = 1
    UNKNOWN = 2

    @classmethod
    def from_joint(cls, ndarray: np.ndarray) -> int:
        value = int(ndarray[7])
        if value not in (v.value for v in cls):
            log.error(f"{cls.__name__}: {value=}")
            raise InvalidValidity(f"Valid joint value {value} is invalid")
        return value


@dataclass
class BodyJoint(JsonSchemaMixin):
    position_x:  Optional[float] = None
    position_y:  Optional[float] = None
    position_z:  Optional[float] = None
    orientation_w:  Optional[float] = None
    orientation_x:  Optional[float] = None
    orientation_y:  Optional[float] = None
    orientation_z:  Optional[float] = None
    confidence_level: Optional[int] = None
    position_image_0:  Optional[float] = None
    position_image_1:  Optional[float] = None
    valid: Optional[int] = None

    is_null: bool = True

    @classmethod
    def from_joint(cls, ndarray: np.ndarray) -> BodyJoint:
        return cls(
            position_x=ndarray[0],
            position_y=ndarray[1],
            position_z=ndarray[2],
            orientation_w=ndarray[3],
            orientation_x=ndarray[4],
            orientation_y=ndarray[5],
            orientation_z=ndarray[6],
            confidence_level=JointConfidence.from_joint(ndarray),
            position_image_0=ndarray[8],
            position_image_1=ndarray[9],
            valid=JointValid.from_joint(ndarray),
            is_null=False,
        )


__all__ = ["JointId", "InvalidConfidence", "InvalidValidity", "JointConfidence", "JointValid", "BodyJoint"]
