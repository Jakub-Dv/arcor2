from http import HTTPStatus

from flask import Blueprint, Response

from arcor2.flask import RespT
from arcor2.logging import get_logger
from arcor2_kinect_azure import app

log = get_logger(__name__)

blueprint = Blueprint("healthcheck", __name__, url_prefix="/healthcheck")


@blueprint.route("/", methods=["GET"])
def healthcheck() -> RespT:
    if app.MOCK:
        return Response(response="Ok", status=HTTPStatus.OK)
    else:
        kinect = app.KINECT
        assert kinect is not None
        if kinect.stable_buffer_len() == kinect.CAPTURE_BUFFER_CAP:
            return Response(response="Ok", status=HTTPStatus.OK)
        else:
            return Response(response="Waiting on kinect", status=HTTPStatus.METHOD_NOT_ALLOWED)
