"""ARCOR2 integration for a YuMi robot.

Based on https://github.com/galou/yumipy/tree/robotware6_06/yumipy
"""

import concurrent.futures as cf
import copy
import math
import socket
import time
from dataclasses import dataclass
from threading import Event, Lock
from typing import Iterable, NamedTuple, cast

import numpy as np
import quaternion
import requests
from requests import Session
from requests.auth import HTTPDigestAuth

from arcor2 import json
from arcor2 import transformations as tr
from arcor2.data.common import ActionMetadata, IntEnum, Joint, Orientation, Pose, Position, StrEnum
from arcor2.exceptions import Arcor2Exception
from arcor2.logging import get_logger
from arcor2.object_types.abstract import MultiArmRobot, Settings


class RawResponse(NamedTuple):

    mirror_code: int
    res_code: int
    message: str


class Response(NamedTuple):

    raw_res: RawResponse
    data: str


class RequestPacket(NamedTuple):

    req: str
    timeout: float
    return_res: bool


METERS_TO_MM = 1000.0
MM_TO_METERS = 1.0 / METERS_TO_MM

MOTION_BUFFER_SIZE = 512
MAX_TCP_SPEED = 1.5  # YuMi has max TCP speed 1.5m/s

MAX_GRIPPER_WIDTH = 0.02
MAX_GRIPPER_FORCE = 20

logger = get_logger("YuMi")


@dataclass
class YumiSettings(Settings):

    ip: str = "192.168.104.101"
    max_tcp_speed: float = MAX_TCP_SPEED
    home_on_start: bool = False

    def __post_init__(self) -> None:

        if not 0 < self.max_tcp_speed <= MAX_TCP_SPEED:
            raise YumiException("Invalid speed.")


class RwsException(Arcor2Exception):
    pass


class ProgramStopped(RwsException):
    pass


class ExecutionState(StrEnum):

    running: str = "running"
    stopped: str = "stopped"


class ControllerState(StrEnum):

    init: str = "init"
    motoron: str = "motoron"
    motoroff: str = "motoroff"
    guardstop: str = "guardstop"
    emergencystop: str = "emergencystop"
    emergencystopreset: str = "emergencystopreset"
    sysfail: str = "sysfail"


class RWS:
    """Class for communicating with RobotWare through Robot Web Services (ABB's
    Rest API).

    Inspired by https://github.com/prinsWindy/ABB-Robot-Machine-Vision
    """

    def __init__(self, base_url: str, username: str = "Default User", password: str = "robotics") -> None:
        self._base_url = base_url
        self._session = Session()  # creates persistent HTTP communication
        self._session.auth = HTTPDigestAuth(username, password)
        self._headers: dict[str, str] = {"Content-Type": "application/x-www-form-urlencoded"}

    def _post(self, url: str, data: None | dict = None, params: None | dict = None) -> requests.Response:

        if params is None:
            params = {}

        params["json"] = "1"

        assert not url.startswith("/")

        return self._session.post(f"{self._base_url}/{url}", data=data, params=params, headers=self._headers)

    def _get(self, url: str, params: None | dict = None) -> requests.Response:

        if params is None:
            params = {}

        params["json"] = "1"

        assert not url.startswith("/")

        return self._session.get(f"{self._base_url}/{url}", params=params, headers=self._headers)

    def _handle_response(self, resp: requests.Response, expected_code: int, error_message: str) -> None:

        if resp.status_code != expected_code:
            try:
                msg = json.loads_type(resp.text, dict)["_embedded"]["status"]["msg"]
            except (KeyError, json.JsonException):
                raise RwsException(error_message)
            raise RwsException(f"{error_message}. {msg}")

    def register_remote_user(self) -> None:

        resp = self._post(
            "users",
            {"username": "ARCOR2 User", "application": "Arcor2Studio", "location": "Earth", "ulocale": "remote"},
        )
        self._handle_response(resp, 201, "Could not register remote user.")

    def login_as_local_user(self) -> None:

        resp = self._post("users", {"type": "local"}, {"action": "set-locale"})
        self._handle_response(resp, 204, "Could not login as local user.")

    def reset_pp(self) -> None:
        """Resets the program pointer to main procedure in RAPID."""

        resp = self._post("rw/rapid/execution", params={"action": "resetpp"})
        self._handle_response(resp, 204, "Could not reset PP.")

    def request_mastership(self) -> None:
        resp = self._post("rw/mastership", params={"action": "request"})
        self._handle_response(
            resp, 204, "Could not get mastership. Try switching to manual and back to auto or restart the controller."
        )

    def release_mastership(self) -> None:
        resp = self._post("rw/mastership", params={"action": "release"})
        self._handle_response(resp, 204, "Could not release mastership.")

    def request_rmmp(self) -> None:
        """RMMP (Request Manual Mode Privileges) is used to get privileges in
        manual mode.

        It is the counter part of Mastership request in auto mode.
        """

        resp = self._post("users/rmmp", data={"privilege": "modify"})
        self._handle_response(resp, 204, "Could not get rmmp.")

    def cancel_rmmp(self) -> None:
        resp = self._post("users/rmmp", params={"action": "cancel"})
        self._handle_response(resp, 204, "Could not cancel rmmp.")

    def motors_on(self) -> None:
        """Turns the robot's motors on.

        Operation mode has to be AUTO.
        """

        resp = self._post("rw/panel/ctrlstate", {"ctrl-state": ControllerState.motoron}, {"action": "setctrlstate"})
        self._handle_response(resp, 204, "Could not turn on motors. The controller might be in manual mode.")

    def motors_off(self) -> None:
        """Turns the robot's motors off."""

        resp = self._post("rw/panel/ctrlstate", {"ctrl-state": ControllerState.motoroff}, {"action": "setctrlstate"})
        self._handle_response(resp, 204, "Could not turn off motors.")

    def tasks(self) -> list:  # TODO dataclass
        """Returns a list of all rapid tasks."""

        resp = self._get("rw/rapid/tasks")
        self._handle_response(resp, 200, "Could not get tasks.")

        return json.loads_type(resp.text, dict)["_embedded"]["_state"]

    def all_tasks_running(self) -> bool:

        for task in self.tasks():
            if task["excstate"] != "star":
                return False
        return True

    def activate_task(self, task: str) -> None:

        resp = self._post(f"rw/rapid/tasks/{task}", params={"action": "activate"})
        self._handle_response(resp, 204, f"Failed to activate task {task}.")

    def activate_all_tasks(self) -> None:

        for task in self.tasks():
            self.activate_task(task["name"])

    def start_RAPID(self, wait_until_started: bool = True) -> None:
        """Resets program pointer to main procedure in RAPID and starts RAPID
        execution."""

        resp = self._post(
            "rw/rapid/execution",
            {
                "regain": "continue",
                "execmode": "continue",
                "cycle": "forever",
                "condition": "none",
                "stopatbp": "disabled",
                "alltaskbytsp": "false",
            },
            {"action": "start"},
        )

        self._handle_response(
            resp,
            204,
            f"""
            Could not start RAPID. Possible causes:
            * Operating mode might not be AUTO. Current opmode: {self.get_operation_mode()}.
            * Motors might be turned off. Current ctrlstate: {self.get_controller_state()}.
            * RAPID might have write access.
            """,
        )

        if not wait_until_started:
            return

        # TODO use websockets
        for _ in range(100):
            if self.is_running():
                break
            time.sleep(0.1)
        else:
            raise RwsException("Failed to start RAPID.")

    def stop_RAPID(self, wait_until_stopped: bool = True) -> None:
        """Stops RAPID execution."""

        resp = self._post("rw/rapid/execution", {"stopmode": "stop", "usetsp": "normal"}, {"action": "stop"})
        self._handle_response(resp, 204, "Could not stop RAPID execution")

        if not wait_until_stopped:
            return

        # TODO use websockets
        for _ in range(100):
            if self.is_stopped():
                break
            time.sleep(0.1)
        else:
            raise RwsException("Failed to stop RAPID.")

    def get_execution_state(self) -> ExecutionState:
        """Gets the execution state of the controller."""

        resp = self._get("rw/rapid/execution")
        self._handle_response(resp, 200, "Could not get execution state.")

        return ExecutionState(json.loads_type(resp.text, dict)["_embedded"]["_state"][0]["ctrlexecstate"])

    def is_running(self) -> bool:
        """Checks the execution state of the controller and."""

        return self.get_execution_state() == ExecutionState.running

    def is_stopped(self) -> bool:
        """Checks the execution state of the controller and."""

        return self.get_execution_state() == ExecutionState.stopped

    def get_operation_mode(self) -> str:  # TODO enum
        """Gets the operation mode of the controller."""

        resp = self._get("rw/panel/opmode")
        self._handle_response(resp, 200, "Could not get operation mode.")
        return json.loads_type(resp.text, dict)["_embedded"]["_state"][0]["opmode"]

    def get_controller_state(self) -> ControllerState:
        """Gets the controller state."""

        resp = self._get("rw/panel/ctrlstate")
        self._handle_response(resp, 200, "Could not get controller state.")
        return ControllerState(json.loads_type(resp.text, dict)["_embedded"]["_state"][0]["ctrlstate"])

    def block_while_running(self, cancel_event: Event) -> None:

        # is_running is not enough - "Motion supervision" stops only one task
        while self.all_tasks_running() and not cancel_event.is_set():  # TODO use websockets callback
            time.sleep(0.1)

        if not cancel_event.is_set():
            raise ProgramStopped()


