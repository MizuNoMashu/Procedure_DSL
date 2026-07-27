"""
Client rclpy verso le action/service pubbliche esposte dal nodo move_group.

Non usa moveit_py: franka_fr3_moveit_config costruisce la propria
configurazione MoveIt "a mano" (yaml sparsi passati al nodo move_group),
non tramite MoveItConfigsBuilder, quindi caricare moveit_py in-process
richiederebbe duplicare quella configurazione in un altro formato. Qui
invece si parla con il move_group già avviato da entrypoint.sh, esattamente
come fa MoveGroupInterface in C++ (stesse action/service ROS 2 standard).

IMPORTANTE: questo modulo è SOLO un pianificatore. Ogni goal viene inviato
con planning_options.plan_only = True: move_group calcola la traiettoria
(IK + collision checking + OMPL) e la restituisce, ma non la esegue mai —
non invia comandi né al robot reale né al fake hardware. L'attuazione resta
interamente a carico del servizio 'cobot' (pylibfranka).
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from rclpy.action import ActionClient
from rclpy.node import Node

from geometry_msgs.msg import Point, Pose, PoseStamped, Quaternion
from moveit_msgs.action import MoveGroup
from moveit_msgs.msg import (
    BoundingVolume,
    Constraints,
    JointConstraint,
    MoveItErrorCodes,
    OrientationConstraint,
    PositionConstraint,
    RobotState,
)
from moveit_msgs.srv import GetPositionFK
from rcl_interfaces.srv import GetParameters
from sensor_msgs.msg import JointState
from shape_msgs.msg import SolidPrimitive
from std_msgs.msg import Header

from .srdf import SrdfInfo, parse_srdf

logger = logging.getLogger("moveit-api.interface")

# Costanti moveit_msgs/MoveItErrorCodes più comuni, per messaggi d'errore leggibili.
_ERROR_CODE_NAMES = {
    1: "SUCCESS",
    99999: "FAILURE",
    -1: "PLANNING_FAILED",
    -2: "INVALID_MOTION_PLAN",
    -3: "MOTION_PLAN_INVALIDATED_BY_ENVIRONMENT_CHANGE",
    -4: "CONTROL_FAILED",
    -5: "UNABLE_TO_AQUIRE_SENSOR_DATA",
    -6: "TIMED_OUT",
    -7: "PREEMPTED",
    -10: "START_STATE_IN_COLLISION",
    -11: "START_STATE_VIOLATES_PATH_CONSTRAINTS",
    -12: "GOAL_IN_COLLISION",
    -13: "GOAL_VIOLATES_PATH_CONSTRAINTS",
    -14: "GOAL_CONSTRAINTS_VIOLATED",
    -15: "INVALID_GROUP_NAME",
    -16: "INVALID_GOAL_CONSTRAINTS",
    -17: "INVALID_ROBOT_STATE",
    -18: "INVALID_LINK_NAME",
    -19: "INVALID_OBJECT_NAME",
}


def error_code_name(val: int) -> str:
    return _ERROR_CODE_NAMES.get(val, f"UNKNOWN({val})")


def euler_to_quaternion(roll: float, pitch: float, yaw: float) -> Quaternion:
    """Convenzione standard REP-103 (roll=X, pitch=Y, yaw=Z, fixed-frame ZYX)."""
    cr, sr = math.cos(roll * 0.5), math.sin(roll * 0.5)
    cp, sp = math.cos(pitch * 0.5), math.sin(pitch * 0.5)
    cy, sy = math.cos(yaw * 0.5), math.sin(yaw * 0.5)

    return Quaternion(
        x=sr * cp * cy - cr * sp * sy,
        y=cr * sp * cy + sr * cp * sy,
        z=cr * cp * sy - sr * sp * cy,
        w=cr * cp * cy + sr * sp * sy,
    )


class PlanningBusyError(RuntimeError):
    pass


class MoveItNotReadyError(RuntimeError):
    pass


@dataclass
class TrajectoryPoint:
    positions: list[float]
    velocities: list[float]
    accelerations: list[float]
    time_from_start: float


@dataclass
class PlanResult:
    success: bool
    error_code: int
    error_name: str
    planning_time: Optional[float] = None
    joint_names: list[str] = field(default_factory=list)
    points: list[TrajectoryPoint] = field(default_factory=list)


class MoveItInterface:
    """
    Singolo punto di accesso a MoveIt per l'app Flask — SOLO pianificazione.

    - discover(): legge l'SRDF dal nodo move_group e ricava group/eef di default.
    - plan_joint / plan_named / plan_pose: sincroni, bloccano il thread Flask
      chiamante finché move_group non ha finito di pianificare (plan_only=True,
      nessuna esecuzione), serializzati con un lock non bloccante (una
      pianificazione alla volta). Il risultato include la traiettoria calcolata.
    """

    def __init__(
        self,
        node: Node,
        namespace: str = "",
        default_group_override: Optional[str] = None,
        default_eef_link_override: Optional[str] = None,
        service_timeout_sec: float = 5.0,
    ) -> None:
        self._node = node
        self._ns = namespace.rstrip("/")
        self._default_group_override = default_group_override
        self._default_eef_link_override = default_eef_link_override
        self._service_timeout_sec = service_timeout_sec

        self._srdf: Optional[SrdfInfo] = None
        self._discovery_error: Optional[str] = None
        self._discovery_lock = threading.Lock()

        self._planning_lock = threading.Lock()
        self._current_goal_handle = None
        self._current_operation: Optional[str] = None

        self._joint_state_lock = threading.Lock()
        self._latest_joint_state: Optional[JointState] = None

        self._move_action_client = ActionClient(
            node, MoveGroup, f"{self._ns}/move_action"
        )
        self._fk_client = node.create_client(
            GetPositionFK, f"{self._ns}/compute_fk"
        )
        self._get_params_client = node.create_client(
            GetParameters, f"{self._ns}/move_group/get_parameters"
        )

        node.create_subscription(
            JointState, f"{self._ns}/joint_states", self._on_joint_state, 10
        )

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    @property
    def is_ready(self) -> bool:
        return self._srdf is not None

    @property
    def discovery_error(self) -> Optional[str]:
        return self._discovery_error

    def start_discovery_loop(self, retry_period_sec: float = 3.0) -> None:
        def _loop():
            while True:
                if self.discover():
                    return
                time.sleep(retry_period_sec)

        threading.Thread(target=_loop, name="moveit-discovery", daemon=True).start()

    def discover(self) -> bool:
        with self._discovery_lock:
            if self._srdf is not None:
                return True
            try:
                xml_text = self._fetch_srdf_param()
                self._srdf = parse_srdf(xml_text)
                self._discovery_error = None
                logger.info(
                    "SRDF scoperto: groups=%s default_group=%s default_eef_link=%s",
                    list(self._srdf.groups.keys()),
                    self._srdf.default_group(),
                    self._srdf.default_eef_link(self._srdf.default_group()),
                )
                return True
            except Exception as exc:  # noqa: BLE001
                self._discovery_error = str(exc)
                logger.warning("Discovery SRDF fallita, riprovo: %s", exc)
                return False

    def _fetch_srdf_param(self) -> str:
        if not self._get_params_client.wait_for_service(timeout_sec=self._service_timeout_sec):
            raise MoveItNotReadyError(
                f"servizio {self._ns}/move_group/get_parameters non disponibile"
            )

        request = GetParameters.Request(names=["robot_description_semantic"])
        response = self._call_service_sync(self._get_params_client, request)

        if not response.values:
            raise MoveItNotReadyError("parametro robot_description_semantic vuoto")

        value = response.values[0]
        # PARAMETER_STRING = 4, ma leggiamo direttamente il campo per non
        # dipendere da un import aggiuntivo di rcl_interfaces.msg.ParameterType.
        if not value.string_value:
            raise MoveItNotReadyError(
                "robot_description_semantic non è una stringa non vuota"
            )
        return value.string_value

    # ------------------------------------------------------------------
    # Introspection helpers usati dalle route
    # ------------------------------------------------------------------

    def groups_info(self) -> dict[str, Any]:
        if self._srdf is None:
            raise MoveItNotReadyError("SRDF non ancora disponibile")
        srdf = self._srdf
        return {
            "groups": {
                name: {
                    "joint_names": g.joint_names,
                    "base_link": g.base_link,
                    "tip_link": g.tip_link,
                }
                for name, g in srdf.groups.items()
            },
            "group_states": srdf.group_states,
            "end_effectors": [
                {
                    "name": ee.name,
                    "parent_link": ee.parent_link,
                    "parent_group": ee.parent_group,
                    "group": ee.group,
                }
                for ee in srdf.end_effectors
            ],
            "default_group": self.default_group(),
            "default_eef_link": self.default_eef_link(),
        }

    def default_group(self) -> Optional[str]:
        if self._default_group_override:
            return self._default_group_override
        if self._srdf is None:
            return None
        return self._srdf.default_group()

    def default_eef_link(self, group_name: Optional[str] = None) -> Optional[str]:
        if self._default_eef_link_override:
            return self._default_eef_link_override
        if self._srdf is None:
            return None
        return self._srdf.default_eef_link(group_name or self.default_group())

    @property
    def is_busy(self) -> bool:
        return self._planning_lock.locked()

    def status_dict(self) -> dict[str, Any]:
        return {
            "ready": self.is_ready,
            "busy": self.is_busy,
            "current_operation": self._current_operation,
            "discovery_error": self._discovery_error,
            "mode": "planner_only",
        }

    def latest_joint_state(self) -> Optional[dict[str, Any]]:
        with self._joint_state_lock:
            js = self._latest_joint_state
        if js is None:
            return None
        return {
            "name": list(js.name),
            "position": list(js.position),
            "velocity": list(js.velocity),
        }

    def _on_joint_state(self, msg: JointState) -> None:
        with self._joint_state_lock:
            self._latest_joint_state = msg

    # ------------------------------------------------------------------
    # Planning primitives
    # ------------------------------------------------------------------

    def plan_joint(
        self,
        joint_positions: dict[str, float],
        group: Optional[str] = None,
        speed_factor: float = 0.2,
        tolerance: float = 0.001,
        planning_time: float = 5.0,
        start_joint_positions: Optional[dict[str, float]] = None,
    ) -> PlanResult:
        group = group or self.default_group()
        if not group:
            raise MoveItNotReadyError("nessun planning group disponibile/configurato")

        constraints = Constraints()
        for joint_name, position in joint_positions.items():
            constraints.joint_constraints.append(
                JointConstraint(
                    joint_name=joint_name,
                    position=float(position),
                    tolerance_above=tolerance,
                    tolerance_below=tolerance,
                    weight=1.0,
                )
            )

        return self._plan(
            group=group,
            goal_constraints=[constraints],
            speed_factor=speed_factor,
            planning_time=planning_time,
            operation_name="plan_joint",
            start_joint_positions=start_joint_positions,
        )

    def plan_named(
        self,
        state_name: str,
        group: Optional[str] = None,
        speed_factor: float = 0.2,
        planning_time: float = 5.0,
        start_joint_positions: Optional[dict[str, float]] = None,
    ) -> PlanResult:
        group = group or self.default_group()
        if not group:
            raise MoveItNotReadyError("nessun planning group disponibile/configurato")
        if self._srdf is None:
            raise MoveItNotReadyError("SRDF non ancora disponibile")

        states_for_group = self._srdf.group_states.get(group, {})
        joint_positions = states_for_group.get(state_name)
        if joint_positions is None:
            known = sorted(states_for_group.keys())
            raise ValueError(
                f"stato '{state_name}' non trovato per il gruppo '{group}'. "
                f"Stati noti: {known}"
            )

        return self.plan_joint(
            joint_positions,
            group=group,
            speed_factor=speed_factor,
            planning_time=planning_time,
            start_joint_positions=start_joint_positions,
        )

    def plan_pose(
        self,
        position: dict[str, float],
        orientation: Optional[dict[str, float]] = None,
        rpy: Optional[list[float]] = None,
        group: Optional[str] = None,
        link_name: Optional[str] = None,
        frame_id: Optional[str] = None,
        speed_factor: float = 0.2,
        tolerance_position: float = 0.01,
        tolerance_orientation: float = 0.02,
        planning_time: float = 5.0,
        start_joint_positions: Optional[dict[str, float]] = None,
    ) -> PlanResult:
        group = group or self.default_group()
        if not group:
            raise MoveItNotReadyError("nessun planning group disponibile/configurato")

        link_name = link_name or self.default_eef_link(group)
        if not link_name:
            raise ValueError(
                "impossibile determinare il link end-effector: nessun <end_effector> "
                "trovato nell'SRDF. Specificare esplicitamente 'link_name' nella richiesta "
                "oppure impostare MOVEIT_EEF_LINK."
            )

        if orientation is not None:
            quat = Quaternion(
                x=float(orientation["x"]),
                y=float(orientation["y"]),
                z=float(orientation["z"]),
                w=float(orientation["w"]),
            )
        elif rpy is not None:
            quat = euler_to_quaternion(float(rpy[0]), float(rpy[1]), float(rpy[2]))
        else:
            raise ValueError("specificare 'orientation' (quaternione) oppure 'rpy'")

        planning_frame = frame_id or (self._srdf.groups[group].base_link if self._srdf and group in self._srdf.groups else None) or "world"

        pose = Pose(
            position=Point(x=float(position["x"]), y=float(position["y"]), z=float(position["z"])),
            orientation=quat,
        )
        header = Header(frame_id=planning_frame)

        constraints = Constraints()

        position_constraint = PositionConstraint(
            header=header,
            link_name=link_name,
            weight=1.0,
        )
        position_constraint.constraint_region = BoundingVolume(
            primitives=[SolidPrimitive(type=SolidPrimitive.SPHERE, dimensions=[tolerance_position])],
            primitive_poses=[pose],
        )
        constraints.position_constraints.append(position_constraint)

        orientation_constraint = OrientationConstraint(
            header=header,
            link_name=link_name,
            orientation=quat,
            absolute_x_axis_tolerance=tolerance_orientation,
            absolute_y_axis_tolerance=tolerance_orientation,
            absolute_z_axis_tolerance=tolerance_orientation,
            weight=1.0,
        )
        constraints.orientation_constraints.append(orientation_constraint)

        return self._plan(
            group=group,
            goal_constraints=[constraints],
            speed_factor=speed_factor,
            planning_time=planning_time,
            operation_name="plan_pose",
            start_joint_positions=start_joint_positions,
        )

    def cancel(self) -> bool:
        """Annulla una pianificazione in corso (non c'è nessuna esecuzione da fermare)."""
        goal_handle = self._current_goal_handle
        if goal_handle is None:
            return False
        cancel_future = goal_handle.cancel_goal_async()
        done_event = threading.Event()
        cancel_future.add_done_callback(lambda _f: done_event.set())
        done_event.wait(self._service_timeout_sec)
        return True

    def get_fk_pose(self, link_name: Optional[str] = None) -> dict[str, Any]:
        group = self.default_group()
        link_name = link_name or self.default_eef_link(group)
        if not link_name:
            raise ValueError("link_name non specificato e nessun default disponibile")

        joint_state = self.latest_joint_state()
        if joint_state is None:
            raise MoveItNotReadyError("nessun /joint_states ricevuto ancora")

        if not self._fk_client.wait_for_service(timeout_sec=self._service_timeout_sec):
            raise MoveItNotReadyError(f"servizio {self._ns}/compute_fk non disponibile")

        request = GetPositionFK.Request()
        request.header = Header(frame_id="")
        request.fk_link_names = [link_name]
        request.robot_state = RobotState(
            joint_state=JointState(
                name=joint_state["name"],
                position=joint_state["position"],
            ),
            is_diff=False,
        )

        response = self._call_service_sync(self._fk_client, request)
        if not response.pose_stamped:
            raise RuntimeError(
                f"compute_fk fallito: {error_code_name(response.error_code.val)}"
            )

        pose_stamped: PoseStamped = response.pose_stamped[0]
        return {
            "link_name": link_name,
            "frame_id": pose_stamped.header.frame_id,
            "position": {
                "x": pose_stamped.pose.position.x,
                "y": pose_stamped.pose.position.y,
                "z": pose_stamped.pose.position.z,
            },
            "orientation": {
                "x": pose_stamped.pose.orientation.x,
                "y": pose_stamped.pose.orientation.y,
                "z": pose_stamped.pose.orientation.z,
                "w": pose_stamped.pose.orientation.w,
            },
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _plan(
        self,
        group: str,
        goal_constraints: list[Constraints],
        speed_factor: float,
        planning_time: float,
        operation_name: str,
        start_joint_positions: Optional[dict[str, float]] = None,
    ) -> PlanResult:
        if not self._planning_lock.acquire(blocking=False):
            raise PlanningBusyError("un'altra richiesta di pianificazione è già in corso")

        try:
            if not self._move_action_client.wait_for_server(timeout_sec=self._service_timeout_sec):
                raise MoveItNotReadyError(f"action {self._ns}/move_action non disponibile")

            goal = MoveGroup.Goal()
            goal.request.group_name = group
            goal.request.goal_constraints = goal_constraints
            if start_joint_positions:
                goal.request.start_state = RobotState(
                    joint_state=JointState(
                        name=list(start_joint_positions.keys()),
                        position=[float(v) for v in start_joint_positions.values()],
                    ),
                    is_diff=False,
                )
            else:
                # Nessuno stato iniziale esplicito: usa lo stato corrente noto
                # a move_group (dal suo planning scene monitor, non dal robot
                # reale se questo processo gira con USE_FAKE_HARDWARE=true).
                goal.request.start_state.is_diff = True
            goal.request.num_planning_attempts = 5
            goal.request.allowed_planning_time = float(planning_time)
            goal.request.max_velocity_scaling_factor = float(speed_factor)
            goal.request.max_acceleration_scaling_factor = float(speed_factor)
            # Solo pianificazione: mai eseguita su hardware reale o fake.
            goal.planning_options.plan_only = True

            self._current_operation = operation_name
            result, goal_handle = self._send_goal_sync(goal)
            self._current_goal_handle = goal_handle

            error_val = result.error_code.val
            joint_trajectory = result.planned_trajectory.joint_trajectory
            points = [
                TrajectoryPoint(
                    positions=list(p.positions),
                    velocities=list(p.velocities),
                    accelerations=list(p.accelerations),
                    time_from_start=p.time_from_start.sec + p.time_from_start.nanosec * 1e-9,
                )
                for p in joint_trajectory.points
            ]

            return PlanResult(
                success=(error_val == MoveItErrorCodes.SUCCESS),
                error_code=error_val,
                error_name=error_code_name(error_val),
                planning_time=getattr(result, "planning_time", None),
                joint_names=list(joint_trajectory.joint_names),
                points=points,
            )
        finally:
            self._current_goal_handle = None
            self._current_operation = None
            self._planning_lock.release()

    def _send_goal_sync(self, goal_msg: MoveGroup.Goal, timeout_sec: float = 120.0):
        send_future = self._move_action_client.send_goal_async(goal_msg)
        sent_event = threading.Event()
        box: dict[str, Any] = {}

        def _on_sent(fut):
            box["goal_handle"] = fut.result()
            sent_event.set()

        send_future.add_done_callback(_on_sent)
        if not sent_event.wait(timeout_sec):
            raise TimeoutError("timeout nell'invio del goal a move_group")

        goal_handle = box["goal_handle"]
        if not goal_handle.accepted:
            raise RuntimeError("goal rifiutato da move_group")

        result_future = goal_handle.get_result_async()
        result_event = threading.Event()

        def _on_result(fut):
            box["result"] = fut.result().result
            result_event.set()

        result_future.add_done_callback(_on_result)
        if not result_event.wait(timeout_sec):
            raise TimeoutError("timeout in attesa del risultato da move_group")

        return box["result"], goal_handle

    def _call_service_sync(self, client, request, timeout_sec: Optional[float] = None):
        timeout_sec = timeout_sec or self._service_timeout_sec
        future = client.call_async(request)
        done_event = threading.Event()
        future.add_done_callback(lambda _f: done_event.set())
        if not done_event.wait(timeout_sec):
            raise TimeoutError(f"timeout chiamando il servizio {client.srv_name}")
        exc = future.exception()
        if exc is not None:
            raise exc
        return future.result()
