from __future__ import annotations

from pyk4a import PyK4A
from pyk4a import Config, ColorResolution, DepthMode, FPS

from arcor2_kinect_azure import config


def get_default_config() -> Config:
    return Config(
        color_resolution=ColorResolution.RES_1080P,
        depth_mode=DepthMode.NFOV_UNBINNED,
        camera_fps=FPS.FPS_30,
    )


class Tracker(PyK4A):
    def __init__(self, config: Config | None, *args, **kwargs) -> None:
        if config is None:
            config = get_default_config()
        super().__init__(config, *args, **kwargs)

    def run_forever(self, devel: bool = False) -> None:
        if devel:
            import cv2

        try:
            while True:
                capture = self.get_capture()
                body_skeleton = capture.body_skeleton

                frame = capture.color

                if body_skeleton is not None:

                    for body_index in range(body_skeleton.shape[0]):
                        skeleton = body_skeleton[body_index, :, :]
                        for joint_index in range(skeleton.shape[0]):
                            try:
                                valid = int(skeleton[joint_index, -1])
                                if valid != 1:
                                    continue
                                x, y = skeleton[joint_index, (-3, -2)].astype(int)
                                if devel:
                                    cv2.circle(frame, (x, y), 12, (50, 50, 50), thickness=-1, lineType=cv2.FILLED)
                                    cv2.putText(
                                        frame,
                                        str(joint_index),
                                        (x, y),
                                        cv2.FONT_HERSHEY_SIMPLEX,
                                        1,
                                        (0, 0, 0),
                                        2,
                                        cv2.LINE_AA
                                    )
                            except Exception as e:
                                print(e)
                                pass

                if devel:
                    cv2.imshow("frame", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
        except KeyboardInterrupt:
            pass

        self.stop()
        if devel:
            cv2.destroyAllWindows()
