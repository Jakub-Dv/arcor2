from arcor2_kinect_azure.core import get_capture
from flask import Blueprint
from pyk4a.capture import PyK4ACapture

from arcor2.data.kinect.body import BodyCount
from arcor2.flask import DataclassResponse
from arcor2.logging import get_logger

log = get_logger(__name__)

blueprint = Blueprint("bodies", __name__, url_prefix="/bodies")


@blueprint.route("/count")
def get_body_count() -> DataclassResponse:
    capture: PyK4ACapture = get_capture()
    skeleton = capture.body_skeleton
    if skeleton is None:
        count = 0
    else:
        count = skeleton.shape[0]
    return DataclassResponse(dataclass=BodyCount(result=count, message="number of bodies in frame"))
