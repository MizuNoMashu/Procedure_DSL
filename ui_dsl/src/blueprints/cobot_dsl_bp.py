"""
DSL-for-Cobot blueprint.

Endpoints for loading DSL files, assigning cobot operations to steps,
saving back to both external and internal DSL, and executing operations
via the cobot service proxy.
"""

import os
import time
from pathlib import Path

import requests as _requests
from flask import Blueprint, jsonify, request, render_template

from pipeline.dsl_cobot_ops import update_internal_dsl_cobot_ops
from pipeline.dsl_converter import (
    internal_to_external,
    external_to_internal,
    parse_internal_dsl,
)
from pipeline.output_paths import output_root, find_in_any_folder

cobot_dsl_bp = Blueprint("cobot_dsl", __name__)

_SRC_DIR = Path(__file__).parent.parent
_COBOT_URL = os.environ.get("COBOT_SERVICE_URL", "http://cobot:5000")


# ── Available cobot operations ────────────────────────────────────────────────
# Each entry maps a logical operation name to its REST endpoint on the cobot
# service plus a typed parameter schema used by the UI to render input fields.
# `to_body` converts the UI parameters into the JSON body the endpoint expects.
#
# param types:
#   "array7"  → 7-element float array  (joint positions/deltas, rad)
#   "float"   → single float value
_SPEED = {
    "type": "float",
    "description": "Speed factor (0-1)",
    "default": 0.2,
    "required": False,
}

COBOT_OP_REGISTRY = {
    "move_home": {
        "endpoint": "/api/motion/move-home",
        "description": "Return robot to home position",
        "params": {"speed_factor": _SPEED},
        "to_body": lambda p: _only(p, "speed_factor"),
    },
    "move_joints": {
        "endpoint": "/api/motion-position-control/move",
        "description": "Move robot to absolute joint positions",
        "params": {
            "joints": {
                "type": "array7",
                "description": "7 joint positions (rad)",
                "required": True,
            },
            "speed_factor": _SPEED,
        },
        "to_body": lambda p: {"positions": p["joints"], **_only(p, "speed_factor")},
    },
    "move_relative": {
        "endpoint": "/api/motion-position-control/move-relative",
        "description": "Move robot by relative joint deltas",
        "params": {
            "delta": {
                "type": "array7",
                "description": "7 joint deltas (rad)",
                "required": True,
            },
            "speed_factor": _SPEED,
        },
        "to_body": lambda p: {"deltas": p["delta"], **_only(p, "speed_factor")},
    },
    "move_cartesian": {
        "endpoint": "/api/motion-cartesian/move",
        "description": "Move end-effector to an absolute Cartesian pose",
        "params": {
            "x": {"type": "float", "description": "x (m)", "required": True},
            "y": {"type": "float", "description": "y (m)", "required": True},
            "z": {"type": "float", "description": "z (m)", "required": True},
            "roll": {"type": "float", "description": "roll (rad)", "default": 0.0, "required": False},
            "pitch": {"type": "float", "description": "pitch (rad)", "default": 0.0, "required": False},
            "yaw": {"type": "float", "description": "yaw (rad)", "default": 0.0, "required": False},
            "speed_factor": _SPEED,
        },
        "to_body": lambda p: dict(p),
    },
    "pick_and_place": {
        "endpoint": "/api/motion/pick-and-place",
        "description": "Full pick-and-place workflow (home → open → pick → place → release → home)",
        "params": {
            "pick_pose": {
                "type": "array7",
                "description": "Pick joint positions (rad)",
                "required": True,
            },
            "place_pose": {
                "type": "array7",
                "description": "Place joint positions (rad)",
                "required": True,
            },
            "grasp_force": {
                "type": "float",
                "description": "Grasp force (N)",
                "default": 10.0,
                "required": False,
            },
            "grasp_width": {
                "type": "float",
                "description": "Grasp width (m)",
                "default": 0.04,
                "required": False,
            },
        },
        "to_body": lambda p: {
            "pick_position": p["pick_pose"],
            "place_position": p["place_pose"],
            **({"grasp_force": p["grasp_force"]} if "grasp_force" in p else {}),
            **({"grasp_width_mm": p["grasp_width"] * 1000.0} if "grasp_width" in p else {}),
        },
    },
    "gripper_open": {
        "endpoint": "/api/gripper/open",
        "description": "Open gripper to specified width",
        "params": {
            "width": {
                "type": "float",
                "description": "Target width (m, max 0.08)",
                "default": 0.08,
                "required": False,
            }
        },
        "to_body": lambda p: {"width_mm": p["width"] * 1000.0} if "width" in p else {},
    },
    "gripper_close": {
        "endpoint": "/api/gripper/close",
        "description": "Close gripper fully",
        "params": {},
        "to_body": lambda p: {},
    },
    "gripper_grasp": {
        "endpoint": "/api/gripper/grasp",
        "description": "Grasp object with controlled force",
        "params": {
            "width": {
                "type": "float",
                "description": "Target width (m)",
                "required": True,
            },
            "force": {
                "type": "float",
                "description": "Grasp force (N)",
                "required": True,
            },
            "speed": {
                "type": "float",
                "description": "Closing speed (m/s)",
                "default": 0.1,
                "required": False,
            },
        },
        "to_body": lambda p: {"width_mm": p["width"] * 1000.0, **_only(p, "force", "speed")},
    },
    "gripper_release": {
        "endpoint": "/api/gripper/release",
        "description": "Release object (open gripper)",
        "params": {},
        "to_body": lambda p: {},
    },
}


