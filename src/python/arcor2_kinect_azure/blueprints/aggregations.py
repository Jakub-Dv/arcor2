from arcor2_kinect_azure.aggregations import Direction
from arcor2_kinect_azure.core import get_settings, get_stable_buffer
from flask import Blueprint, request

from arcor2.data.kinect.aggregation import DirectionModel
from arcor2.data.kinect.joint import JointId
from arcor2.flask import DataclassResponse

blueprint = Blueprint("aggregation", __name__, url_prefix="/aggregation")


@blueprint.route("/direction")
def get_moving_direction() -> DataclassResponse:
    buffer = get_stable_buffer()
    joint_id = int(request.args.get("joint_id") or JointId.SPINE_CHEST)
    body_id = int(request.args.get("body_id") or 0)
    num_samples = int(request.args.get("num_samples") or get_settings().NUM_SAMPLES)
    best_effort = bool(request.args.get("best_effort") or False)

    direction = Direction(buffer, joint_id, body_id, num_samples, best_effort)

    return DataclassResponse(
        dataclass=DirectionModel.from_direction(direction),
    )
