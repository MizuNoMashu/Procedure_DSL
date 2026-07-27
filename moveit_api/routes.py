"""
Endpoint REST per la sola pianificazione di traiettorie MoveIt.

Questo servizio non attua nulla: ogni endpoint /moveit/plan-* chiede a
move_group di pianificare (IK + collision checking + OMPL) con
plan_only=True e restituisce la traiettoria calcolata (waypoint articolari
+ timing). L'esecuzione sul robot resta interamente a carico del servizio
'cobot'. Una sola richiesta di pianificazione alla volta (lock non
bloccante -> 409 se occupato).
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from moveit_client.interface import MoveItNotReadyError, PlanningBusyError

moveit_bp = Blueprint("moveit", __name__, url_prefix="/moveit")

_interface = None  # iniettato da app.py con init_routes()


def init_routes(interface) -> None:
    global _interface
    _interface = interface


def _not_ready():
    return jsonify({
        "error": "MoveIt non ancora pronto",
        "detail": _interface.discovery_error if _interface else "interface non inizializzata",
    }), 503


def _busy():
    return jsonify({"error": "un'altra richiesta di pianificazione è già in corso"}), 409


def _plan_result_response(result):
    status_code = 200 if result.success else 422
    return jsonify({
        "success": result.success,
        "error_code": result.error_code,
        "error_name": result.error_name,
        "planning_time": result.planning_time,
        "trajectory": {
            "joint_names": result.joint_names,
            "points": [
                {
                    "positions": p.positions,
                    "velocities": p.velocities,
                    "accelerations": p.accelerations,
                    "time_from_start": p.time_from_start,
                }
                for p in result.points
            ],
        },
    }), status_code


@moveit_bp.route("/groups", methods=["GET"])
def groups():
    """Planning group, target nominati (group_state) ed end-effector scoperti dall'SRDF."""
    if _interface is None or not _interface.is_ready:
        return _not_ready()
    return jsonify(_interface.groups_info()), 200


@moveit_bp.route("/status", methods=["GET"])
def status():
    if _interface is None:
        return jsonify({"ready": False, "busy": False}), 200
    return jsonify(_interface.status_dict()), 200


@moveit_bp.route("/state", methods=["GET"])
def state():
    if _interface is None or not _interface.is_ready:
        return _not_ready()
    joint_state = _interface.latest_joint_state()
    if joint_state is None:
        return jsonify({"error": "nessun /joint_states ricevuto ancora"}), 503
    return jsonify({"joint_state": joint_state, "busy": _interface.is_busy}), 200


@moveit_bp.route("/pose", methods=["GET"])
def pose():
    """Pose (FK) corrente dell'end-effector, calcolata dall'ultimo /joint_states noto
    a questo processo (che se USE_FAKE_HARDWARE=true riflette il fake hardware, non
    necessariamente lo stato reale del robot pilotato da 'cobot')."""
    if _interface is None or not _interface.is_ready:
        return _not_ready()
    link_name = request.args.get("link_name")
    try:
        return jsonify(_interface.get_fk_pose(link_name=link_name)), 200
    except MoveItNotReadyError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500


