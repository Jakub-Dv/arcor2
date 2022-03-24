import argparse
import os

from arcor2_kinect_azure import version
from arcor2_kinect_azure.blueprints import aggregations, body, common, positions
from arcor2_kinect_azure.core import get_kinect_app
from arcor2_kinect_azure.core.abstract import Kinect
from flask import Flask

from arcor2 import env
from arcor2.data.kinect import BaseResult
from arcor2.flask import DataclassResponse, create_app, run_app
from arcor2.helpers import port_from_url
from arcor2.logging import get_logger

log = get_logger(__name__)

URL = os.getenv("ARCOR2_KINECT_AZURE_URL", "http://localhost:5016")
SERVICE_NAME = "Kinect Azure Service"

app: Flask = create_app(__name__)
app.register_blueprint(common.blueprint)
app.register_blueprint(body.blueprint)
app.register_blueprint(positions.blueprint)
app.register_blueprint(aggregations.blueprint)

kinect_app: Kinect = get_kinect_app()


@app.route("/")
def check_connection() -> DataclassResponse:
    is_opened: bool = kinect_app.opened
    dataclass = BaseResult(message=f'Connection to device is {"" if is_opened else "not "}opened')
    return DataclassResponse(
        dataclass=dataclass,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=SERVICE_NAME)
    parser.add_argument("-s", "--swagger", action="store_true", default=False)
    parser.add_argument("-m", "--mock", action="store_true", default=env.get_bool("ARCOR2_KINECT_AZURE_MOCK"))
    args = parser.parse_args()

    log.info(f"running on port: {port_from_url(URL)}")
    run_app(app, SERVICE_NAME, version(), port_from_url(URL), None, args.swagger)

    global kinect_app
    del kinect_app


if __name__ == "__main__":
    main()