class CmdCodes(IntEnum):
    ping = 0
    goto_pose_linear = 1  # MoveL
    goto_joints = 2  # MoveAbsJ
    get_pose = 3  # CRobT
    get_joints = 4  # CJointT
    goto_pose = 5  # MoveJ
    set_tool = 6  # Redefine currentTool in SERVER_*.mod
    set_speed = 8  # Redefine currentSpeed in SERVER_*.mod
    set_zone = 9  # Redefine currentZone in SERVER_*.mod
    set_conf = 10  # Redefine currentConf in SERVER_*.mod

    goto_pose_sync = 11  # MoveL with sync
    goto_joints_sync = 12  # MoveAbsJ with sync
    goto_pose_delta = 13  # MoveL to "current pose + delta"

    close_gripper = 20  # g_GripIn
    open_gripper = 21  # g_GripOut
    calibrate_gripper = 22  # g_Init
    set_gripper_max_speed = 23  # g_SetMaxSpd
    set_gripper_force = 24  # g_SetForce
    move_gripper = 25  # g_MoveTo
    get_gripper_width = 26  # g_GetPos

    buffer_add = 30
    buffer_clear = 31
    buffer_size = 32
    buffer_move = 33  # A series of MoveL
    set_circ_point = 35
    move_by_circ_point = 36  # MoveC

    is_pose_reachable = 40  # isPoseReachable
    is_joints_reachable = 41  # isJointsReachable
    ik = 42
    fk = 43

    set_lead_through = 60
    is_lead_through = 61

    is_gripper_calibrated = 70

    close_connection = 99

    reset_home = 100  # MoveAbsJ to Home


class ResCodes(IntEnum):

    failure = 0
    success = 1


class SubCodes(IntEnum):

    pose = 0
    state = 1


class YumiException(Arcor2Exception):
    pass


class YuMiCommException(YumiException):
    """Communication failure.

    Usually occurs due to timeouts.
    """

    pass


class YuMiControlException(YumiException):
    """Failure of control, typically due to a kinematically unreachable
    pose."""

    def __init__(self, req_packet: RequestPacket, res: RawResponse, *args) -> None:
        super().__init__(*args)
        self.req_packet = req_packet
        self.res = res

    def __str__(self) -> str:
        return self.res.message


def message_to_pose(message: str) -> Pose:
    tokens = message.split()

    if len(tokens) != 7:
        raise YumiException("Invalid format for pose! Got:\n{0}".format(message))
    pose_vals = [float(token) for token in tokens]
    q = pose_vals[3:]
    t = pose_vals[:3]

    try:
        return Pose(
            Position(t[0], t[1], t[2]) * MM_TO_METERS, Orientation.from_quaternion(quaternion.from_float_array(q))
        )
    except (IndexError, ValueError):
        raise YumiException("Invalid pose.")