@moveit_bp.route("/plan-joint", methods=["POST"])
def plan_joint():
    """
    Body:
      joint_positions      : {joint_name: radianti, ...}  (richiesto, target)
      group                : string (opzionale, default = gruppo arm scoperto)
      speed_factor         : float (0,1] (default 0.2, scala velocità/accelerazione della traiettoria)
      tolerance            : radianti (default 0.001)
      planning_time        : secondi (default 5.0)
      start_joint_positions: {joint_name: radianti, ...} (opzionale). Se assente, si pianifica
                             dallo stato che move_group conosce come "corrente" (che con
                             USE_FAKE_HARDWARE=true NON è lo stato reale del robot pilotato
                             da cobot). Per pianificare da uno stato reale, passarlo esplicitamente
                             (es. letto da GET /api/robot/state del servizio cobot).
    """
    if _interface is None or not _interface.is_ready:
        return _not_ready()

    body = request.get_json(silent=True) or {}
    joint_positions = body.get("joint_positions")
    if not joint_positions or not isinstance(joint_positions, dict):
        return jsonify({"error": "joint_positions deve essere un oggetto {joint_name: valore}"}), 400

    start_joint_positions = body.get("start_joint_positions")

    try:
        result = _interface.plan_joint(
            joint_positions={k: float(v) for k, v in joint_positions.items()},
            group=body.get("group"),
            speed_factor=float(body.get("speed_factor", 0.2)),
            tolerance=float(body.get("tolerance", 0.001)),
            planning_time=float(body.get("planning_time", 5.0)),
            start_joint_positions=(
                {k: float(v) for k, v in start_joint_positions.items()}
                if start_joint_positions else None
            ),
        )
    except PlanningBusyError:
        return _busy()
    except (MoveItNotReadyError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500

    return _plan_result_response(result)


@moveit_bp.route("/plan-named", methods=["POST"])
def plan_named():
    """
    Body:
      name                 : nome dello stato SRDF (es. "ready")  (richiesto)
      group                : string (opzionale, default = gruppo arm scoperto)
      speed_factor         : float (0,1] (default 0.2)
      start_joint_positions: vedi /moveit/plan-joint (opzionale)
    """
    if _interface is None or not _interface.is_ready:
        return _not_ready()

    body = request.get_json(silent=True) or {}
    state_name = body.get("name")
    if not state_name:
        return jsonify({"error": "'name' richiesto"}), 400

    start_joint_positions = body.get("start_joint_positions")

    try:
        result = _interface.plan_named(
            state_name=state_name,
            group=body.get("group"),
            speed_factor=float(body.get("speed_factor", 0.2)),
            planning_time=float(body.get("planning_time", 5.0)),
            start_joint_positions=(
                {k: float(v) for k, v in start_joint_positions.items()}
                if start_joint_positions else None
            ),
        )
    except PlanningBusyError:
        return _busy()
    except (MoveItNotReadyError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500

    return _plan_result_response(result)


@moveit_bp.route("/plan-pose", methods=["POST"])
def plan_pose():
    """
    Body:
      position             : {x, y, z}  (richiesto, metri)
      orientation           : {x, y, z, w}  (quaternione; alternativo a rpy)
      rpy                   : [roll, pitch, yaw]  (radianti; alternativo a orientation)
      group                 : string (opzionale)
      link_name             : string (opzionale, default = end-effector scoperto dall'SRDF)
      frame_id              : string (opzionale, default = base_link del gruppo)
      speed_factor          : float (0,1] (default 0.2)
      tolerance_position    : metri (default 0.01)
      tolerance_orientation : radianti (default 0.02)
      start_joint_positions : vedi /moveit/plan-joint (opzionale)
    """
    if _interface is None or not _interface.is_ready:
        return _not_ready()

    body = request.get_json(silent=True) or {}
    position = body.get("position")
    if not position or not all(k in position for k in ("x", "y", "z")):
        return jsonify({"error": "position deve contenere x, y, z"}), 400

    orientation = body.get("orientation")
    rpy = body.get("rpy")
    if orientation is None and rpy is None:
        return jsonify({"error": "specificare 'orientation' (quaternione) oppure 'rpy'"}), 400

    start_joint_positions = body.get("start_joint_positions")

    try:
        result = _interface.plan_pose(
            position=position,
            orientation=orientation,
            rpy=rpy,
            group=body.get("group"),
            link_name=body.get("link_name"),
            frame_id=body.get("frame_id"),
            speed_factor=float(body.get("speed_factor", 0.2)),
            tolerance_position=float(body.get("tolerance_position", 0.01)),
            tolerance_orientation=float(body.get("tolerance_orientation", 0.02)),
            planning_time=float(body.get("planning_time", 5.0)),
            start_joint_positions=(
                {k: float(v) for k, v in start_joint_positions.items()}
                if start_joint_positions else None
            ),
        )
    except PlanningBusyError:
        return _busy()
    except (MoveItNotReadyError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500

    return _plan_result_response(result)


@moveit_bp.route("/cancel", methods=["POST"])
def cancel():
    """Annulla una richiesta di pianificazione in corso (non c'è nessuna esecuzione da fermare)."""
    if _interface is None:
        return _not_ready()
    cancelled = _interface.cancel()
    return jsonify({"cancelled": cancelled}), 200
