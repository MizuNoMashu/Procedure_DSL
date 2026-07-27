#!/usr/bin/env bash
set -Eeuo pipefail

source /opt/ros/humble/setup.bash
source /franka_ros2_ws/install/setup.bash

FRANKA_ROBOT_IP="${FRANKA_ROBOT_IP:-172.16.0.3}"
USE_FAKE_HARDWARE="${USE_FAKE_HARDWARE:-true}"
LOAD_GRIPPER="${LOAD_GRIPPER:-true}"

shutdown() {
    echo "Arresto MoveIt API..."

    if [[ -n "${API_PID:-}" ]]; then
        kill -TERM "${API_PID}" 2>/dev/null || true
    fi

    if [[ -n "${MOVEIT_PID:-}" ]]; then
        kill -TERM "${MOVEIT_PID}" 2>/dev/null || true
    fi

    wait 2>/dev/null || true
}

trap shutdown SIGINT SIGTERM EXIT

if [[ "${USE_FAKE_HARDWARE}" == "true" ]]; then
    echo "Avvio MoveIt con fake hardware"

    ros2 launch franka_fr3_moveit_config moveit.launch.py \
        robot_ip:=dont-care \
        use_fake_hardware:=true \
        load_gripper:="${LOAD_GRIPPER}" &

else
    if [[ -z "${FRANKA_ROBOT_IP}" ]]; then
        echo "FRANKA_ROBOT_IP non configurato"
        exit 1
    fi

    echo "Avvio MoveIt con Franka reale: ${FRANKA_ROBOT_IP}"

    ros2 launch franka_fr3_moveit_config moveit.launch.py \
        robot_ip:="${FRANKA_ROBOT_IP}" \
        use_fake_hardware:=false \
        load_gripper:="${LOAD_GRIPPER}" &
fi

MOVEIT_PID=$!

python3 /app/app.py &
API_PID=$!

# Se uno dei due processi termina, termina anche il container.
wait -n "${MOVEIT_PID}" "${API_PID}"

echo "Uno dei processi principali si è arrestato."
exit 1