class YumiSocket:
    def __init__(self, ip: str, port: int, bufsize, timeout: float) -> None:

        self._ip = ip
        self._port = port
        self._timeout = timeout
        self._bufsize = bufsize
        self._lock = Lock()

        with self._lock:

            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            self._socket.setsockopt(socket.SOL_TCP, socket.TCP_KEEPIDLE, 1)
            self._socket.setsockopt(socket.SOL_TCP, socket.TCP_KEEPINTVL, 1)
            self._socket.setsockopt(socket.SOL_TCP, socket.TCP_KEEPCNT, 2)

            self._socket.settimeout(self._timeout)
            try:
                self._socket.connect((self._ip, self._port))
            except socket.timeout:
                raise YuMiCommException(f"Failed to connect to {self._ip}:{self._port}.")
        logger.debug("Socket successfully opened!")

    def close(self) -> None:
        logger.debug("Shutting down yumi ethernet interface")
        with self._lock:
            if self._socket:
                self._socket.close()

    def send_request(self, req_packet: RequestPacket) -> RawResponse:

        logger.debug("Sending: {0}".format(req_packet))

        with self._lock:

            if not self._socket:
                raise YumiException()

            raw_res: None | RawResponse = None

            self._socket.settimeout(req_packet.timeout)

            try:
                self._socket.send(req_packet.req.encode())
            except socket.error as e:
                raise YuMiCommException("Failed to send request.") from e
                # TODO: better way to handle this mysterious bad file descriptor error
                # if e.errno == 9:
                #    self._reset_socket()

            try:
                recv = self._socket.recv(self._bufsize).decode()
            except socket.error as e:
                raise YuMiCommException("Failed to get response.") from e

        logger.debug("Received: {0}".format(raw_res))

        if not recv:
            raise YuMiCommException("Empty response.")

        tokens = recv.split()

        try:
            res = RawResponse(int(tokens[0]), int(tokens[1]), " ".join(tokens[2:]))
        except (IndexError, ValueError):
            raise YuMiCommException("Invalid response.")
        return res


