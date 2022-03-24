import logging
from collections import deque
from functools import cache

from arcor2_kinect_azure.core.abstract import Kinect
from arcor2_kinect_azure.core.dummy.kinect import DummyKinect, DummyConfig
from arcor2_kinect_azure.core.real.kinect import RealKinect
from pyk4a.capture import PyK4ACapture

from arcor2.data.kinect import Settings

log = logging.getLogger(__name__)


@cache
def get_settings() -> Settings:
    return Settings.from_env()


@cache
def get_kinect_app() -> Kinect:
    log.info("Initializing Kinect")
    settings = get_settings()
    if settings.WITHOUT_KINECT:
        return DummyKinect(settings=settings, config=DummyConfig())
    return RealKinect(settings=settings)


def get_capture() -> PyK4ACapture:
    return get_kinect_app().capture_buffer[-1]


def get_stable_buffer() -> deque[PyK4ACapture]:
    return get_kinect_app().capture_buffer.copy()
