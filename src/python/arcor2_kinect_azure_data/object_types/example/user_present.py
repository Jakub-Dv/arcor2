from time import sleep

from arcor2_kinect_azure_data.object_types.example import BOX, POSE
from arcor2_kinect_azure_data.object_types.kinect import KinectCamera, UrlSettings

settings = UrlSettings("localhost:5016")
k = KinectCamera("id", "foo", POSE, BOX, settings)

# Checks if there is anyone in picture
while True:
    print(f"{k.is_user_present()=}")
    sleep(0.2)
