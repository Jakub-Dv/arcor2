from __future__ import annotations

import logging
from collections import deque
from typing import Optional

from arcor2_kinect_azure.core import get_settings
from arcor2_kinect_azure.core.processing import get_skeleton
from pyk4a import PyK4ACapture

from arcor2.data.kinect.joint import BodyJoint, JointId, JointValid

log = logging.getLogger(__name__)


class Direction:
    def __init__(
        self,
        buffer: deque[PyK4ACapture],
        joint_index: int = JointId.SPINE_CHEST,
        body_index: int = 0,
        num_samples: int = get_settings().NUM_SAMPLES,
        best_effort: bool = False,
    ) -> None:
        self._buffer = buffer

        self._joint: Optional[BodyJoint] = None
        self._horizontal_speed: Optional[float] = None
        self._vertical_speed: Optional[float] = None
        self._depth_speed: Optional[float] = None

        self.joint_index: int = joint_index
        self.num_samples: int = num_samples
        self.body_index: int = body_index

        self._best_effort: bool = best_effort

    @property
    def horizontal_speed(self) -> Optional[float]:
        if self._horizontal_speed is None:
            self._compute()
        return self._horizontal_speed

    @property
    def vertical_speed(self) -> Optional[float]:
        if self._vertical_speed is None:
            self._compute()
        return self._vertical_speed

    @property
    def depth_speed(self) -> Optional[float]:
        if self._depth_speed is None:
            self._compute()
        return self._depth_speed

    def _verify_joint(self) -> bool:
        if self._joint is None:
            self._compute()
        if self._joint is None:
            log.error("failed to compute direction data")
            return False
        return True

    @property
    def joint(self) -> Optional[BodyJoint]:
        if self._verify_joint() is False:
            return None
        return self._joint

    @property
    def x(self) -> Optional[int]:
        if self._verify_joint() is False:
            return None
        return self._joint.position_x

    @property
    def y(self) -> Optional[int]:
        if self._verify_joint() is False:
            return None
        return self._joint.position_y

    @property
    def z(self) -> Optional[int]:
        if self._verify_joint() is False:
            return None
        return self._joint.position_z

    def _compute(self) -> None:
        if self.num_samples < 2:
            log.error("minimum number of samples is 2")
            return

        relevant_buffer: list[BodyJoint] = []
        skip_counter: int = 0

        for capture in reversed(self._buffer):
            skeleton = get_skeleton(capture, self.body_index)
            if skeleton is None:
                if skip_counter and self._best_effort is False > 3:
                    log.error("Multiple captures in sequence are missing bodies")
                    return  # bad data
                skip_counter += 1
                continue
            skip_counter = 0

            joint: BodyJoint = BodyJoint.from_joint(skeleton[self.body_index])
            if joint.valid != JointValid.VALID:
                log.error(f"{joint} is invalid")
                continue

            relevant_buffer.append(joint)

            if len(relevant_buffer) == self.num_samples:
                break

        if len(relevant_buffer) != self.num_samples and self._best_effort is False:
            log.error(f"{len(relevant_buffer)} != {self.num_samples}")
            return

        if self._best_effort and len(relevant_buffer) < 2:
            log.error(f"{len(relevant_buffer)=}, unable to compute direction")
            return

        def get_direction(buffer: list[float]) -> float:
            _sum: float = 0
            for i in range(len(buffer) - 1):
                _sum += buffer[i] - buffer[i + 1]
            return _sum

        self._horizontal_speed = get_direction(list(b.position_x for b in relevant_buffer))
        self._vertical_speed = get_direction(list(b.position_y for b in relevant_buffer))
        self._depth_speed = get_direction(list(b.position_z for b in relevant_buffer))

        self._joint = relevant_buffer[-1]
