#!/usr/bin/env bash
set -Eeuo pipefail

set +u
source /opt/ros/humble/setup.bash
source /ws/install/setup.bash
set -u

export PYTHONPATH="/opt/sim/shim:/srv:/srv/src:${PYTHONPATH:-}"
export FRANKA_DESK_URL="${FRANKA_DESK_URL:-http://127.0.0.1:8080}"
export PORT="${PORT:-5001}"
export HOST="${HOST:-0.0.0.0}"

PIDS=()
shutdown() {
    for pid in "${PIDS[@]}"; do kill -TERM "$pid" 2>/dev/null || true; done
    wait 2>/dev/null || true
}
trap shutdown SIGINT SIGTERM EXIT

URDF="$(xacro "$(ros2 pkg prefix franka_description)/share/franka_description/robots/fr3/fr3.urdf.xacro" \
    hand:=true ee_id:=franka_hand)"

echo "${URDF}" > /tmp/robot.urdf

# l'URDF è troppo grande per la riga di comando: passa da un file di parametri (JSON è YAML valido)
URDF_PARAMS=/tmp/robot_state_publisher.yaml
URDF="${URDF}" python3 -c "import json, os; print(json.dumps({'robot_state_publisher': {'ros__parameters': {'robot_description': os.environ['URDF']}}}))" > "${URDF_PARAMS}"

ros2 run robot_state_publisher robot_state_publisher --ros-args --params-file "${URDF_PARAMS}" &
PIDS+=($!)

python3 /opt/sim/ros_bridge.py &
PIDS+=($!)

python3 /opt/sim/fake_desk.py &
PIDS+=($!)

python3 -m app.server &
PIDS+=($!)

wait -n "${PIDS[@]}"
echo "Un processo del simulatore si è arrestato."
exit 1
