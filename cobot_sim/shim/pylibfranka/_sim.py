"""
Simulatore di un robot Franka FR3 (+ Franka Hand) con la stessa interfaccia di pylibfranka.

Non è un motore fisico completo: serve a far girare lo stack `cobot` (sessioni,
coda, validazione traiettorie, controllo di forza, gripper) senza hardware.

  * controllo in posizione/velocità: il robot insegue il comando in modo ideale;
  * controllo cartesiano: cinematica inversa DLS con spazio nullo verso la home;
  * controllo in coppia: dinamica a inerzia diagonale + attrito viscoso
    (gravità compensata, come fa il Franka reale);
  * contatto opzionale con un piano orizzontale (SIM_CONTACT_Z) per provare
    apply/insert/screw;
  * ogni ciclo di controllo dura 1 ms simulato; SIM_SPEED (default 1) lo lega al
    tempo reale (0 = il più veloce possibile).

Lo stato viene inviato via UDP al bridge ROS 2 (ros_bridge.py) che lo pubblica su /joint_states.
"""

import json
import math
import os
import time as _std_time

import numpy as np

try:  # con eventlet monkey-patched i loop di controllo devono dormire "per davvero"
    from eventlet.patcher import original as _original

    _threading = _original("threading")
    _time = _original("time")
    _socket = _original("socket")
except ImportError:
    import socket as _socket
    import threading as _threading

    _time = _std_time



def _kin():
    # import tardivo: franka_controller importa pylibfranka, evita il ciclo all'import
    from franka_controller import kinematics

    return kinematics


PERIOD = 0.001
HOME_Q = np.array(
    [0.059821926, -0.774301946, -0.023823734, -2.373579979, -0.037449367, 1.568207741, 0.832140386]
)
# Franka Hand: rotazione di -45° attorno a z e TCP a 103.4 mm dalla flangia
_C = math.cos(math.pi / 4)
DEFAULT_NE_T_EE = np.array(
    [[_C, -_C, 0.0, 0.0], [_C, _C, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.1034, 1.0]]
).T.copy()  # le righe elencate sono le colonne (column-major, come libfranka)
INERTIA = np.array([2.0, 2.0, 1.5, 1.5, 0.6, 0.5, 0.2])
DAMPING = np.array([2.0, 2.0, 1.5, 1.5, 0.8, 0.6, 0.3])
GRIPPER_MAX_WIDTH = 0.08


class ControlException(Exception):
    pass


class CommandException(Exception):
    pass


class NetworkException(Exception):
    pass


class IncompatibleVersionException(Exception):
    pass


def _env_float(name, default):
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return float(value)


class Duration:
    def __init__(self, seconds):
        self._s = float(seconds)

    def to_sec(self):
        return self._s

    def to_msec(self):
        return self._s * 1000.0


class SimRobotState:
    """Subset di pylibfranka.RobotState usato dal controller."""

    def __init__(self, core):
        q = core.q.copy()
        flange_T, _ = _kin().forward_kinematics_and_jacobian(q)
        pose = flange_T[0] @ core.ne_t_ee
        pose_c = core.last_pose_command if core.last_pose_command is not None else pose
        f_base = core.ext_wrench_base
        r_t = pose[:3, :3].T
        f_k = np.concatenate([r_t @ f_base[:3], r_t @ f_base[3:]])

        self.q = q.tolist()
        self.q_d = core.q_d.tolist()
        self.dq = core.dq.tolist()
        self.dq_d = core.dq.tolist()
        self.tau_J = core.tau_cmd.tolist()
        self.tau_J_d = core.tau_cmd.tolist()
        self.tau_ext_hat_filtered = core.tau_ext.tolist()
        self.O_T_EE = pose.reshape(-1, order="F").tolist()
        self.O_T_EE_d = pose_c.reshape(-1, order="F").tolist()
        self.O_T_EE_c = pose_c.reshape(-1, order="F").tolist()
        self.F_T_EE = core.ne_t_ee.reshape(-1, order="F").tolist()
        self.O_dP_EE_d = [0.0] * 6
        self.O_F_ext_hat_K = f_base.tolist()
        self.K_F_ext_hat_K = f_k.tolist()
        self.joint_contact = core.joint_contact.astype(float).tolist()
        self.joint_collision = core.joint_collision.astype(float).tolist()
        self.cartesian_contact = core.cartesian_contact.astype(float).tolist()
        self.cartesian_collision = core.cartesian_collision.astype(float).tolist()
        self.control_command_success_rate = 1.0
        self.robot_mode = core.robot_mode
        self.time = Duration(core.sim_time)


