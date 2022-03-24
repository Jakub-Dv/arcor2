from http import HTTPStatus

from arcor2_kinect_azure.core import get_capture, get_kinect_app
from arcor2_kinect_azure.core.processing import get_body_joint
from flask import Blueprint, request
from pyk4a.capture import PyK4ACapture

from arcor2.data.kinect import BaseResult
from arcor2.data.kinect.joint import JointId
from arcor2.data.kinect.position import Position
from arcor2.flask import DataclassResponse

blueprint = Blueprint("position", __name__, url_prefix="/position")


@blueprint.route("/")
def position() -> DataclassResponse:
    kinect_app = get_kinect_app()
    if not (kinect_app.is_running and kinect_app.capturing):
        return DataclassResponse(
            dataclass=BaseResult(message="kinect has not started capturing frames"),
            status=HTTPStatus.FORBIDDEN,
        )

    joint_id = int(request.args.get("joint_id") or JointId.SPINE_CHEST)
    body_id = int(request.args.get("body_id") or 0)
    capture: PyK4ACapture = get_capture()
    joint = get_body_joint(
        capture,
        body_id,
        joint_id,
    )

    if joint.is_null:
        status = HTTPStatus.NOT_FOUND
    else:
        status = HTTPStatus.OK

    return DataclassResponse(
        dataclass=Position(result=joint, message="body part coordinates"),
        status=status
    )
