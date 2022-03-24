from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from dataclasses_jsonschema import JsonSchemaMixin
from pyk4a import FPS, ColorResolution
from pyk4a import Config as KinectConfig
from pyk4a import DepthMode, ImageFormat, WiredSyncMode


@dataclass
class BaseResult(JsonSchemaMixin):
    message: str
    result: Optional[str] = None


@dataclass
class BaseCount(JsonSchemaMixin):
    message: str
    result: int


@dataclass
class Settings(JsonSchemaMixin):
    DEVEL: bool = field(default=True)
    DEBUG: bool = field(default=False)
    WITHOUT_KINECT: bool = field(default=False)
    MAX_BUFFER_CAPACITY: int = field(default=20)

    THREAD_SLEEP_TIME: float = field(default=1 / 1000)

    NUM_SAMPLES: int = field(default=5)

    @classmethod
    def from_env(cls) -> Settings:
        # TODO:
        return cls()


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
    def from_kinect_config(cls, config: KinectConfig) -> Config:
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


__all__ = ["BaseResult", "BaseCount", "Settings", "Config"]