def _only(params, *keys):
    return {k: params[k] for k in keys if k in params}


# ── Page ──────────────────────────────────────────────────────────────────────

@cobot_dsl_bp.route("/dsl-cobot", methods=["GET"])
def dsl_cobot_page():
    return render_template("dsl_cobot.html")


@cobot_dsl_bp.route("/dsl-manage", methods=["GET"])
def dsl_manage_page():
    return render_template("dsl_manage.html")


# ── API ───────────────────────────────────────────────────────────────────────

@cobot_dsl_bp.route("/dsl-cobot/list-dsl", methods=["GET"])
def list_dsl_files():
    """List available DSL files across all per-CSV output folders."""
    out = output_root(_SRC_DIR)
    external = sorted(f.name for f in out.glob("*/*_external_DSL.yml"))
    internal = sorted(f.name for f in out.glob("*/*_internal_DSL.txt"))
    return jsonify({"external": external, "internal": internal})


@cobot_dsl_bp.route("/dsl-cobot/load-dsl", methods=["POST"])
def load_dsl():
    """
    Parse an internal DSL file and return its steps with any existing
    cobot operations, normalised to the format the UI expects.

    Body: {"filename": "<name>_internal_DSL.txt"}
    """
    data = request.get_json(silent=True) or {}
    filename = data.get("filename", "").strip()
    if not filename:
        return jsonify({"error": "filename required"}), 400

    path = find_in_any_folder(_SRC_DIR, filename)
    if path is None:
        return jsonify({"error": "File not found"}), 404

    try:
        parsed = parse_internal_dsl(str(path))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # Normalise to the format the UI expects
    steps = []
    for s in parsed["steps"]:
        on_comps = [t[0] for t in s["on"]] if s["on"] else []
        involved = ([s["comp_name"]] + on_comps) if s["comp_name"] else on_comps
        steps.append({
            "step_number":         s["step_number"],
            "description":         s["description"],
            "involved_components": involved,
            "action":              s["action"],
            "on":                  s["on"],
            "tool_type":           s["tool_type"],
            "tool_name":           s.get("tool_name"),
            "tool_detail":         s.get("tool_detail") or {},
            "cobot_operations":    s["cobot_ops"],
        })

    return jsonify({"project_name": parsed["project_name"], "steps": steps})


@cobot_dsl_bp.route("/dsl-cobot/op-registry", methods=["GET"])
def op_registry():
    """Return the available cobot operation registry."""
    return jsonify({
        name: {k: v for k, v in op.items() if k != "to_body"}
        for name, op in COBOT_OP_REGISTRY.items()
    })


@cobot_dsl_bp.route("/dsl-cobot/save-cobot-ops", methods=["POST"])
def save_cobot_ops():
    """
    Persist cobot operations into the internal DSL, then regenerate the external DSL.

    Body:
    {
        "filename": str,   # internal DSL filename (_internal_DSL.txt)
        "ops": {"1": ["op_str", ...], "3": ["op_str"], ...}
    }
    """
    data = request.get_json(silent=True) or {}
    int_filename = data.get("filename", "").strip()
    ops_raw = data.get("ops", {})

    if not int_filename:
        return jsonify({"error": "filename required"}), 400

    ops = {int(k): v for k, v in ops_raw.items()}

    int_path = find_in_any_folder(_SRC_DIR, int_filename)
    if int_path is None:
        return jsonify({"error": f"Internal DSL not found: {int_filename}"}), 404

    try:
        update_internal_dsl_cobot_ops(str(int_path), ops)
    except Exception as e:
        return jsonify({"error": f"Failed to update internal DSL: {e}"}), 500

    # Regenerate external DSL alongside the internal DSL it was derived from
    ext_filename = int_filename.replace("_internal_DSL.txt", "_external_DSL.yml")
    ext_path = int_path.parent / ext_filename
    try:
        internal_to_external(str(int_path), str(ext_path))
    except Exception as e:
        return jsonify({"error": f"Failed to regenerate external DSL: {e}"}), 500

    return jsonify({
        "ok": True,
        "internal_filename": int_filename,
        "external_filename": ext_filename,
    })