class _Command:
    motion_finished = False

    def __init__(self, values):
        self.values = list(values)
        self.motion_finished = False


class JointPositions(_Command):
    pass


class JointVelocities(_Command):
    pass


class CartesianPose(_Command):
    pass


class Torques(_Command):
    pass


class ControllerMode:
    JointImpedance = "JointImpedance"
    CartesianImpedance = "CartesianImpedance"


class RealtimeConfig:
    kEnforce = "kEnforce"
    kIgnore = "kIgnore"


class RobotMode:
    kOther = "Other"
    kIdle = "Idle"
    kMove = "Move"
    kGuiding = "Guiding"
    kReflex = "Reflex"
    kUserStopped = "UserStopped"
    kAutomaticErrorRecovery = "AutomaticErrorRecovery"


def _skew(v):
    return np.array([[0.0, -v[2], v[1]], [v[2], 0.0, -v[0]], [-v[1], v[0], 0.0]])


def _rotation_error(r_target, r_current):
    r_err = r_target @ r_current.T
    cos_angle = max(-1.0, min(1.0, (np.trace(r_err) - 1.0) / 2.0))
    angle = math.acos(cos_angle)
    if angle < 1e-9:
        return np.zeros(3)
    axis = np.array(
        [r_err[2, 1] - r_err[1, 2], r_err[0, 2] - r_err[2, 0], r_err[1, 0] - r_err[0, 1]]
    )
    norm = np.linalg.norm(axis)
    if norm < 1e-9:
        return np.zeros(3)
    return angle * axis / norm


