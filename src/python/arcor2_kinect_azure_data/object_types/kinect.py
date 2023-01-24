import os
from dataclasses import dataclass
from functools import cache, wraps
from typing import Any, Callable, Optional, Type, TypeVar, cast
from urllib.parse import urljoin, urlparse

from PIL import Image

from arcor2.data.common import ActionMetadata, BodyJointId, Direction, Pose, Position
from arcor2.data.object_type import Models
from arcor2.env import Arcor2EnvException
from arcor2.object_types.abstract import Camera, Settings
from arcor2.rest import DataClass, Method, RestException, ReturnValue, Timeout, call, get_image


@dataclass
class UrlSettings(Settings):
    url: str

    @classmethod
    def from_env(cls) -> "UrlSettings":
        url = os.getenv("ARCOR2_KINECT_AZURE_URL")
        if url is None:
            raise Arcor2EnvException("Missing 'ARCOR2_KINECT_AZURE_URL' environment variable")
        return cls(url)

    def construct_path(self, path: str) -> str:
        @cache
        def get_base_url(url: str) -> str:
            parsed = urlparse(url)
            if parsed.netloc == "":
                parsed = urlparse("http://" + url)
            return parsed.geturl()

        return urljoin(get_base_url(self.url), path)


F = TypeVar("F", bound=Callable[..., Any])


def assure_started(func: F) -> F:
    @wraps(func)
    def wrapper(self: "KinectCamera", *args: Any, **kwargs: Any) -> Any:
        if not self._started:
            self.start()
        assert self._started, "Failed to start kinect"
        return func(self, *args, **kwargs)

    return cast(F, wrapper)


class KinectCamera(Camera):
    _ABSTRACT = False
    mesh_filename = "kinect_azure.dae"

    def __init__(
        self,
        obj_id: str,
        name: str,
        pose: Pose,
        collision_model: Models,
        settings: Optional[UrlSettings] = None,
    ) -> None:
        if settings is None:
            settings = UrlSettings.from_env()
        super().__init__(obj_id, name, pose, collision_model, settings)

    def _request(
        self,
        relative_path: str,
        method: Method = Method.GET,
        body: DataClass | None = None,
        ret_type: Type[Any] = str,
        timeout: Timeout | None = None,
    ) -> ReturnValue:
        full_path = self.settings.construct_path(relative_path)  # type: ignore
        return call(method, full_path, body=body, return_type=ret_type, timeout=timeout)

    def _communicate_image(self, relative_path: str) -> Image.Image:
        full_path = self.settings.construct_path(relative_path)  # type: ignore
        return get_image(full_path)

    @property
    def _started(self) -> bool:
        ret = self._request("/state/started", ret_type=bool)
        assert isinstance(ret, bool)
        return ret

    def start(self) -> None:
        if self._started:
            return

        try:
            self._request("/state/full-start", method=Method.PUT, body=self.pose)
        except RestException:
            # Already running
            return

    def stop(self) -> None:
        if not self._started:
            return

        self._request("/state/stop")

    @assure_started
    def color_image(self, *, an: Optional[str] = None) -> Image.Image:
        """Get color image from kinect.

        :return: Color image
        """
        return self._communicate_image("/color/image")

    @assure_started
    def depth_image(self, averaged_frames: int = 1, *, an: Optional[str] = None) -> Image.Image:
        """Get depth image from kinect.

        :param: averaged_frames: Number of frames to get depth from (more frames, more accurate)
        :return: Depth image
        """
        assert isinstance(averaged_frames, int)
        return self._communicate_image(f"/depth/image?num_frames={averaged_frames}")

    @assure_started
    def is_body_part_nearby(
        self, joint_id: BodyJointId, radius: float, position: Position, *, an: Optional[str] = None
    ) -> bool:
        """Checks if body part is in radius from pose.

        :param: joint_id: Id of body part, see: https://docs.microsoft.com/en-us/azure/kinect-dk/body-joints
        :param: radius: radius around body part in m
        :param: pose: If set, sets position in kinect otherwise use last set position
        :return: True if body part is nearby, otherwise False
        """
        assert 0 <= joint_id <= 31

        ret = self._request(f"/position/is-nearby?joint_id={joint_id}&radius={radius}", ret_type=bool, body=position)
        assert isinstance(ret, bool)
        return ret

    @assure_started
    def get_people_count(self, *, an: Optional[str] = None) -> int:
        """Counts number of skeletons in frame.

        :return: Number of skeletons in frame
        """
        ret = self._request("/body/count", ret_type=int)
        assert isinstance(ret, int)
        return ret

    @assure_started
    def is_user_present(self, *, an: Optional[str] = None) -> bool:
        """Checks if any user is in frame.

        :return: True if any user is in frame, otherwise False
        """
        return bool(self.get_people_count())

    @assure_started
    def is_body_part_moving(
        self,
        joint_id: BodyJointId,
        speed: float,
        direction: Direction,
        deviation: float = 0.1,
        num_samples: int = 5,
        *,
        an: Optional[str] = None,
    ) -> bool:
        """Checks if a body part is moving in specified direction.

        :param: joint_id: Id of body part, see: https://docs.microsoft.com/en-us/azure/kinect-dk/body-joints
        :param: threshold: Minimum speed of moving body part in m/s
        :param: direction: Direction
        :params: num_samples: How many samples to use to calculate speed
        :return: True if body part is moving else False
        """
        assert 0 <= joint_id <= 31
        ret = self._request(
            f"/aggregation/is-moving?joint_id={joint_id}&speed={speed}&num_samples={num_samples}&deviation={deviation}",
            ret_type=bool,
            body=direction,
        )
        assert isinstance(ret, bool)
        return ret

    @assure_started
    def is_colliding(self, threshold: float, position: Position, *, an: Optional[str] = None) -> bool:
        """Check if any body part is colliding with specified position.

        :param: threshold: Max distance from set position in m
        :return: True if colliding else False
        """

        ret = self._request(f"/position/is-colliding?threshold={threshold}", ret_type=bool, body=position)
        assert isinstance(ret, bool)
        return ret

    @assure_started
    def get_position(self, joint_id: BodyJointId, body_id: int = 0) -> Pose:
        """Get body part position.

        :param: joint_id: Id of body part, see: https://docs.microsoft.com/en-us/azure/kinect-dk/body-joints
        :param: threshold: Minimum speed of moving body part in m/s
        :return: Pose
        """
        ret = self._request(f"/position/get?body_id={body_id}&joint_id={joint_id}", ret_type=Pose)
        assert isinstance(ret, Pose)
        return ret

    color_image.__action__ = ActionMetadata()  # type: ignore
    depth_image.__action__ = ActionMetadata()  # type: ignore
    is_body_part_nearby.__action__ = ActionMetadata()  # type: ignore
    get_people_count.__action__ = ActionMetadata()  # type: ignore
    is_user_present.__action__ = ActionMetadata()  # type: ignore
    is_body_part_moving.__action__ = ActionMetadata()  # type: ignore
    is_colliding.__action__ = ActionMetadata()  # type: ignore
    get_position.__action__ = ActionMetadata()  # type: ignore
