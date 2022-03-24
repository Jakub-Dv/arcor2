import asyncio
import threading
import time
from abc import abstractmethod, ABC
from collections import deque
from typing import Optional, Literal

from pyk4a import Config, K4AException
from pyk4a.capture import PyK4ACapture, Calibration

from arcor2.data.kinect import Settings
from arcor2.logging import get_logger

log = get_logger(__name__)


class Kinect(ABC):
    def __init__(self, settings: Settings, config: Config, device_id: int = 0, thread_safe: bool = True) -> None:
        self._device_id = device_id
        self._config: Config = config
        self.thread_safe = thread_safe
        self._device_handle: Optional[object] = None
        self._calibration: Optional[Calibration] = None
        self.is_running = False

        self.settings = settings

        self._capture_buffer: deque[PyK4ACapture] = deque(maxlen=settings.MAX_BUFFER_CAPACITY)
        self._capturing: bool = False
        self._capturing_thread: Optional[threading.Thread] = None

    @abstractmethod
    def start(self) -> None:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass

    @abstractmethod
    def close(self) -> None:
        pass

    @property
    @abstractmethod
    def calibration(self) -> Calibration:
        pass

    def __del__(self) -> None:
        if self.is_running:
            self.stop()
        elif self.opened:
            self.close()

    @abstractmethod
    def get_capture(self, timeout: Optional[int] = None) -> PyK4ACapture:
        pass

    @property
    def config(self) -> Config:
        return self._config

    @property
    def opened(self) -> bool:
        return self._device_handle is not None

    @property
    def capture_buffer(self) -> deque[PyK4ACapture]:
        return self._capture_buffer

    @property
    def capturing(self) -> bool:
        return self._capturing

    def _validate_is_opened(self):
        if not self.opened:
            raise K4AException("Device is not opened")

    def stop_capturing(self) -> None:
        self._capturing = False  # this should stop capturing
        if self._capturing_thread is not None:
            self._capturing_thread.join()
            self._capturing_thread = None
            self._capture_buffer = deque([])  # empty the buffer

    def start_capturing(self) -> Optional[Literal[False]]:
        if not self.is_running:
            log.warning("Please start a device first")
            return False

        if self._capturing is True:
            log.warning("Capturing has already started")
            return False
        self._capturing = True

        def capture_forever() -> None:
            """Periodically capture frames from kinect."""
            capture: PyK4ACapture
            while self._capturing:
                start = time.time()
                capture = self.get_capture()
                # lazy load body skeleton
                _ = capture.body_skeleton
                end = time.time()
                self._capture_buffer.append(capture)
                log.info(f"capturing took: {end - start}")

        self._capturing_thread = threading.Thread(target=capture_forever)
        self._capturing_thread.start()
        return None
