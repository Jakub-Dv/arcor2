from typing import Optional

import numpy as np
from pyk4a.capture import PyK4ACapture

from arcor2.data.kinect.joint import BodyJoint


def get_skeleton(capture: PyK4ACapture, body_id: int) -> Optional[np.ndarray]:
    skeleton = capture.body_skeleton
    if skeleton is None or skeleton.shape[0] == 0:
        return None
    try:
        return skeleton[body_id, :, :]
    except KeyError:
        return None


def get_body_joint(capture: PyK4ACapture, body_id: int, index: int) -> BodyJoint:
    body_skeleton = get_skeleton(capture, body_id)
    if body_skeleton is None:
        return BodyJoint()
    return BodyJoint.from_joint(body_skeleton[index])
