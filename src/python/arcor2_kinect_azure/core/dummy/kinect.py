import logging
from collections import deque
from time import sleep

from arcor2_kinect_azure.core.abstract import Kinect
from arcor2_kinect_azure.core.dummy.capture import DummyPyk4aCapture
from pyk4a import Calibration, Config
from pyk4a.errors import K4AException

log = logging.getLogger(__name__)


class DummyCalibration(Calibration):
    pass


class DummyConfig(Config):
    pass


class DummyKinect(Kinect):
    TIMEOUT_WAIT_INFINITE = -1
    BODY_TRACKING_SUPPORT = True

    def start(self) -> None:
        if not self.opened:
            self.open()
        self.is_running = True

    def stop(self) -> None:
        if not self.opened:
            raise K4AException("Device not opened")
        if self._capturing and self._capturing_thread is not None:
            self._capturing = False
            sleep(0.2)
            self._capturing_thread.join()
        self.close()
        self._capturing = False
        self.is_running = False

    def get_capture(self, timeout=TIMEOUT_WAIT_INFINITE) -> DummyPyk4aCapture:
        capture_handle = object
        return DummyPyk4aCapture(
            calibration=self.calibration,
            capture_handle=capture_handle,
            color_format=self._config.color_format,
            thread_safe=self.thread_safe,
        )

    def _device_open(self) -> None:
        self._device_handle = object

    def open(self) -> None:
        if self.opened:
            raise K4AException("Device already opened")
        self._device_open()

    def close(self):
        self._device_handle = None

    @property
    def opened(self) -> bool:
        return self._device_handle is not None

    @property
    def capture_buffer(self) -> deque:
        return self._capture_buffer

    @property
    def calibration(self) -> Calibration:
        self._validate_is_opened()
        if not self._calibration:
            self._calibration = DummyCalibration(
                object,
                self._config.depth_mode,
                self._config.color_resolution,
            )
        return self._calibration