class SimCore:
    """Stato condiviso del robot simulato (un solo robot per processo)."""

    def __init__(self):
        self.lock = _threading.RLock()
        self.speed = _env_float("SIM_SPEED", 1.0)
        self.config_file = os.getenv("SIM_CONFIG_FILE", "/tmp/cobot_sim_config.json")
        self._config_mtime = None
        self.contact_z = os.getenv("SIM_CONTACT_Z")
        self.contact_z = float(self.contact_z) if self.contact_z not in (None, "") else None
        self.ik_damping = _env_float("SIM_IK_DAMPING", 1e-6)
        self.contact_k = _env_float("SIM_CONTACT_STIFFNESS", 3000.0)
        self.contact_d = _env_float("SIM_CONTACT_DAMPING", 60.0)

        self.q = HOME_Q.copy()
        self.dq = np.zeros(7)
        self.q_d = HOME_Q.copy()
        self.tau_cmd = np.zeros(7)
        self.tau_ext = np.zeros(7)
        self.ne_t_ee = DEFAULT_NE_T_EE.copy()
        self.last_pose_command = None
        self.ext_wrench_base = np.zeros(6)
        self.sim_time = 0.0

        self.lower_torque = np.full(7, 20.0)
        self.upper_torque = np.full(7, 20.0)
        self.lower_force = np.array([20.0, 20.0, 20.0, 25.0, 25.0, 25.0])
        self.upper_force = np.array([20.0, 20.0, 20.0, 25.0, 25.0, 25.0])
        self.joint_contact = np.zeros(7, dtype=bool)
        self.joint_collision = np.zeros(7, dtype=bool)
        self.cartesian_contact = np.zeros(6, dtype=bool)
        self.cartesian_collision = np.zeros(6, dtype=bool)

        self.robot_mode = RobotMode.kIdle
        self.reflex = None
        self.active = None
        self._next_tick = _time.monotonic()
        self._prev_ee_z = None

        self.gripper_width = GRIPPER_MAX_WIDTH
        self.gripper_grasped = False
        self.gripper_stop = _threading.Event()

        self._publisher = _StatePublisher(self)
        self._publisher.start()

    def refresh_config(self):
        """Legge il piano di contatto scritto da fake_desk (/sim/contact), modificabile dalla UI."""
        try:
            mtime = os.stat(self.config_file).st_mtime
        except OSError:
            return
        if mtime == self._config_mtime:
            return
        self._config_mtime = mtime
        try:
            with open(self.config_file) as handle:
                value = json.load(handle).get("contact_z")
            self.contact_z = None if value is None else float(value)
        except (OSError, ValueError, TypeError):
            pass

    # ------------------------------------------------------------------
    # Cinematica
    # ------------------------------------------------------------------

    def ee_pose_and_jacobian(self, q):
        flange_T, jac = _kin().forward_kinematics_and_jacobian(q)
        pose = flange_T[0] @ self.ne_t_ee
        jac = jac[0].copy()
        r = pose[:3, 3] - flange_T[0][:3, 3]
        jac[:3, :] = jac[:3, :] - _skew(r) @ jac[3:, :]
        return pose, jac

    # ------------------------------------------------------------------
    # Temporizzazione e controllo attivo
    # ------------------------------------------------------------------

    def pace(self):
        if self.speed <= 0:
            return
        self._next_tick += PERIOD / self.speed
        delay = self._next_tick - _time.monotonic()
        if delay > 0:
            _time.sleep(delay)
        elif delay < -0.1:
            self._next_tick = _time.monotonic()

    def begin(self, control):
        with self.lock:
            self._check_reflex()
            if self.active is not None:
                raise ControlException("un altro controllo è già attivo (chiamare stop())")
            self.active = control
            self.robot_mode = RobotMode.kMove
            self._next_tick = _time.monotonic()
            self.last_pose_command = None
            self.q_d = self.q.copy()
            self.tau_cmd = np.zeros(7)

    def end(self, control=None):
        with self.lock:
            if control is None or self.active is control:
                self.active = None
                self.dq = np.zeros(7)
                if self.reflex is None:
                    self.robot_mode = RobotMode.kIdle

    def _check_reflex(self):
        if self.reflex is not None:
            raise ControlException(self.reflex)

    def trigger_reflex(self, message):
        self.reflex = message
        self.robot_mode = RobotMode.kReflex
        self.active = None
        self.dq = np.zeros(7)
        raise ControlException(message)

    def recover(self):
        with self.lock:
            self.reflex = None
            self.active = None
            self.dq = np.zeros(7)
            self.tau_cmd = np.zeros(7)
            self.cartesian_collision[:] = False
            self.joint_collision[:] = False
            self.robot_mode = RobotMode.kIdle

    # ------------------------------------------------------------------
    # Contatto e soglie di collisione
    # ------------------------------------------------------------------

    def update_contacts(self, dt):
        pose, jac = self.ee_pose_and_jacobian(self.q)
        wrench = np.zeros(6)
        if self.contact_z is not None:
            z = pose[2, 3]
            vz = 0.0 if self._prev_ee_z is None else (z - self._prev_ee_z) / dt
            self._prev_ee_z = z
            penetration = self.contact_z - z
            if penetration > 0.0:
                wrench[2] = max(0.0, self.contact_k * penetration - self.contact_d * vz)
        else:
            self._prev_ee_z = None
        self.ext_wrench_base = wrench
        self.tau_ext = jac.T @ wrench

        magnitude = np.abs(wrench)
        self.cartesian_contact = magnitude > self.lower_force
        self.cartesian_collision = magnitude > self.upper_force
        torque_mag = np.abs(self.tau_ext)
        self.joint_contact = torque_mag > self.lower_torque
        self.joint_collision = torque_mag > self.upper_torque

    def check_collision(self):
        if self.cartesian_collision.any() or self.joint_collision.any():
            self.trigger_reflex("Cartesian reflex: contact force above the collision threshold")

    # ------------------------------------------------------------------
    # Passi di simulazione
    # ------------------------------------------------------------------

    def _apply_joint_target(self, q_new, dt, label):
        if np.any(q_new < _kin().FR3_Q_MIN - 1e-6) or np.any(q_new > _kin().FR3_Q_MAX + 1e-6):
            self.trigger_reflex(f"{label}_position_limits_violation")
        dq_new = (q_new - self.q) / dt
        if np.any(np.abs(dq_new) > _kin().FR3_DQ_MAX * 1.05):
            self.trigger_reflex(f"{label}_velocity_limits_violation")
        self.q = q_new
        self.dq = dq_new
        self.q_d = q_new.copy()

    def step_joint_positions(self, q_cmd, dt=PERIOD):
        self._apply_joint_target(np.asarray(q_cmd, dtype=float), dt, "joint_motion_generator")
        self._finish_step(dt)

    def step_joint_velocities(self, dq_cmd, dt=PERIOD):
        dq_cmd = np.asarray(dq_cmd, dtype=float)
        self._apply_joint_target(self.q + dq_cmd * dt, dt, "joint_velocity_motion_generator")
        self._finish_step(dt)

    def step_cartesian_pose(self, pose_cmd, dt=PERIOD):
        target = np.asarray(pose_cmd, dtype=float).reshape((4, 4), order="F")
        self.last_pose_command = target
        q = self.q.copy()
        for _ in range(2):
            pose, jac = self.ee_pose_and_jacobian(q)
            err = np.concatenate(
                [target[:3, 3] - pose[:3, 3], _rotation_error(target[:3, :3], pose[:3, :3])]
            )
            # smorzamento minimo: vicino a una singolarità il passo di giunto esplode
            jac_pinv = jac.T @ np.linalg.inv(jac @ jac.T + self.ik_damping * np.eye(6))
            dq = jac_pinv @ err
            null = (np.eye(7) - jac_pinv @ jac) @ (HOME_Q - q) * 0.5 * dt
            q = q + dq + null
        # niente clamp: come sul robot vero, una velocità di giunto oltre il limite
        # (tipica vicino a una singolarità) fa scattare il reflex
        self._apply_joint_target(q, dt, "cartesian_motion_generator_joint")
        self._finish_step(dt)

    def step_torques(self, tau_cmd, dt=PERIOD):
        tau = np.asarray(tau_cmd, dtype=float)
        if not np.all(np.isfinite(tau)):
            self.trigger_reflex("controller_torque_discontinuity: torque non finita")
        self.tau_cmd = tau
        ddq = (tau + self.tau_ext - DAMPING * self.dq) / INERTIA
        self.dq = self.dq + ddq * dt
        q_new = self.q + self.dq * dt
        if np.any(q_new < _kin().FR3_Q_MIN) or np.any(q_new > _kin().FR3_Q_MAX):
            q_new = np.clip(q_new, _kin().FR3_Q_MIN, _kin().FR3_Q_MAX)
            self.dq = np.zeros(7)
            self.trigger_reflex("joint_position_limits_violation")
        self.q = q_new
        self.q_d = q_new.copy()
        self._finish_step(dt)

    def _finish_step(self, dt):
        self.sim_time += dt
        self.update_contacts(dt)
        self.check_collision()

    def set_collision_behavior(self, lower_torque, upper_torque, lower_force, upper_force):
        with self.lock:
            self.lower_torque = np.asarray(lower_torque, dtype=float)
            self.upper_torque = np.asarray(upper_torque, dtype=float)
            self.lower_force = np.asarray(lower_force, dtype=float)
            self.upper_force = np.asarray(upper_force, dtype=float)

    def snapshot(self):
        with self.lock:
            pose, _ = self.ee_pose_and_jacobian(self.q)
            return {
                "q": self.q.tolist(),
                "gripper_width": float(self.gripper_width),
                "ee": pose[:3, 3].tolist(),
                "ee_rot": pose[:3, :3].reshape(-1).tolist(),
                "mode": self.robot_mode,
                "grasped": bool(self.gripper_grasped),
                "external_force": self.ext_wrench_base.tolist(),
                "sigma_min": float(np.linalg.svd(self.ee_pose_and_jacobian(self.q)[1], compute_uv=False)[-1]),
                "sim_time": self.sim_time,
            }


class _StatePublisher:
    """Invia lo stato a ~30 Hz al bridge ROS 2 (UDP, best effort)."""

    def __init__(self, core):
        self.core = core
        self.addr = (
            os.getenv("SIM_BRIDGE_HOST", "127.0.0.1"),
            int(os.getenv("SIM_BRIDGE_PORT", "5599")),
        )
        self.rate = _env_float("SIM_PUBLISH_HZ", 30.0)
        self._thread = None

    def start(self):
        if self._thread is not None:
            return
        self._thread = _threading.Thread(target=self._run, name="sim-state-publisher", daemon=True)
        self._thread.start()

    def _run(self):
        sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        while True:
            self.core.refresh_config()
            if self.rate > 0:
                try:
                    sock.sendto(json.dumps(self.core.snapshot()).encode(), self.addr)
                except OSError:
                    pass
            _time.sleep(1.0 / (self.rate if self.rate > 0 else 2.0))


_CORE = None
_CORE_LOCK = _threading.Lock()


def get_core():
    global _CORE
    with _CORE_LOCK:
        if _CORE is None:
            _CORE = SimCore()
        return _CORE
