"""
Bridge simulatore -> ROS 2.

Riceve via UDP lo stato del robot simulato (pylibfranka sim, in un altro processo)
e lo pubblica su:
  /joint_states          sensor_msgs/JointState  (7 giunti + dita del gripper)
  /cobot_sim/ee_pose     geometry_msgs/PoseStamped (frame fr3_link0)
  /cobot_sim/status      std_msgs/String (JSON con modo, gripper, forze)
robot_state_publisher ne ricava i TF (RViz). Lo stesso processo serve anche il
visualizzatore 3D locale (http://localhost:8090): pagina, librerie, URDF, mesh e /state.
"""

import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import String

ARM_ID = os.getenv("SIM_ARM_ID", "fr3")
JOINTS = [f"{ARM_ID}_joint{i}" for i in range(1, 8)]
FINGERS = [f"{ARM_ID}_finger_joint1", f"{ARM_ID}_finger_joint2"]


def rotation_to_quaternion(m):
    r = [m[0:3], m[3:6], m[6:9]]
    trace = r[0][0] + r[1][1] + r[2][2]
    if trace > 0:
        s = (trace + 1.0) ** 0.5 * 2
        return ((r[2][1] - r[1][2]) / s, (r[0][2] - r[2][0]) / s, (r[1][0] - r[0][1]) / s, 0.25 * s)
    if r[0][0] > r[1][1] and r[0][0] > r[2][2]:
        s = (1.0 + r[0][0] - r[1][1] - r[2][2]) ** 0.5 * 2
        return (0.25 * s, (r[0][1] + r[1][0]) / s, (r[0][2] + r[2][0]) / s, (r[2][1] - r[1][2]) / s)
    if r[1][1] > r[2][2]:
        s = (1.0 + r[1][1] - r[0][0] - r[2][2]) ** 0.5 * 2
        return ((r[0][1] + r[1][0]) / s, 0.25 * s, (r[1][2] + r[2][1]) / s, (r[0][2] - r[2][0]) / s)
    s = (1.0 + r[2][2] - r[0][0] - r[1][1]) ** 0.5 * 2
    return ((r[0][2] + r[2][0]) / s, (r[1][2] + r[2][1]) / s, 0.25 * s, (r[1][0] - r[0][1]) / s)


VIEWER_DIR = os.getenv("SIM_VIEWER_DIR", "/opt/sim/viewer")
DESCRIPTION_DIR = os.getenv(
    "SIM_DESCRIPTION_DIR", "/ws/install/franka_description/share/franka_description"
)
URDF_FILE = os.getenv("SIM_URDF_FILE", "/tmp/robot.urdf")
CONFIG_FILE = os.getenv("SIM_CONFIG_FILE", "/tmp/cobot_sim_config.json")
MIME = {".html": "text/html", ".js": "text/javascript", ".dae": "model/vnd.collada+xml",
        ".stl": "model/stl", ".urdf": "application/xml", ".json": "application/json"}


def contact_z():
    try:
        with open(CONFIG_FILE) as handle:
            return json.load(handle).get("contact_z")
    except (OSError, ValueError):
        value = os.getenv("SIM_CONTACT_Z")
        return float(value) if value else None


def make_handler(bridge):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, body, ctype):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _file(self, root, rel):
            root = os.path.realpath(root)
            path = os.path.realpath(os.path.join(root, rel.lstrip("/")))
            if not path.startswith(root + os.sep) or not os.path.isfile(path):
                self.send_error(404)
                return
            with open(path, "rb") as handle:
                self._send(handle.read(), MIME.get(os.path.splitext(path)[1], "application/octet-stream"))

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/state":
                with bridge._lock:
                    snap = dict(bridge._latest or {})
                if not snap:
                    return self._send(b"{}", "application/json")
                snap["contact_z"] = contact_z()
                return self._send(json.dumps(snap).encode(), "application/json")
            if path == "/robot.urdf":
                return self._file(os.path.dirname(URDF_FILE), os.path.basename(URDF_FILE))
            if path.startswith("/pkg/franka_description/"):
                return self._file(DESCRIPTION_DIR, path[len("/pkg/franka_description/"):])
            if path.startswith("/vendor/"):
                return self._file(os.path.join(VIEWER_DIR, "vendor"), path[len("/vendor/"):])
            if path in ("/", "/index.html"):
                return self._file(VIEWER_DIR, "index.html")
            self.send_error(404)

    return Handler


class SimBridge(Node):
    def __init__(self):
        super().__init__("cobot_sim_bridge")
        self.joint_pub = self.create_publisher(JointState, "/joint_states", 10)
        self.pose_pub = self.create_publisher(PoseStamped, "/cobot_sim/ee_pose", 10)
        self.status_pub = self.create_publisher(String, "/cobot_sim/status", 10)
        self._latest = None
        self._lock = threading.Lock()

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("0.0.0.0", int(os.getenv("SIM_BRIDGE_PORT", "5599"))))
        threading.Thread(target=self._receive, daemon=True).start()
        self.create_timer(1.0 / float(os.getenv("SIM_ROS_HZ", "50")), self._publish)
        server = ThreadingHTTPServer(("0.0.0.0", int(os.getenv("VIEWER_PORT", "8090"))), make_handler(self))
        threading.Thread(target=server.serve_forever, daemon=True).start()

    def _receive(self):
        while True:
            data, _ = self._sock.recvfrom(65535)
            try:
                with self._lock:
                    self._latest = json.loads(data)
            except ValueError:
                pass

    def _publish(self):
        with self._lock:
            snap = self._latest
        if snap is None:
            return
        now = self.get_clock().now().to_msg()

        joints = JointState()
        joints.header.stamp = now
        joints.name = JOINTS + FINGERS
        finger = snap["gripper_width"] / 2.0
        joints.position = list(snap["q"]) + [finger, finger]
        self.joint_pub.publish(joints)

        pose = PoseStamped()
        pose.header.stamp = now
        pose.header.frame_id = f"{ARM_ID}_link0"
        pose.pose.position.x, pose.pose.position.y, pose.pose.position.z = snap["ee"]
        (pose.pose.orientation.x, pose.pose.orientation.y,
         pose.pose.orientation.z, pose.pose.orientation.w) = rotation_to_quaternion(snap["ee_rot"])
        self.pose_pub.publish(pose)

        status = String()
        status.data = json.dumps({k: snap[k] for k in ("mode", "gripper_width", "grasped", "external_force", "sim_time", "sigma_min")})
        self.status_pub.publish(status)


def main():
    rclpy.init()
    node = SimBridge()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
