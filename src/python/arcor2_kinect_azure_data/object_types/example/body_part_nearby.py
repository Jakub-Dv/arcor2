from time import sleep

from arcor2.data.common import BodyJointId, Position
from arcor2_kinect_azure_data.object_types.example import BOX, POSE
from arcor2_kinect_azure_data.object_types.kinect import KinectCamera, UrlSettings

position = Position(0, 0, 1)  # +- 1m from camera
radius = 0.1  # 100mm
joint_id = BodyJointId.HAND_LEFT

settings = UrlSettings("localhost:5016")
k = KinectCamera("id", "foo", POSE, BOX, settings)

while True:
    print(f"{k.is_body_part_nearby(joint_id, radius, position)=}")
    sleep(0.2)
