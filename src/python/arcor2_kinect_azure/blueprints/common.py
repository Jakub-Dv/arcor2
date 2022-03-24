from http import HTTPStatus

from arcor2_kinect_azure.core import get_kinect_app, get_settings
from arcor2_kinect_azure.core.real.kinect import RealKinect
from flask import Blueprint
from pyk4a.errors import K4AException

from arcor2.data.kinect import BaseCount, BaseResult, Config, Settings
from arcor2.flask import DataclassResponse
from arcor2.logging import get_logger

log = get_logger(__name__)

blueprint = Blueprint("state", __name__, url_prefix="/state")

kinect_app = get_kinect_app()


@blueprint.route("/start")
def start_kinect() -> DataclassResponse:
    try:
        kinect_app.start()
    except K4AException:
        dataclass = BaseResult(message="Probably misconfigured config")
        return DataclassResponse(
            dataclass=dataclass,
            status=HTTPStatus.NOT_FOUND,
        )
    return DataclassResponse(
        dataclass=BaseResult(message="started"),
    )


@blueprint.route("/start-capturing")
def start_capturing() -> DataclassResponse:
    if kinect_app.start_capturing() is False:
        return DataclassResponse(dataclass=BaseResult(message="Could not start capturing"), status=HTTPStatus.FORBIDDEN)
    return DataclassResponse(dataclass=BaseResult(message="started capturing frames"))


@blueprint.route("/captured-results")
def captured_results() -> DataclassResponse:
    captured_frames: int = len(kinect_app.capture_buffer)
    return DataclassResponse(
        dataclass=BaseCount(result=captured_frames, message=f"{captured_frames} results in buffer"),
    )


@blueprint.route("/stop-capturing")
def stop_capturing() -> DataclassResponse:
    if not kinect_app.capturing:
        return DataclassResponse(
            dataclass=BaseResult(message="Capturing has not started"),
        )
    kinect_app.stop_capturing()
    return DataclassResponse(dataclass=BaseResult(message="Stopped capturing"))


@blueprint.route("/config")
def get_config() -> DataclassResponse:
    dataclass = Config.from_kinect_config(kinect_app.config)
    return DataclassResponse(
        dataclass=dataclass,
    )


@blueprint.route("/stop")
def stop_kinect() -> DataclassResponse:
    if kinect_app.is_running:
        kinect_app.stop()
        return DataclassResponse(
            dataclass=BaseResult(message="stopped"),
        )
    return DataclassResponse(
        dataclass=BaseResult(message="not running"),
    )


@blueprint.route("/show")
def show_video() -> DataclassResponse:
    settings: Settings = get_settings()
    if not settings.DEVEL:
        return DataclassResponse(
            dataclass=BaseResult(message=f"{settings.DEVEL=}, must be True"),
            status=HTTPStatus.FORBIDDEN,
        )
    if not isinstance(kinect_app, RealKinect):
        return DataclassResponse(
            dataclass=BaseResult(message=f"Cannot show video on {kinect_app}"),
            status=HTTPStatus.NOT_FOUND,
        )
    if not kinect_app.opened:
        return DataclassResponse(
            dataclass=BaseResult(message="Please start the device first"),
            status=HTTPStatus.FORBIDDEN,
        )

    res = kinect_app.show_video()

    if res is False:
        return DataclassResponse(
            dataclass=BaseResult(message="cannot start video"),
            status=HTTPStatus.NOT_FOUND,
        )
    return DataclassResponse(
        dataclass=BaseResult(message="started video"),
    )
