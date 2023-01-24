import os
import re
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, get_type_hints

from dataclasses_jsonschema import JsonSchemaMixin

from arcor2.object_types.abstract import Settings as Arcor2Settings


@dataclass
class Settings(Arcor2Settings):
    ARCOR2_KINECT_DEVEL: bool = field(default=False)
    ARCOR2_KINECT_DUMMY: bool = field(default=False)
    ARCOR2_KINECT_SKELETON_PRELOAD: bool = field(default=False)

    ARCOR2_KINECT_MAX_BUFFER_CAPACITY: int = field(default=20)
    ARCOR2_KINECT_THREAD_SLEEP_TIME: float = field(default=1 / 20)

    ARCOR2_KINECT_MOVING_NUM_SAMPLES: int = field(default=5)
    ARCOR2_KINECT_NEARBY_RADIUS: float = field(default=0.1)
    ARCOR2_KINECT_MOVING_THRESHOLD: float = field(default=0.1)

    @classmethod
    def from_env(cls) -> "Settings":
        d = {}
        type_hints: dict = get_type_hints(cls)
        for value in cls.__dict__:
            if not re.fullmatch(r"ARCOR2_KINECT[A-Z_]+", value):
                continue
            _type = type_hints[value]
            try:
                d[value] = _type(os.getenv(value))
            except Exception:
                pass
        return cls(**d)


class FPS(IntEnum):
    FPS_5 = 0
    FPS_15 = 1
    FPS_30 = 2


class ColorResolution(IntEnum):
    OFF = 0
    RES_720P = 1
    RES_1080P = 2
    RES_1440P = 3
    RES_1536P = 4
    RES_2160P = 5
    RES_3072P = 6


class DepthMode(IntEnum):
    OFF = 0
    NFOV_2X2BINNED = 1
    NFOV_UNBINNED = 2
    WFOV_2X2BINNED = 3
    WFOV_UNBINNED = 4
    PASSIVE_IR = 5


class ImageFormat(IntEnum):
    COLOR_MJPG = 0
    COLOR_NV12 = 1
    COLOR_YUY2 = 2
    COLOR_BGRA32 = 3
    DEPTH16 = 4
    IR16 = 5
    CUSTOM8 = 6
    CUSTOM16 = 7
    CUSTOM = 8


class WiredSyncMode(IntEnum):
    STANDALONE = 0
    MASTER = 1
    SUBORDINATE = 2


@dataclass
class Config(JsonSchemaMixin):
    color_resolution: ColorResolution
    color_format: ImageFormat
    depth_mode: DepthMode
    camera_fps: FPS
    synchronized_images_only: bool
    depth_delay_off_color_usec: int
    wired_sync_mode: WiredSyncMode
    subordinate_delay_off_master_usec: int
    disable_streaming_indicator: bool

    @classmethod
    def from_kinect_config(cls, config: Any) -> "Config":
        return cls(
            color_resolution=config.color_resolution,
            color_format=config.color_format,
            depth_mode=config.depth_mode,
            camera_fps=config.camera_fps,
            synchronized_images_only=config.synchronized_images_only,
            depth_delay_off_color_usec=config.depth_delay_off_color_usec,
            wired_sync_mode=config.wired_sync_mode,
            subordinate_delay_off_master_usec=config.subordinate_delay_off_master_usec,
            disable_streaming_indicator=config.disable_streaming_indicator,
        )
