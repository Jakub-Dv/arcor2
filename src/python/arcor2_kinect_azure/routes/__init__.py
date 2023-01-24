from functools import wraps
from typing import Callable, ParamSpec, TypeVar

from arcor2_kinect_azure import app
from arcor2_kinect_azure.exceptions import StartError


def started() -> bool:
    if app.MOCK:
        return app.MOCK_STARTED

    return app.KINECT is not None


P = ParamSpec("P")
R = TypeVar("R")
F = Callable[P, R]


def requires_started(f: F):
    @wraps(f)  # type: ignore
    def wrapped(*args: P.args, **kwargs: P.kwargs):
        if not started():
            raise StartError("Not started")
        return f(*args, **kwargs)

    return wrapped
