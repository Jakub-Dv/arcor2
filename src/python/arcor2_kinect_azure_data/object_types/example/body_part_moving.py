from time import sleep

from arcor2.data.common import BodyJointId, Direction
from arcor2_kinect_azure_data.object_types.example import BOX, POSE
from arcor2_kinect_azure_data.object_types.kinect import KinectCamera, UrlSettings

joint_id = BodyJointId.HAND_LEFT
direction = Direction(1, 0, 0)
speed = 0.05
deviation = 0.2

settings = UrlSettings("localhost:5016")
k = KinectCamera("id", "foo", POSE, BOX, settings)

while True:
    print(f"{k.is_body_part_moving(joint_id, speed, direction, deviation)=}")
    sleep(0.2)
