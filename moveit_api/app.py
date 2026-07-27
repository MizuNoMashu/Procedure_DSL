import logging
import os
import threading
from datetime import datetime, timezone

import rclpy
from flask import Flask, jsonify
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node

from moveit_client import MoveItInterface
from routes import init_routes, moveit_bp


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("moveit-api")

app = Flask(__name__)

rclpy.init()

ros_node = Node("moveit_http_api")
ros_executor = SingleThreadedExecutor()
ros_executor.add_node(ros_node)


def spin_ros() -> None:
    """Mantiene aggiornato il nodo e il grafo ROS 2."""
    try:
        ros_executor.spin()
    except Exception:
        logger.exception("Errore durante lo spin ROS 2")


ros_thread = threading.Thread(
    target=spin_ros,
    name="ros2-executor",
    daemon=True,
)
ros_thread.start()

moveit_interface = MoveItInterface(
    ros_node,
    namespace=os.getenv("MOVEIT_NS", ""),
    default_group_override=os.getenv("MOVEIT_GROUP_NAME"),
    default_eef_link_override=os.getenv("MOVEIT_EEF_LINK"),
)
moveit_interface.start_discovery_loop()

init_routes(moveit_interface)
app.register_blueprint(moveit_bp)


def get_ros_nodes() -> list[str]:
    """Restituisce i nomi completi dei nodi ROS visibili."""
    return sorted(
        full_name
        for _, _, full_name in ros_node.get_node_names_and_namespaces()
    )


@app.get("/health")
def health():
    nodes = get_ros_nodes()

    move_group_available = any(
        node == "/move_group" or node.endswith("/move_group")
        for node in nodes
    )

    controller_manager_available = any(
        node == "/controller_manager" or node.endswith("/controller_manager")
        for node in nodes
    )

    healthy = (
        rclpy.ok()
        and move_group_available
        and controller_manager_available
    )

    body = {
        "status": "UP" if healthy else "DEGRADED",
        "service": "moveit-api",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ros": {
            "initialized": rclpy.ok(),
            "move_group": move_group_available,
            "controller_manager": controller_manager_available,
            "nodes": nodes,
        },
        "moveit": moveit_interface.status_dict(),
    }

    return jsonify(body), 200 if healthy else 503


@app.get("/ready")
def ready():
    """Endpoint minimale per il Docker healthcheck."""
    nodes = get_ros_nodes()

    move_group_available = any(
        node == "/move_group" or node.endswith("/move_group")
        for node in nodes
    )

    if not move_group_available:
        return jsonify({
            "ready": False,
            "reason": "move_group non disponibile",
        }), 503

    return jsonify({"ready": True}), 200


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
        use_reloader=False,
        threaded=True,
    )