import json
from http import HTTPStatus

from flask import Blueprint, Response, request

from arcor2.data.common import BodyJointId, Pose, Position
from arcor2.flask import DataclassResponse, RespT
from arcor2.logging import get_logger
from arcor2_kinect_azure import app
from arcor2_kinect_azure.exceptions import NotFound
from arcor2_kinect_azure.kinect.processing import get_body_joint, parse_skeleton
from arcor2_kinect_azure.routes import requires_started
from arcor2_kinect_azure_data.joint import BodyJoint, JointValid

blueprint = Blueprint("position", __name__, url_prefix="/position")

log = get_logger(__name__)


@blueprint.route("/is-nearby", methods=["GET"])
@requires_started
def is_nearby() -> RespT:
    """Get true if body part is nearby specified position
    ---
    get:
        description: Get true if body part is nearby specified position
        tags:
           - Kinect Azure
        requestBody:
            content:
              application/json:
                schema:
                  $ref: Position
        parameters:
            - in: query
              name: body_id
              description: Default value points to the chest
              schema:
                type: integer
                default: 2
                minimum: 0
                maximum: 31
            - in: query
              name: radius
              schema:
                type: number
                format: float
                default: 1.0
                minimum: 0.0
        responses:
            200:
              description: Ok
              content:
                application/json:
                    schema:
                        type: boolean
            500:
              description: "Error types: **General**, **StartError**."
              content:
                application/json:
                  schema:
                    $ref: WebApiError
    """
    if not isinstance(request.json, dict):
        raise NotFound("Position was not found")

    kinect = app.KINECT
    assert kinect is not None

    abs_position = Position.from_dict(request.json)
    position = kinect.get_camera_relative_pos(abs_position)
    body_id = BodyJointId.from_int(int(request.args.get("body_id") or 0))
    joint_id = int(request.args.get("joint_id") or BodyJointId.SPINE_CHEST)
    if joint_id not in range(len(BodyJointId)):
        return Response(
            response='"Wrong BodyJointId provided"',
            status=HTTPStatus.FORBIDDEN,
        )
    radius = float(request.args.get("radius") or 1.0)

    joint = get_body_joint(kinect.capture(), joint_id, body_id)
    if not joint:
        return Response(response=json.dumps(False))

    for set_p, p in zip(position, joint.position):
        if abs(set_p - p) > radius:
            return Response(response=json.dumps(False))

    return Response(response=json.dumps(True))


@blueprint.route("/is-colliding", methods=["GET"])
@requires_started
def is_colliding() -> RespT:
    """Get true if body is going to collide with provided position
    ---
    get:
        description: Get true if body is going to collide with provided position
        tags:
           - Kinect Azure
        requestBody:
            content:
              application/json:
                schema:
                  $ref: Position
        parameters:
            - in: query
              name: radius
              schema:
                type: number
                format: float
                default: 0.03
                minimum: 0.0
        responses:
            200:
              description: Ok
              content:
                application/json:
                    schema:
                        type: boolean
            500:
              description: "Error types: **General**, **StartError**."
              content:
                application/json:
                  schema:
                    $ref: WebApiError
    """
    if not isinstance(request.json, dict):
        raise NotFound("Position was not found")

    kinect = app.KINECT
    assert kinect is not None

    abs_position = Position.from_dict(request.json)
    position = kinect.get_camera_relative_pos(abs_position)
    threshold = float(request.args.get("radius") or 0.1)

    stable_buffer = kinect.stable_buffer()
    skeleton = None
    for buffer_index in range(5):
        skeleton = parse_skeleton(stable_buffer[buffer_index])
        if skeleton is not None:
            break

    if skeleton is None:
        log.warning("No skeleton was found")
        return Response(response="false")

    log.debug(f"{threshold=}")
    for joint_id in range(len(BodyJointId)):
        body_joint = BodyJoint.from_joint(skeleton[joint_id])
        if body_joint.valid != JointValid.VALID or body_joint.position is None:
            continue

        distance = position - body_joint.position
        log.debug(f"{joint_id}: {distance=}")
        if abs(distance.x) < threshold and abs(distance.y) < threshold and abs(distance.z) < threshold:
            return Response(response=json.dumps(True))

    return Response(response=json.dumps(False))


@blueprint.route("/get", methods=["GET"])
@requires_started
def get_position() -> RespT:
    """Return position of specified body part
    ---
    get:
        description: Return position of specified body part
        tags:
           - Kinect Azure
        parameters:
            - in: query
              name: body_id
              schema:
                type: integer
                default: 0
            - in: query
              name: joint_id
              schema:
                type: integer
                default: 2
                minimum: 0
                maximum: 31
        responses:
            200:
              description: Ok
              content:
                application/json:
                    schema:
                        $ref: Pose
            500:
              description: "Error types: **General**, **StartError**."
              content:
                application/json:
                  schema:
                    $ref: WebApiError
    """
    kinect = app.KINECT
    assert kinect is not None

    body_id = int(request.args.get("body_id") or 0)
    joint_id = BodyJointId.from_maybe_str_or_default(request.args.get("joint_id"))

    capture = kinect.capture()
    joint = get_body_joint(capture, joint_id, body_id)
    assert joint is not None

    abs_position = kinect.get_camera_absolute_pos(joint.position)

    return DataclassResponse(Pose(abs_position))
