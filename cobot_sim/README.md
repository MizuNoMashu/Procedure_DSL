# cobot_sim — simulated Franka FR3 on ROS 2

Lets the UI and the `cobot` API run without a physical robot. Instead of talking to
libfranka, the cobot code talks to a drop-in `pylibfranka` replacement
(`shim/pylibfranka`) that simulates the arm and the Franka Hand. Nothing in
`cobot/` or `ui_dsl/` is mocked: sessions, queue, trajectory pre-checks, force
control and emergency stop are the real code.

```
browser ─ ui_dsl ─ /cobot-proxy ─▶ cobot API (python, :5001) ─ pylibfranka sim
                                         │                         │ UDP 30 Hz
                          fake Desk API (:8080, internal)          ▼
                                                            ros_bridge ─▶ /joint_states
                                          robot_state_publisher ◀─┘      /cobot_sim/ee_pose
                                          3D viewer (:8090, local page) ◀── same process as ros_bridge
```

## Run

```bash
COBOT_SERVICE_URL=http://cobot-sim:5001 SIM_SERVICE_URL=http://cobot-sim:8080 docker compose --profile sim up ui cobot-sim --build
```

Do not run it together with the `cobot` service: both use port 5001.

1. UI → Cobot page → *Connect Desk* → *Prepare and connect* (any IP/credentials; the Desk API is simulated via `FRANKA_DESK_URL`).
2. Send motions from the UI, the Trajectory Builder or the DSL page. The first command opens a session; if someone else holds the robot you are queued and the badge bottom-right shows your position.
3. Watch the robot: http://localhost:8090 (3D viewer served by the container itself, no account, no cloud; the JS libraries are downloaded at image build time). API docs: http://localhost:5001/api/docs/, queue debugger: http://localhost:5001/debug.

ROS topics (domain `SIM_ROS_DOMAIN_ID`, default 20): `/joint_states`, `/cobot_sim/ee_pose`, `/cobot_sim/status`, `/tf` (usable from RViz or any ROS 2 tool in the same domain).

## What is simulated

| Area | Behaviour |
| --- | --- |
| Joint / velocity control | ideal tracking; joint limits and 1.05× velocity limit raise `ControlException` (robot → `ERROR_LOCKED`, `POST /api/robot/recovery` clears it) |
| Cartesian control | near-undamped IK with null space towards home; singularities trigger a velocity reflex |
| Torque control (impedance, force tasks) | diagonal inertia + viscous friction, gravity compensated |
| Contact | optional horizontal plane so `apply` / `insert` / `screw` find a surface: set it from the UI (Cobot page → *Simulator · contact surface*, e.g. "Place under TCP");  collision thresholds from `set_collision_behavior` are honoured |
| Gripper | homing, move, grasp (assumes an object of the requested width), stop |
| Desk API | token, operating mode, joint brakes, FCI, safety recovery |

Not simulated: link/environment collisions, real dynamics, real-time jitter. Treat results as functional checks, not as validation of gains on the real robot.

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `SIM_SPEED` | `1` | simulated time / wall time; `0` = as fast as possible |
| `SIM_CONTACT_Z` | empty | initial height of the contact plane (the UI panel overrides it at runtime), empty = no contact |
| `SIM_ROS_DOMAIN_ID` | `20` | ROS domain (keep it different from `moveit`, 10) |
| `COBOT_SESSION_IDLE_TIMEOUT` | `60` | seconds before an idle session loses its turn |

## MoveIt

`moveit` runs its own ROS fake hardware, so by default it believes the arm is at *its* home. Set `ROBOT_STATE_URL=http://cobot-sim:8090/state` and MoveIt plans from the simulated arm instead (start state, `/moveit/state`, `/moveit/pose`). Run both together:

```bash
COBOT_SERVICE_URL=http://cobot-sim:5001 SIM_SERVICE_URL=http://cobot-sim:8080 ROBOT_STATE_URL=http://cobot-sim:8090/state \
  docker compose --profile sim up ui cobot-sim moveit --build
```

MoveIt is planner-only: it never moves anything, the cobot API executes (here: the simulator).

## Singularities

* **Joint-space moves** (`move_joints`, trajectories) pass through any configuration, as on the real robot. The cobot's own trajectory pre-check (`σ_min(J)` along the path) is what rejects dangerous ones — it runs unchanged in the sim.
* **Cartesian moves** use an almost undamped IK: near a singularity (arm fully stretched, wrist aligned) the required joint velocity explodes and the sim raises the same `joint_velocity_limits_violation` reflex as the robot (`ERROR_LOCKED`, then *Recovery*). Try `move_cartesian` to x = 0.80, z = 0.45.
* The 3D viewer shows `σ_min(J)` live and turns red below 0.05. `SIM_IK_DAMPING` (default `1e-6`) tunes how aggressive this is.

## Tests

```bash
python -m pytest cobot_sim/tests   # needs numpy + pytest
```