class YuMiArm:
    """Interface to a single arm of an ABB YuMi robot.

    Communicates with the robot over Ethernet.
    """

    JOINTS = 7

    def __init__(self, name: str, ip: str, port: int, bufsize: int, motion_timeout: float, comm_timeout: float) -> None:
        """Initializes a YuMiArm interface. This interface will communicate
        with one arm (port) on the YuMi Robot. This uses a subprocess to handle
        non-blocking socket communication with the RAPID server.

        Parameters
        ----------
            name : string
                    Name of the arm {'left', 'right'}
            ip : string formated ip address, optional
                    IP of YuMi Robot.
                    Default uses the one in YuMiConstants
            port : int, optional
                    Port of target arm's server.
                    Default uses the port for the left arm from YuMiConstants.
            bufsize : int, optional
                    Buffer size for ethernet responses
            motion_timeout : float, optional
                    Timeout for motion commands.
                    Default from YuMiConstants.MOTION_TIMEOUT
            comm_timeout : float, optional
                    Timeout for non-motion ethernet communication.
                    Default from YuMiConstants.COMM_TIMEOUT
        """
        self.name = name
        self._motion_timeout = motion_timeout
        self._comm_timeout = comm_timeout
        self._ip = ip
        self._port = port
        self._bufsize = bufsize

        self._main_socket = YumiSocket(self._ip, self._port, self._bufsize, self._comm_timeout)

        # TODO this two could be optional as the _main_socket can do the same (just not in parallel)
        self._poses_socket = YumiSocket(self._ip, self._port + 2, self._bufsize, self._comm_timeout)
        self._joints_socket = YumiSocket(self._ip, self._port + 4, self._bufsize, self._comm_timeout)

        self._sockets = (self._main_socket, self._poses_socket, self._joints_socket)

    def reconnect(self) -> None:

        self.terminate()
        self._main_socket = YumiSocket(self._ip, self._port, self._bufsize, self._comm_timeout)
        self._poses_socket = YumiSocket(self._ip, self._port + 2, self._bufsize, self._comm_timeout)
        self._joints_socket = YumiSocket(self._ip, self._port + 4, self._bufsize, self._comm_timeout)

    def terminate(self) -> None:
        """Stops subprocess for ethernet communication.

        Allows program to exit gracefully.
        """

        for s in self._sockets:
            s.close()

    def _request(self, req: str, timeout: None | float = None, socket: None | YumiSocket = None) -> RawResponse:

        if timeout is None:
            timeout = self._comm_timeout

        if socket is None:
            socket = self._main_socket

        req_packet = RequestPacket(req, timeout, True)
        logger.debug("Process req: {0}".format(req_packet))

        res = socket.send_request(req_packet)

        logger.debug("res: {0}".format(res))

        if res.res_code != ResCodes.success:
            raise YuMiControlException(req_packet, res)

        return res

    @staticmethod
    def _construct_req(code: CmdCodes, body="") -> str:
        return "{0:d} {1}#".format(code.value, body)

    @staticmethod
    def _iter_to_str(template: str, iterable: Iterable):
        result = ""
        for val in iterable:
            result += template.format(val).rstrip("0").rstrip(".") + " "
        return result

    @classmethod
    def _get_pose_body(cls, pose: Pose) -> str:

        pose = copy.deepcopy(pose)
        pose.position *= METERS_TO_MM
        body = "{0}{1}".format(
            cls._iter_to_str("{:.2f}", list(pose.position)),
            cls._iter_to_str("{:.5f}", quaternion.as_float_array(pose.orientation.as_quaternion())),
        )
        return body

    def ping(self) -> None:
        """Pings the remote server."""
        for s in self._sockets:
            self._request(self._construct_req(CmdCodes.ping), socket=s)

    def joint_names(self) -> set[str]:
        assert self.name
        return {f"yumi_joint_{i + 1}_{self.name[0]}" for i in range(self.JOINTS)}

    def _response_to_joints(self, res: RawResponse) -> list[Joint]:

        tokens = res.message.split()

        if len(tokens) != self.JOINTS:
            raise YumiException(f"Invalid format for states! Got: '{res.message}'.")
        values = [math.radians(float(token)) for token in tokens]

        assert self.name
        return [Joint(f"yumi_joint_{i + 1}_{self.name[0]}", j) for i, j in enumerate(values)]

    def _joints_to_str(self, joints: list[Joint]) -> str:
        return self._iter_to_str("{:.2f}", [math.degrees(j.value) for j in joints])

    def joints(self, include_gripper: bool = False) -> list[Joint]:
        joints = self._response_to_joints(
            self._request(self._construct_req(CmdCodes.get_joints), socket=self._joints_socket)
        )

        if include_gripper:
            w = self.get_gripper_width()
            joints.append(Joint(f"gripper_{self.name[0]}_joint", w))
            joints.append(Joint(f"gripper_{self.name[0]}_joint_m", w))

        return joints

    def get_pose(self) -> Pose:

        res = self._request(self._construct_req(CmdCodes.get_pose), socket=self._poses_socket)
        return message_to_pose(res.message)

    @property
    def lead_through(self) -> bool:

        req = self._construct_req(CmdCodes.is_lead_through)
        res = self._request(req)
        return bool(int(res.message))

    @lead_through.setter
    def lead_through(self, enabled: bool) -> None:

        req = self._construct_req(CmdCodes.set_lead_through, f"{int(enabled)} ")
        self._request(req)

    def is_pose_reachable(self, pose: Pose) -> bool:

        body = self._get_pose_body(pose)
        req = self._construct_req(CmdCodes.is_pose_reachable, body)
        res = self._request(req)
        return bool(int(res.message))

    def is_gripper_calibrated(self) -> bool:

        req = self._construct_req(CmdCodes.is_gripper_calibrated)
        res = self._request(req)
        return bool(int(res.message))

    def ik(self, pose: Pose) -> list[Joint]:
        try:
            return self._response_to_joints(self._request(self._construct_req(CmdCodes.ik, self._get_pose_body(pose))))
        except YuMiControlException as e:
            raise MultiArmRobot.KinematicsException(str(e))

    def fk(self, joints: list[Joint]) -> Pose:

        self._check_and_sort_joints(joints)
        try:
            return message_to_pose(self._request(self._construct_req(CmdCodes.fk, self._joints_to_str(joints))).message)
        except YuMiControlException as e:
            raise MultiArmRobot.KinematicsException(str(e))

    def _check_and_sort_joints(self, joints: list[Joint]) -> None:

        if len(joints) != self.JOINTS:
            raise YumiException("Invalid number of joints.")

        for j in joints:

            arr = j.name.split("_")

            try:
                idx = int(arr[2])
            except ValueError:
                raise YumiException(f"Invalid format of joint name: {j.name}.")

            if len(arr) != 4 or arr[0] != "yumi" or arr[1] != "joint" or not 0 < idx <= self.JOINTS:
                raise YumiException(f"Invalid format of joint name: {j.name}.")

            if len(arr[3]) != 1 or arr[3] != self.name[0]:
                raise YumiException(f"Joint name {j.name} not valid for {self.name} arm.")

        joints.sort(key=lambda x: int(x.name.split("_")[2]))

    def goto_joints(self, joints: list[Joint]) -> None:
        """Commands the YuMi to goto the given state (joint angles)"""

        self._check_and_sort_joints(joints)
        self._request(
            self._construct_req(CmdCodes.goto_joints, self._joints_to_str(joints)), timeout=self._motion_timeout
        )

    def goto_joints_sync(self, joints: list[Joint]) -> None:

        self._check_and_sort_joints(joints)
        self._request(
            self._construct_req(CmdCodes.goto_joints_sync, self._joints_to_str(joints)), timeout=self._motion_timeout
        )

    def goto_pose(self, pose: Pose, linear: bool = True, relative: bool = False) -> None:
        """Commands the YuMi to goto the given pose.

        Parameters
        ----------
        pose : RigidTransform
        linear : bool, optional
            If True, will use MoveL in RAPID to ensure linear path.
            Otherwise use MoveJ in RAPID, which does not ensure linear path.
            Defaults to True
        relative : bool, optional
            If True, will use goto_pose_relative by computing the delta pose from current pose to target pose.
            Defaults to False
        """
        if relative:
            cur_pose = self.get_pose()
            delta_pose = Pose.from_tr_matrix(cur_pose.inversed().as_tr_matrix() * pose.as_tr_matrix())
            rot = np.rad2deg(quaternion.as_euler_angles(delta_pose.orientation.as_quaternion()))
            self.goto_pose_delta(delta_pose.position, rot)
        else:
            body = self._get_pose_body(pose)
            if linear:
                cmd = CmdCodes.goto_pose_linear
            else:
                cmd = CmdCodes.goto_pose
            req = self._construct_req(cmd, body)
            self._request(req, timeout=self._motion_timeout)

    def goto_pose_sync(self, pose: Pose) -> None:
        body = self._get_pose_body(pose)
        req = self._construct_req(CmdCodes.goto_pose_sync, body)
        self._request(req, timeout=self._motion_timeout)

    def goto_pose_delta(self, translation: Iterable[float], rotation: None | Iterable[float] = None) -> None:
        """Goto a target pose by transforming the current pose using the given
        translation and rotation.

        Parameters
        ----------
        translation : list-like with length 3
            The translation vector (x, y, z) in meters.
        rotation : list-like with length 3, optional
            The euler angles of given rotation in degrees.
            Defaults to 0 degrees - no rotation.
        """
        translation = [val * METERS_TO_MM for val in translation]
        translation_str = self._iter_to_str("{:.1f}", translation)
        rotation_str = ""
        if rotation is not None:
            rotation_str = self._iter_to_str("{:.5f}", rotation)

        body = translation_str + rotation_str
        req = self._construct_req(CmdCodes.goto_pose_delta, body)
        self._request(req, timeout=self._motion_timeout)

    def set_tool(self, pose: Pose) -> None:
        """Sets the Tool Center Point (TCP) of the arm using the given pose."""
        body = self._get_pose_body(pose)
        req = self._construct_req(CmdCodes.set_tool, body)
        self._request(req)

    def set_speed(self, speed_data: Iterable[float]) -> None:
        """Sets the target speed of the arm's movements.

        Parameters
        ----------
        speed_data : list-like with length 4
            Specifies the speed data that will be used by RAPID when executing motions.
            Should be generated using YuMiRobot.get_v
        """

        body = self._iter_to_str("{:.2f}", speed_data)
        req = self._construct_req(CmdCodes.set_speed, body)
        self._request(req)

    def set_zone(self, zone_data: dict) -> None:
        """Set zone data for future moves.

        Parameters
        ----------
        zone_data: list-like with length 4
            Specifies the zone data that will be used by RAPID when executing motions.
        """
        pm = zone_data["point_motion"]
        data = (pm,) + zone_data["values"]
        body = self._iter_to_str("{:2f}", data)
        req = self._construct_req(CmdCodes.set_zone, body)
        self._request(req)

    def set_conf(self, conf_data: Iterable[float]) -> None:
        """Set confdata for future moves.

        Parameters
        ----------
        conf_data : list-like with length 4
            Specifies the arm configuration data that will be used by RAPID when executing motions.
        """
        body = self._iter_to_str("{:d}", conf_data)
        req = self._construct_req(CmdCodes.set_conf, body)
        self._request(req)

    def move_circular(self, center_pose: Pose, target_pose: Pose) -> None:
        """Goto a target pose by following a circular path around the
        center_pose.

        Parameters
        ----------
        center_pose : RigidTransform
            Pose for the center of the circle for circular movement.
        target_pose : RigidTransform
            Target pose
        """
        body_set_circ_point = self._get_pose_body(center_pose)
        body_move_by_circ_point = self._get_pose_body(target_pose)

        req_set_circ_point = self._construct_req(CmdCodes.set_circ_point, body_set_circ_point)
        req_move_by_circ_point = self._construct_req(CmdCodes.move_by_circ_point, body_move_by_circ_point)

        res_set_circ_point = self._request(req_set_circ_point, True)
        if res_set_circ_point is None:
            raise YumiException("Set circular point failed.")
        else:
            self._request(req_move_by_circ_point, timeout=self._motion_timeout)

    def buffer_add_single(self, pose: Pose) -> None:
        """Add single pose to the linear movement buffer in RAPID."""
        body = self._get_pose_body(pose)
        req = self._construct_req(CmdCodes.buffer_add, body)
        self._request(req)

    def buffer_add_all(self, pose_list: list[Pose]) -> None:
        """Add a list of poses to the linear movement buffer in RAPID."""

        for pose in pose_list:
            self.buffer_add_single(pose)

    def buffer_clear(self) -> None:
        """Clears the linear movement buffer in RAPID."""
        req = self._construct_req(CmdCodes.buffer_clear)
        self._request(req)

    def buffer_size(self) -> int:
        """Gets the current linear movement buffer size."""
        req = self._construct_req(CmdCodes.buffer_size)
        res = self._request(req)

        try:
            return int(res.message)
        except ValueError as e:
            raise YumiException() from e

    def buffer_move(self) -> None:
        """Executes the linear movement buffer."""

        self._request(self._construct_req(CmdCodes.buffer_move), timeout=self._motion_timeout)

    def open_gripper(
        self,
        force: None | float = None,
        width: None | float = None,
        no_wait: bool = False,
    ) -> None:
        """Opens the gripper to the target width.

        Parameters
        ----------
        force : float, optional, in newtons.
            Sets the corresponding outward force in Newtons.
            Defaults to 20 N, which is the maximum grip force.
        width : float, optional, in meters.
            Sets the target width of gripper open motion.
            Defaults to maximum opening.
        """
        if force is None:
            force = MAX_GRIPPER_FORCE
        if width is not None:
            width = METERS_TO_MM * width
            body = self._iter_to_str("{0:.1f}", [force, width] + ([0] if no_wait else []))
            req = self._construct_req(CmdCodes.open_gripper, body)
        else:
            body = self._iter_to_str("{0:.1f}", [force] + ([0] if no_wait else []))
            req = self._construct_req(CmdCodes.open_gripper, body)
        self._request(req, timeout=self._motion_timeout)

    def close_gripper(self, force=MAX_GRIPPER_FORCE, width: float = 0.0, no_wait: bool = False) -> None:
        """Closes the gripper as close to  as possible with maximum force.

        Parameters
        ----------
        force : float, optional, in newtons.
            Sets the corresponding gripping force in Newtons.
            Defaults to 20 N, which is the maximum grip force.
        width : float, optional, in meters.
            Sets the target width of gripper close motion. Cannot be greater than max gripper width.
            Defaults to 0.
        """
        if force < 0 or force > MAX_GRIPPER_FORCE:
            raise ValueError("Gripper force can only be between {} and {}. Got {}.".format(0, MAX_GRIPPER_FORCE, force))
        if width < 0 or width > MAX_GRIPPER_WIDTH:
            raise ValueError("Gripper width can only be between {} and {}. Got {}.".format(0, MAX_GRIPPER_WIDTH, width))

        width = METERS_TO_MM * width
        body = self._iter_to_str("{0:.1f}", [force, width] + ([0] if no_wait else []))
        req = self._construct_req(CmdCodes.close_gripper, body)
        self._request(req, timeout=self._motion_timeout)

    def move_gripper(self, width: float, no_wait: bool = False) -> None:
        """Moves the gripper to the given width in meters.

        Parameters
        ----------
        width : float
            Target width in meters
        no_wait : bool, optional
            If True, the RAPID server will continue without waiting for the gripper to reach its target width
            Defaults to False
        """
        lst = [width * METERS_TO_MM]
        if no_wait:
            lst.append(0)
        body = self._iter_to_str("{0:.1f}", lst)
        req = self._construct_req(CmdCodes.move_gripper, body)
        self._request(req, timeout=self._motion_timeout)

    def calibrate_gripper(
        self,
        max_speed: None | float = None,
        hold_force: None | float = None,
        phys_limit: None | float = None,
        skip_if_already_calibrated=True,
    ) -> None:
        """Calibrates the gripper.

        Parameters
        ----------
        max_speed : float, optional
            Max speed of the gripper in mm/s.
            Defaults to None. If None, will use maximum speed in RAPID.
        hold_force : float, optional
            Hold force used by the gripper in N.
            Defaults to None. If None, will use maximum force the gripper can provide (20N).
        phys_limit : float, optional
            The maximum opening of the gripper.
            Defaults to None. If None, will use maximum opening the gripper can provide (25mm).

        Notes
        -----
        All 3 values must be provided, or they'll all default to None.
        """

        if skip_if_already_calibrated and self.is_gripper_calibrated():
            return

        if None in (max_speed, hold_force, phys_limit):
            body = ""
        else:
            body = self._iter_to_str("{:.1f}", [max_speed, hold_force, phys_limit])
        req = self._construct_req(CmdCodes.calibrate_gripper, body)
        self._request(req, timeout=self._motion_timeout)

    def set_gripper_force(self, force: float) -> None:
        """Sets the gripper hold force.

        Parameters
        ----------
        force : float
            Hold force by the gripper in N.
        """
        body = self._iter_to_str("{:.1f}", [force])
        req = self._construct_req(CmdCodes.set_gripper_force, body)
        self._request(req)

    def set_gripper_max_speed(self, max_speed: float) -> None:
        """Sets the gripper max speed.

        Parameters
        ----------
        max_speed : float
            In mm/s.
        """
        body = self._iter_to_str("{:1f}", [max_speed])
        req = self._construct_req(CmdCodes.set_gripper_max_speed, body)
        self._request(req)

    def get_gripper_width(self) -> float:
        """Get width of current gripper in meters."""
        req = self._construct_req(CmdCodes.get_gripper_width)
        res = self._request(req)
        width = float(res.message) * MM_TO_METERS
        return width

    def reset_home(self) -> None:
        """Resets the arm to home using joints."""
        self._request(self._construct_req(CmdCodes.reset_home))


