"""
Sostituto di `pylibfranka` per la simulazione (vedi _sim.py).

Espone le classi e i metodi che `franka_controller` usa: Robot, Gripper, Model,
i comandi (JointPositions, CartesianPose, ...) e le eccezioni.
"""

import numpy as np

from . import _sim
from ._sim import (  # noqa: F401
    CartesianPose,
    CommandException,
    ControllerMode,
    ControlException,
    Duration,
    IncompatibleVersionException,
    JointPositions,
    JointVelocities,
    NetworkException,
    RealtimeConfig,
    RobotMode,
    SimRobotState as RobotState,
    Torques,
)

__version__ = "0.0.0-sim"


class ActiveControl:
    """Sessione di controllo real-time: readOnce() poi writeOnce(comando), a 1 kHz."""

    def __init__(self, core, step):
        self._core = core
        self._step = step
        self._finished = False
        core.begin(self)

    def readOnce(self):
        core = self._core
        with core.lock:
            if self._finished:
                raise ControlException("il controllo è già terminato")
            core._check_reflex()
            if core.active is not self:
                raise ControlException("controllo interrotto da stop()")
        core.pace()
        with core.lock:
            return RobotState(core), Duration(_sim.PERIOD)

    def writeOnce(self, command):
        core = self._core
        with core.lock:
            if self._finished:
                return
            core._check_reflex()
            if core.active is not self:
                raise ControlException("controllo interrotto da stop()")
            self._step(command.values)
            if getattr(command, "motion_finished", False):
                self._finished = True
                core.end(self)

    def stop_control(self):
        self._finished = True


class Model:
    def __init__(self, core):
        self._core = core

    def coriolis(self, state):
        return [0.0] * 7

    def gravity(self, state):
        return [0.0] * 7

    def mass(self, state):
        return np.diag(_sim.INERTIA).reshape(-1, order="F").tolist()

    def zero_jacobian(self, state_or_frame, state=None):
        state = state if state is not None else state_or_frame
        _, jac = self._core.ee_pose_and_jacobian(np.asarray(state.q, dtype=float))
        return jac.reshape(-1, order="F").tolist()


class Robot:
    def __init__(self, ip="", realtime_config=RealtimeConfig.kEnforce):
        self.ip = ip
        self.realtime_config = realtime_config
        self._core = _sim.get_core()

    def read_once(self):
        with self._core.lock:
            return RobotState(self._core)

    def _start(self, step):
        return ActiveControl(self._core, step)

    def start_joint_position_control(self, mode=ControllerMode.JointImpedance):
        return self._start(self._core.step_joint_positions)

    def start_joint_velocity_control(self, mode=ControllerMode.JointImpedance):
        return self._start(self._core.step_joint_velocities)

    def start_cartesian_pose_control(self, mode=ControllerMode.JointImpedance):
        return self._start(self._core.step_cartesian_pose)

    def start_torque_control(self):
        return self._start(self._core.step_torques)

    def stop(self):
        self._core.end()

    def load_model(self):
        return Model(self._core)

    def set_collision_behavior(
        self, lower_torque_thresholds, upper_torque_thresholds,
        lower_force_thresholds, upper_force_thresholds,
    ):
        self._core.set_collision_behavior(
            lower_torque_thresholds, upper_torque_thresholds,
            lower_force_thresholds, upper_force_thresholds,
        )

    def set_joint_impedance(self, stiffness):
        if len(stiffness) != 7:
            raise CommandException("set_joint_impedance: servono 7 valori")

    def set_cartesian_impedance(self, stiffness):
        if len(stiffness) != 6:
            raise CommandException("set_cartesian_impedance: servono 6 valori")

    def set_EE(self, transform):
        values = np.asarray(transform, dtype=float)
        if values.size != 16:
            raise CommandException("set_EE: servono 16 valori (column-major)")
        self._core.ne_t_ee = values.reshape((4, 4), order="F")

    def automatic_error_recovery(self):
        self._core.recover()

    def server_version(self):
        return 9


class GripperState:
    def __init__(self, width, max_width, is_grasped, temperature):
        self.width = width
        self.max_width = max_width
        self.is_grasped = is_grasped
        self.temperature = temperature
        self.time = 0


class Gripper:
    def __init__(self, ip=""):
        self.ip = ip
        self._core = _sim.get_core()

    def _move_to(self, target, speed):
        core = self._core
        if speed <= 0:
            raise CommandException("speed deve essere > 0")
        if not 0.0 <= target <= _sim.GRIPPER_MAX_WIDTH + 1e-9:
            raise CommandException(f"width fuori range: {target}")
        core.gripper_stop.clear()
        step = 0.01
        scale = core.speed if core.speed > 0 else None
        while True:
            with core.lock:
                delta = target - core.gripper_width
                if abs(delta) < 1e-6:
                    core.gripper_width = target
                    return True
                if core.gripper_stop.is_set():
                    return False
                advance = speed * step * (scale or 1e6)
                core.gripper_width += max(-advance, min(advance, delta))
            if scale:
                _sim._time.sleep(step / scale)

    def homing(self):
        self._core.gripper_grasped = False
        return self._move_to(_sim.GRIPPER_MAX_WIDTH, 0.05)

    def move(self, width, speed):
        self._core.gripper_grasped = False
        return self._move_to(float(width), float(speed))

    def grasp(self, width, speed, force, epsilon_inner=0.005, epsilon_outer=0.005):
        if force <= 0:
            raise CommandException("force deve essere > 0")
        ok = self._move_to(float(width), float(speed))
        self._core.gripper_grasped = bool(ok)
        return ok

    def stop(self):
        self._core.gripper_stop.set()
        return True

    def read_once(self):
        core = self._core
        with core.lock:
            return GripperState(core.gripper_width, _sim.GRIPPER_MAX_WIDTH, core.gripper_grasped, 30.0)

    def server_version(self):
        return 3


# il robot simulato esiste (e viene pubblicato) fin dall'avvio del server, anche prima della connessione
_sim.get_core()
