import os
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
os.environ["SIM_SPEED"] = "0"
os.environ["SIM_PUBLISH_HZ"] = "0"
sys.path.insert(0, str(ROOT / "cobot_sim" / "shim"))
sys.path.insert(0, str(ROOT / "cobot" / "src"))

import pylibfranka  # noqa: E402
from franka_controller.kinematics import FR3_Q_MAX  # noqa: E402


@pytest.fixture()
def robot():
    robot = pylibfranka.Robot("sim")
    robot._core.recover()
    robot._core.q = np.array(pylibfranka._sim.HOME_Q)
    return robot


def run_joint_move(robot, target, steps=500):
    control = robot.start_joint_position_control(pylibfranka.ControllerMode.JointImpedance)
    q0 = np.array(robot.read_once().q)
    for i in range(1, steps + 1):
        control.readOnce()
        cmd = pylibfranka.JointPositions((q0 + (target - q0) * i / steps).tolist())
        cmd.motion_finished = i == steps
        control.writeOnce(cmd)


def test_joint_position_control_reaches_target(robot):
    target = np.array(pylibfranka._sim.HOME_Q) + 0.1
    run_joint_move(robot, target)
    assert np.allclose(robot.read_once().q, target, atol=1e-9)


def test_velocity_limit_violation_raises_and_recovers(robot):
    control = robot.start_joint_position_control()
    control.readOnce()
    with pytest.raises(pylibfranka.ControlException):
        control.writeOnce(pylibfranka.JointPositions((np.array(robot.read_once().q) + 0.5).tolist()))
    with pytest.raises(pylibfranka.ControlException):
        robot.start_joint_position_control()
    robot.automatic_error_recovery()
    robot.start_joint_position_control()


def test_cartesian_pose_control_tracks_target(robot):
    state = robot.read_once()
    pose = np.array(state.O_T_EE).reshape((4, 4), order="F")
    target = pose.copy()
    target[2, 3] -= 0.05
    control = robot.start_cartesian_pose_control()
    for i in range(1, 801):
        control.readOnce()
        step = pose.copy()
        step[2, 3] = pose[2, 3] + (target[2, 3] - pose[2, 3]) * i / 800
        cmd = pylibfranka.CartesianPose(step.reshape(-1, order="F").tolist())
        cmd.motion_finished = i == 800
        control.writeOnce(cmd)
    final = np.array(robot.read_once().O_T_EE).reshape((4, 4), order="F")
    assert np.allclose(final[:3, 3], target[:3, 3], atol=1e-3)


def test_gripper_grasp_and_homing():
    gripper = pylibfranka.Gripper("sim")
    assert gripper.homing()
    assert gripper.grasp(0.03, 0.1, 20.0)
    state = gripper.read_once()
    assert state.is_grasped and state.width == pytest.approx(0.03)
    assert gripper.move(0.08, 0.1)
    assert not gripper.read_once().is_grasped


def test_joint_limits_are_enforced(robot):
    control = robot.start_joint_position_control()
    control.readOnce()
    target = np.array(robot.read_once().q)
    target[0] = FR3_Q_MAX[0] + 0.01
    with pytest.raises(pylibfranka.ControlException):
        control.writeOnce(pylibfranka.JointPositions(target.tolist()))
    robot.automatic_error_recovery()