class YumiArms(StrEnum):

    LEFT: str = "left"
    RIGHT: str = "right"


class YuMi(MultiArmRobot):
    """Interface to both arms of an ABB YuMi robot.

    Communicates with the robot over Ethernet.
    """

    _ABSTRACT = False
    urdf_package_name = "yumi.zip"

    def __init__(self, obj_id: str, name: str, pose: Pose, settings: YumiSettings) -> None:

        super().__init__(obj_id, name, pose, settings)

        self._executor = cf.ThreadPoolExecutor()

        self._rws = RWS(f"http://{self.settings.ip}")

        if self._rws.get_operation_mode() != "AUTO":
            raise YumiException("Not in auto mode.")

        # TODO with claimed mastership, it is not possible to start RAPID - why??
        # self._rws.request_mastership()

        try:
            state = self._rws.get_controller_state()

            # https://developercenter.robotstudio.com/api/rwsApi/panel_ctrlstate_get_page.html
            if state == ControllerState.emergencystop:
                raise YumiException("Emergency stop is active.")
            elif state == ControllerState.sysfail:
                raise YumiException("Robot needs to be restarted.")
            elif state == ControllerState.motoroff:
                self._rws.motors_on()

            if self._rws.is_running():
                self._rws.stop_RAPID()

            self._rws.reset_pp()
            self._rws.activate_all_tasks()
            self._rws.start_RAPID()

        except YumiException:
            # self._rws.release_mastership()
            raise

        self._buffsize = 4096
        self._motion_timeout = 20.0
        self._comm_timeout = 5.0
        self._speed: None | int = None

        self._left = YuMiArm(YumiArms.LEFT, settings.ip, 5000, self._buffsize, self._motion_timeout, self._comm_timeout)
        self._right = YuMiArm(
            YumiArms.RIGHT, settings.ip, 5001, self._buffsize, self._motion_timeout, self._comm_timeout
        )
        self._mapping: dict[str, YuMiArm] = {YumiArms.LEFT: self._left, YumiArms.RIGHT: self._right}

        self.default_configuration()
        self.calibrate_grippers()  # TODO only if not calibrated

        if self.settings.home_on_start:
            self._left.reset_home()
            self._right.reset_home()

    def default_configuration(self) -> None:

        # TODO set according to the used gripper
        # https://github.com/galou/yumipy/blob/robotware6_06/yumipy/yumi_constants.py#L117
        self.set_tool(Pose())
        self.set_z("fine")

        self._left.set_conf([0, 0, 0, 4])
        self._right.set_conf([0, 0, 0, 4])

    def recover(self) -> None:
        """Recover from unhandled error in program (e.g. predicted collision,
        moving in wrong direction)."""

        # sometimes, stop+reset is needed to start RAPID again and sometimes it fails and then RAPID starts just fine
        # no idea why it is like this...
        try:
            self._rws.stop_RAPID()
        except RwsException:
            pass
        try:
            self._rws.reset_pp()
        except RwsException:
            pass

        try:
            # TODO when stop comes from "Motion supervision" (collision occurred), this fails
            # ...maybe the collision has to be acknowledged somehow?
            # how to check if collision happened? /rw/panel/coldetstate?
            # also see https://forums.robotstudio.com/discussion/5991/error-recovery-for-motion-supervision (last post)
            self._rws.start_RAPID()
        except RwsException as e:
            raise YumiException(f"Failed to recover from stopped program. {str(e)}") from e

        for arm in self.arms:
            arm.reconnect()

        self.default_configuration()
        self._speed = None

    @property
    def settings(self) -> YumiSettings:
        return cast(YumiSettings, super().settings)

    def _arm_by_name(self, name: None | str) -> YuMiArm:

        if name is None:
            raise YumiException("Arm has to be specified.")

        try:
            return self._mapping[name]
        except KeyError:
            raise YumiException("Unknown arm name.")

    # ------------------------------------------------------------------------------------------------------------------

    def get_arm_ids(self) -> set[str]:
        return set(self._mapping)

    def get_end_effectors_ids(self, arm_id: None | str = None) -> set[str]:

        self._arm_by_name(arm_id)
        return {"default"}

    def get_end_effector_pose(self, end_effector: str, arm_id: None | str = None) -> Pose:

        arm = self._arm_by_name(arm_id)
        return tr.make_pose_abs(self.pose, arm.get_pose())

    def robot_joints(self, include_gripper: bool = False, arm_id: None | str = None) -> list[Joint]:

        if arm_id is None:

            ret: list[Joint] = []
            futures: list[cf.Future] = [
                self._executor.submit(self._left.joints, include_gripper),
                self._executor.submit(self._right.joints, include_gripper),
            ]

            try:
                states = [f.result(timeout=self._comm_timeout) for f in futures]
            except cf.TimeoutError:
                raise YuMiCommException("Failed to get joints.")

            ret.extend(states[0])
            ret.extend(states[1])

            return ret

        return self._arm_by_name(arm_id).joints(include_gripper)

    def grippers(self, arm_id: None | str = None) -> set[str]:
        return set(self._mapping)

    def suctions(self, arm_id: None | str = None) -> set[str]:
        return set()

    def move_to_pose(
        self,
        end_effector_id: str,
        target_pose: Pose,
        speed: float,
        safe: bool = True,
        linear: bool = True,
        arm_id: None | str = None,
    ) -> None:
        """Move given robot's end effector to the selected pose.

        :param end_effector_id:
        :param target_pose:
        :param speed:
        :param safe:
        :return:
        """

        assert 0.0 <= speed <= 1.0

        with self._move_lock:

            self.set_v(int(speed * self.settings.max_tcp_speed * METERS_TO_MM))

            evt = Event()

            futures: list[cf.Future] = [
                self._executor.submit(self._rws.block_while_running, evt),
                self._executor.submit(
                    self._arm_by_name(arm_id).goto_pose, tr.make_pose_rel(self.pose, target_pose), linear
                ),
            ]

            for f in cf.as_completed(futures):

                try:
                    f.result()
                except YumiException:
                    evt.set()
                    raise
                except ProgramStopped:
                    self.recover()

                    # TODO read log and give proper message?
                    raise YumiException("Impossible motion.")

                else:
                    evt.set()  # this terminates block_while_running

    def move_to_joints(
        self, target_joints: list[Joint], speed: float, safe: bool = True, arm_id: None | str = None
    ) -> None:
        """Sets target joint values.

        :param target_joints:
        :param speed:
        :param safe:
        :return:
        """

        assert 0.0 <= speed <= 1.0

        with self._move_lock:

            self.set_v(int(speed * self.settings.max_tcp_speed * METERS_TO_MM))

            if arm_id is None:

                left = [j for j in target_joints if j.name.endswith("_l")]
                right = [j for j in target_joints if j.name.endswith("_r")]

                self.goto_joints_sync(left, right)
            else:
                self._arm_by_name(arm_id).goto_joints(target_joints)

    def inverse_kinematics(
        self,
        end_effector_id: str,
        pose: Pose,
        start_joints: None | list[Joint] = None,
        avoid_collisions: bool = True,
        arm_id: None | str = None,
    ) -> list[Joint]:
        """Computes inverse kinematics.

        :param end_effector_id: IK target pose end-effector
        :param pose: IK target pose
        :param start_joints: IK start joints
        :param avoid_collisions: Return non-collision IK result if true
        :return: Inverse kinematics
        """

        return self._arm_by_name(arm_id).ik(tr.make_pose_rel(self.pose, pose))

    def forward_kinematics(self, end_effector_id: str, joints: list[Joint], arm_id: None | str = None) -> Pose:
        """Computes forward kinematics.

        :param end_effector_id: Target end effector name
        :param joints: Input joint values
        :return: Pose of the given end effector
        """

        return tr.make_pose_abs(self.pose, self._arm_by_name(arm_id).fk(joints))

    def get_hand_teaching_mode(self, arm_id: None | str = None) -> bool:
        return self._arm_by_name(arm_id).lead_through

    def set_hand_teaching_mode(self, enabled: bool, arm_id: None | str = None) -> None:
        self._arm_by_name(arm_id).lead_through = enabled

    def cleanup(self) -> None:

        self.wait_for_all(
            [self._executor.submit(arm.terminate) for arm in self.arms],
            self._comm_timeout,
            "Failed to terminate connection.",
        )
        self._executor.shutdown()
        self._rws.stop_RAPID()
        self._rws.motors_off()
        # self._rws.release_mastership()

    # ------------------------------------------------------------------------------------------------------------------

    def pick(
        self,
        arm: YumiArms,
        pose: Pose,
        approach_speed: float = 0.5,
        pick_speed: float = 0.25,
        vertical_offset: float = 0.05,
        *,
        an: None | str = None,
    ) -> None:
        """Picks an object from a horizontal surface.

        :param arm: Selected arm.
        :param pose: Gripping pose.
        :param approach_speed: How fast will the robot approach to pre-pick pose.
        :param pick_speed: How fast will the robot pick the object up.
        :param vertical_offset: Vertical offset of the pre-pick pose.
        :param an:
        :return:
        """

        pre_pick_pose = copy.deepcopy(pose)
        pre_pick_pose.position.z += vertical_offset

        self.move_arm(arm, pre_pick_pose, approach_speed)
        self.open_gripper(arm)
        self.move_arm(arm, pose, pick_speed)
        self.close_gripper(arm)
        self.move_arm(arm, pre_pick_pose, pick_speed)

    pick.__action__ = ActionMetadata(composite=True)  # type: ignore

    def place(
        self,
        arm: YumiArms,
        pose: Pose,
        approach_speed: float = 0.5,
        place_speed: float = 0.25,
        vertical_offset: float = 0.05,
        *,
        an: None | str = None,
    ) -> None:
        """Places an object on a horizontal surface.

        :param arm: Selected arm.
        :param pose: Placing pose.
        :param approach_speed: How fast will the robot approach to pre-place pose.
        :param place_speed: How fast will the robot place the object.
        :param vertical_offset: Vertical offset of the pre-place pose.
        :param an:
        :return:
        """

        pre_place_pose = copy.deepcopy(pose)
        pre_place_pose.position.z += vertical_offset

        self.move_arm(arm, pre_place_pose, approach_speed)
        self.move_arm(arm, pose, place_speed)
        self.open_gripper(arm)
        self.move_arm(arm, pre_place_pose, place_speed)
        self.close_gripper(arm)

    place.__action__ = ActionMetadata(composite=True)  # type: ignore

    def move_arm(
        self, arm: YumiArms, pose: Pose, speed: float = 0.5, linear: bool = True, *, an: None | str = None
    ) -> None:
        """Moves the arm's TCP to the given pose.

        :param arm: Selected arm.
        :param pose: Target pose.
        :param speed: Speed of movement.
        :param linear: Selects 'linear' movement over the 'joints' default one.
        :return:
        """

        assert 0.0 <= speed <= 1.0

        self.move_to_pose("", pose, speed, False, linear, arm)

    move_arm.__action__ = ActionMetadata()  # type: ignore

    def close_gripper(self, arm: YumiArms, force: float = 1.0, width: float = 0.0, *, an: None | str = None) -> None:
        """Closes the gripper as close to as possible with maximum force.

        :param arm: Selected arm.
        :param force: Maximum force in newtons.
        :param width: Target state in millimetres..
        :return:
        """

        assert 0.0 <= force <= 1.0
        assert 0.0 <= width <= 1.0

        self._arm_by_name(arm).close_gripper(force * MAX_GRIPPER_FORCE, width * MAX_GRIPPER_WIDTH)

    close_gripper.__action__ = ActionMetadata()  # type: ignore

    def open_gripper(self, arm: YumiArms, force: float = 1.0, width: float = 1.0, *, an: None | str = None) -> None:
        """Opens the gripper to the target width.

        :param arm: Selected arm.
        :param force: Maximum force in newtons.
        :param width: Target opening in millimetres.
        :return:
        """

        assert 0.0 <= force <= 1.0
        assert 0.0 <= width <= 1.0

        self._arm_by_name(arm).open_gripper(force * MAX_GRIPPER_FORCE, width * MAX_GRIPPER_WIDTH)

    open_gripper.__action__ = ActionMetadata()  # type: ignore

    def move_both_arms(self, left_pose: Pose, right_pose: Pose, speed: float = 0.5, *, an: None | str = None) -> None:
        """Commands both arms to go to assigned poses in sync.

        Sync means both motions will end at the same time.

        :param left_pose: Target pose for the left arm.
        :param right_pose: Target pose for the left arm.
        :param speed: Speed of the movement.
        :return:
        """

        assert 0.0 <= speed <= 1.0

        self.set_v(int(speed * self.settings.max_tcp_speed * METERS_TO_MM))

        with self._move_lock:

            evt = Event()

            futures: list[cf.Future] = [
                self._executor.submit(self._rws.block_while_running, evt),
                self._executor.submit(self._left.goto_pose_sync, tr.make_pose_rel(self.pose, left_pose)),
                self._executor.submit(self._right.goto_pose_sync, tr.make_pose_rel(self.pose, right_pose)),
            ]

            try:
                for f in cf.as_completed(futures, self._motion_timeout):
                    f.result()
            except YumiException:
                evt.set()
                raise
            except ProgramStopped:
                self.recover()

                # TODO read log and give proper message?
                raise YumiException("Impossible motion.")
            else:
                evt.set()  # this terminates block_while_running

    move_both_arms.__action__ = ActionMetadata()  # type: ignore

    # ------------------------------------------------------------------------------------------------------------------

    @property
    def arms(self) -> list[YuMiArm]:
        return [self._left, self._right]

    def open_grippers(self):
        self._left.open_gripper()
        self._right.open_gripper()

    def wait_for_all(self, futures: list[cf.Future], timeout: float, timeout_error_message: str) -> None:

        try:
            for f in cf.as_completed(futures, timeout):
                f.result()
        except cf.TimeoutError:
            raise YuMiCommException(timeout_error_message)

    def goto_joints_sync(self, left: list[Joint], right: list[Joint]) -> None:
        """Commands both arms to go to assigned states in sync. Sync means both
        motions will end at the same time.

        Parameters
        ----------
            left_state : YuMiState
                    Target state for left arm
            right_state : YuMiState
                    Target state for right arm

        Raises
        ------
        YuMiCommException
            If communication times out or socket error.
        YuMiControlException
            If commanded pose triggers any motion errors that are catchable by RAPID sever.
        """

        self.wait_for_all(
            [
                self._executor.submit(self._left.goto_joints_sync, left),
                self._executor.submit(self._right.goto_joints_sync, right),
            ],
            self._motion_timeout,
            "Failed to move to joints in sync.",
        )

    def set_v(self, n: int) -> None:
        """Sets speed for both arms using n as the speed number.

        Parameters
        ----------
            n: int
                speed number. If n = 100, then speed will be set to the corresponding v100
                specified in RAPID. Loosely, n is translational speed in milimeters per second

        Raises
        ------
        YuMiCommException
            If communication times out or socket error.
        """

        # do not set speed if no change is requested
        if self._speed is not None and self._speed == n:
            return

        speed_data = self.get_v(n)
        self.wait_for_all(
            [self._executor.submit(arm.set_speed, speed_data) for arm in self.arms],
            self._comm_timeout,
            "Failed to set speed.",
        )

    def set_z(self, name: str) -> None:
        """Sets zoning settings for both arms according to name.

        Parameters
        ----------
            name : str
                Name of zone setting. ie: "z10", "z200", "fine"

        Raises
        ------
        YuMiCommException
            If communication times out or socket error.
        """
        zone_data = self.get_z(name)
        self.wait_for_all(
            [self._executor.submit(arm.set_zone, zone_data) for arm in self.arms],
            self._comm_timeout,
            "Failed set zone data.",
        )

    def set_tool(self, pose: Pose) -> None:
        """Sets TCP (Tool Center Point) for both arms using given pose as
        offset."""

        self.wait_for_all(
            [self._executor.submit(arm.set_tool, pose) for arm in self.arms], self._comm_timeout, "Failed to set tool."
        )

    def calibrate_grippers(self) -> None:
        """Calibrates grippers for instantiated arms."""

        self.wait_for_all(
            [self._executor.submit(arm.calibrate_gripper) for arm in self.arms],
            self._motion_timeout,
            "Failed to calibrate grippers.",
        )

    @staticmethod
    def construct_speed_data(tra: float, rot: float) -> tuple[float, float, float, float]:
        """Constructs a speed data tuple that's in the same format as ones used
        in RAPID.

        Parameters
        ----------
            tra : float
                    translational speed (milimeters per second)
            rot : float
                    rotational speed (degrees per second)

        Returns:
            A tuple of correctly formatted speed data: (tra, rot, tra, rot)
        """
        return tra, rot, tra, rot

    @classmethod
    def get_v(cls, n: int) -> tuple[float, float, float, float]:
        """Gets the corresponding speed data for n as the speed number.

        Parameters
        ----------
            n : int
                    speed number. If n = 100, will return the same speed data as v100 in RAPID

        Returns
        -------
            Corresponding speed data tuple using n as speed number
        """
        return cls.construct_speed_data(n, 500)

    @classmethod
    def get_z(cls, name: str) -> dict:
        """Gets the corresponding speed data for n as the speed number.

        Parameters
        ----------
            name : str
                    Name of zone setting. ie: "z10", "z200", "fine"

        Returns
        -------
            Corresponding zone data dict to be used in set_z
        """
        values = cls.ZONE_VALUES[name]
        point_motion = 1 if name == "fine" else 0
        return {"point_motion": point_motion, "values": values}

    @staticmethod
    def construct_zone_data(pzone_tcp: float, pzone_ori: float, zone_ori: float) -> tuple[float, float, float]:
        """Constructs tuple for zone data.

        Parameters
        ----------
            pzone_tcp : float
                    path zone size for TCP
            pzone_ori : float
                    path zone size for orientation
            zone_ori : float
                    zone size for orientation

        Returns:
            A tuple of correctly formatted zone data: (pzone_tcp, pzone_ori, zone_ori)
        """
        return pzone_tcp, pzone_ori, zone_ori

    ZONE_VALUES: dict[str, tuple[float, float, float]] = {
        "fine": (0, 0, 0),  # these values actually don't matter for fine
        "z0": (0.3, 0.3, 0.03),
        "z1": (1, 1, 0.1),
        "z5": (5, 8, 0.8),
        "z10": (10, 15, 1.5),
        "z15": (15, 23, 2.3),
        "z20": (20, 30, 3),
        "z30": (30, 45, 4.5),
        "z50": (50, 75, 7.5),
        "z100": (100, 150, 15),
        "z200": (200, 300, 30),
    }
