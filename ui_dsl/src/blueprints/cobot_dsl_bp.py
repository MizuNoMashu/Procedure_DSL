"""
DSL-for-Cobot blueprint.

Endpoints for loading DSL files, assigning cobot operations to steps,
saving back to both external and internal DSL, and executing operations
via the cobot service proxy.
"""

import os
from pathlib import Path

import requests as _requests
from flask import Blueprint, jsonify, request, render_template

from pipeline.dsl_cobot_ops import update_internal_dsl_cobot_ops
from pipeline.dsl_converter import (
    internal_to_external,
    external_to_internal,
    parse_internal_dsl,
)

cobot_dsl_bp = Blueprint("cobot_dsl", __name__)

_SRC_DIR = Path(__file__).parent.parent
_COBOT_URL = os.environ.get("COBOT_SERVICE_URL", "http://cobot:5000")


# ── Available cobot operations ────────────────────────────────────────────────
# Each entry maps a logical operation name to its REST endpoint on the cobot
# service plus a typed parameter schema used by the UI to render input fields.
#
# param types:
#   "array6"  → 6-element float array  [x, y, z, rx, ry, rz]
#   "array7"  → 7-element float array  (joint positions/deltas, rad)
#   "float"   → single float value
COBOT_OP_REGISTRY = {
    "move_home": {
        "endpoint": "/api/motion/move-home",
        "description": "Return robot to home position",
        "params": {},
    },
    "move_joints": {
        "endpoint": "/api/motion/move-joints",
        "description": "Move robot to absolute joint positions",
        "params": {
            "joints": {
                "type": "array7",
                "description": "7 joint positions (rad)",
                "required": True,
            }
        },
    },
    "move_relative": {
        "endpoint": "/api/motion/move-relative",
        "description": "Move robot by relative joint deltas",
        "params": {
            "delta": {
                "type": "array7",
                "description": "7 joint deltas (rad)",
                "required": True,
            }
        },
    },
    "pick_and_place": {
        "endpoint": "/api/motion/pick-and-place",
        "description": "Full pick-and-place workflow (home → open → pick → place → release → home)",
        "params": {
            "pick_pose": {
                "type": "array6",
                "description": "Pick pose [x, y, z, rx, ry, rz] (m / rad)",
                "required": True,
            },
            "place_pose": {
                "type": "array6",
                "description": "Place pose [x, y, z, rx, ry, rz] (m / rad)",
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
    },
    "gripper_close": {
        "endpoint": "/api/gripper/close",
        "description": "Close gripper fully",
        "params": {},
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
    },
    "gripper_release": {
        "endpoint": "/api/gripper/release",
        "description": "Release object (open gripper)",
        "params": {
            "width": {
                "type": "float",
                "description": "Release width (m)",
                "default": 0.08,
                "required": False,
            }
        },
    },
}


def _output_dir() -> Path:
    p = _SRC_DIR / "output"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_path(filename: str) -> Path | None:
    """Resolve filename inside output_dir; return None if it escapes the dir."""
    out = _output_dir().resolve()
    path = (out / filename).resolve()
    if not str(path).startswith(str(out)):
        return None
    return path


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
    """List available DSL files in the output directory."""
    out = _output_dir()
    external = sorted(f.name for f in out.glob("*_external_DSL.yml"))
    internal = sorted(f.name for f in out.glob("*_internal_DSL.txt"))
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

    path = _safe_path(filename)
    if path is None:
        return jsonify({"error": "Invalid filename"}), 400
    if not path.exists():
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
            "cobot_operations":    s["cobot_ops"],
        })

    return jsonify({"project_name": parsed["project_name"], "steps": steps})


@cobot_dsl_bp.route("/dsl-cobot/op-registry", methods=["GET"])
def op_registry():
    """Return the available cobot operation registry."""
    return jsonify(COBOT_OP_REGISTRY)


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

    int_path = _safe_path(int_filename)
    if int_path is None or not int_path.exists():
        return jsonify({"error": f"Internal DSL not found: {int_filename}"}), 404

    try:
        update_internal_dsl_cobot_ops(str(int_path), ops)
    except Exception as e:
        return jsonify({"error": f"Failed to update internal DSL: {e}"}), 500

    # Regenerate external DSL
    ext_filename = int_filename.replace("_internal_DSL.txt", "_external_DSL.yml")
    ext_path = _safe_path(ext_filename)
    if ext_path is not None:
        try:
            internal_to_external(str(int_path), str(ext_path))
        except Exception as e:
            return jsonify({"error": f"Failed to regenerate external DSL: {e}"}), 500

    return jsonify({
        "ok": True,
        "internal_filename": int_filename,
        "external_filename": ext_filename,
    })


@cobot_dsl_bp.route("/dsl-cobot/execute-op", methods=["POST"])
def execute_cobot_op():
    """
    Execute a single cobot operation via the cobot service.

    Body: {"func": "pick_and_place", "params": {"pick_pose": [...], ...}}
    """
    data = request.get_json(silent=True) or {}
    func_name = data.get("func", "").strip()
    params = data.get("params", {})

    if func_name not in COBOT_OP_REGISTRY:
        return jsonify({"error": f"Unknown operation: {func_name}"}), 400

    op = COBOT_OP_REGISTRY[func_name]
    url = f"{_COBOT_URL}{op['endpoint']}"

    try:
        resp = _requests.post(url, json=params, timeout=60)
        return (
            resp.content,
            resp.status_code,
            {"Content-Type": resp.headers.get("Content-Type", "application/json")},
        )
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

    src_path = _safe_path(filename)
    if src_path is None or not src_path.exists():
        return jsonify({"error": f"File not found: {filename}"}), 404

    out = _output_dir()

    try:
        if direction == "internal_to_external":
            # e.g. Cubesat_internal_DSL.txt → Cubesat_external_DSL.yml
            out_name = filename.replace("_internal_DSL.txt", "_external_DSL.yml")
            out_path = str(out / out_name)
            internal_to_external(str(src_path), out_path)
        else:
            # e.g. Cubesat_external_DSL.yml → Cubesat_internal_DSL.txt
            out_name = filename.replace("_external_DSL.yml", "_internal_DSL.txt")
            out_path = str(out / out_name)
            external_to_internal(str(src_path), out_path)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "ok": True,
        "output_filename": out_name,
        "download_url": f"/download-dsl/{out_name}",
    })
