import asyncio
import logging
import threading
from collections import deque
from time import sleep
from typing import Optional, Literal

import cv2
from arcor2_kinect_azure.core.abstract import Kinect
from pyk4a import Config, PyK4A

from arcor2.data.kinect import Settings

log = logging.getLogger(__name__)


class RealKinect(PyK4A, Kinect):
    def __init__(
        self, settings: Settings, config: Optional[Config] = None, device_id: int = 0, thread_safe: bool = True
    ) -> None:
        super().__init__(config, device_id, thread_safe)

        self.settings = settings
        self._capture_buffer = deque(maxlen=settings.MAX_BUFFER_CAPACITY)
        self._capturing = False
        self._capturing_thread: Optional[threading.Thread] = None

        self._showing_video: bool = False
        self._video_thread: Optional[threading.Thread] = None

    @property
    def capture_buffer(self) -> deque:
        return self._capture_buffer

    def stop(self) -> None:
        if self._showing_video:
            self._stop_showing_video()
        if self._capturing and self._capturing_thread is not None:
            self._capturing = False
            sleep(0.2)
            self._capturing_thread.join()

        super().stop()

    def _stop_showing_video(self) -> None:
        self._showing_video = False  # this should stop showing video
        if self._video_thread is not None:
            self._video_thread.join()
            cv2.destroyAllWindows()

    def show_video(self) -> Optional[Literal[False]]:
        if self._showing_video:
            log.warning("Already showing video")
            return None

        if not self._capturing:
            log.warning(f"Cannot start live video due to {self._capturing=}")
            return False

        self._showing_video = True

        def _video() -> None:
            while self._showing_video:
                capture = self.capture_buffer[-1]
                body_skeleton = capture.body_skeleton

                frame = capture.color

                if body_skeleton is not None:

                    for body_index in range(body_skeleton.shape[0]):
                        skeleton = body_skeleton[body_index, :, :]
                        for joint_index in range(skeleton.shape[0]):
                            try:
                                valid = int(skeleton[joint_index, -1])
                                if valid != 1:
                                    continue
                                x, y = skeleton[joint_index, (-3, -2)].astype(int)
                                cv2.circle(frame, (x, y), 12, (50, 50, 50), thickness=-1, lineType=cv2.FILLED)
                                cv2.putText(
                                    frame,
                                    str(joint_index),
                                    (x, y),
                                    cv2.FONT_HERSHEY_SIMPLEX,
                                    1,
                                    (0, 0, 0),
                                    2,
                                    cv2.LINE_AA,
                                )
                            except Exception as e:
                                log.exception(e)
                                pass

                cv2.imshow("frame", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    cv2.destroyAllWindows()
                    self._showing_video = False
                    break

        self._video_thread = threading.Thread(target=_video)
        self._video_thread.start()
        return None