_OP_TIMEOUT_SEC = float(os.environ.get("COBOT_OP_TIMEOUT_SEC", "600"))
_POLL_SEC = 0.3


def _wait_until_idle(headers):
    """Poll the cobot until the async operation ends; return its last_operation."""
    deadline = time.monotonic() + _OP_TIMEOUT_SEC
    while time.monotonic() < deadline:
        status = _requests.get(f"{_COBOT_URL}/api/robot/status", headers=headers, timeout=10).json()
        if not status.get("busy"):
            return status
        time.sleep(_POLL_SEC)
    return None


@cobot_dsl_bp.route("/dsl-cobot/execute-op", methods=["POST"])
def execute_cobot_op():
    """
    Execute a single cobot operation via the cobot service and wait for it to finish.

    The cobot only accepts commands from the active session of its FIFO queue:
    the browser opens it (static/cobot_session.js) and sends it in X-Session-Id.

    Body: {"func": "pick_and_place", "params": {"pick_pose": [...], ...}}
    """
    data = request.get_json(silent=True) or {}
    func_name = data.get("func", "").strip()
    params = data.get("params") or {}

    if func_name not in COBOT_OP_REGISTRY:
        return jsonify({"error": f"Unknown operation: {func_name}"}), 400

    op = COBOT_OP_REGISTRY[func_name]
    url = f"{_COBOT_URL}{op['endpoint']}"
    headers = {k: v for k, v in request.headers.items() if k.lower() == "x-session-id"}

    try:
        body = op["to_body"](params)
    except KeyError as e:
        return jsonify({"error": f"Missing parameter: {e.args[0]}"}), 400

    try:
        resp = _requests.post(url, json=body, headers=headers, timeout=60)
        if resp.status_code != 202:
            return (
                resp.content,
                resp.status_code,
                {"Content-Type": resp.headers.get("Content-Type", "application/json")},
            )

        status = _wait_until_idle(headers)
        if status is None:
            return jsonify({"error": "Timed out waiting for the operation to finish"}), 504
        last = status.get("last_operation") or {}
        if last.get("success") is False or status.get("mode") == "error_locked":
            return jsonify({
                "error": last.get("error") or "Operation failed",
                "operation": last.get("operation"),
                "mode": status.get("mode"),
            }), 500
        return jsonify({"status": "completed", "operation": last.get("operation")}), 200
    except _requests.exceptions.ConnectionError:
        return jsonify({"error": f"Cobot service unreachable at {_COBOT_URL}"}), 503
    except _requests.exceptions.Timeout:
        return jsonify({"error": "Cobot service timed out"}), 504


# ── DSL Converter ──────────────────────────────────────────────────────────────

@cobot_dsl_bp.route("/dsl-cobot/convert", methods=["POST"])
def convert_dsl():
    """
    Convert between internal and external DSL formats.

    Body:
    {
        "direction": "internal_to_external" | "external_to_internal",
        "filename": str      # source file (must be in output dir)
    }

    Returns: {"ok": true, "output_filename": str, "download_url": str}
    """
    data = request.get_json(silent=True) or {}
    direction = data.get("direction", "").strip()
    filename  = data.get("filename", "").strip()

    if direction not in ("internal_to_external", "external_to_internal"):
        return jsonify({"error": "direction must be 'internal_to_external' or 'external_to_internal'"}), 400
    if not filename:
        return jsonify({"error": "filename required"}), 400

    src_path = find_in_any_folder(_SRC_DIR, filename)
    if src_path is None:
        return jsonify({"error": f"File not found: {filename}"}), 404

    try:
        if direction == "internal_to_external":
            # e.g. Cubesat_internal_DSL.txt → Cubesat_external_DSL.yml
            out_name = filename.replace("_internal_DSL.txt", "_external_DSL.yml")
            out_path = str(src_path.parent / out_name)
            internal_to_external(str(src_path), out_path)
        else:
            # e.g. Cubesat_external_DSL.yml → Cubesat_internal_DSL.txt
            out_name = filename.replace("_external_DSL.yml", "_internal_DSL.txt")
            out_path = str(src_path.parent / out_name)
            external_to_internal(str(src_path), out_path)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "ok": True,
        "output_filename": out_name,
        "download_url": f"/download-dsl/{out_name}",
    })
