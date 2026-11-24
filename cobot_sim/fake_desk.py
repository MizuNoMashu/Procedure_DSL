"""
Desk API finta del Franka (stessi endpoint usati da franka_controller.FrankaDeskAPI).

Tiene lo stato minimo per far funzionare prepare_for_fci(): token SPoC, modalità
operativa, freni dei giunti e FCI. Nessuna autenticazione.
"""

import json
import os
import uuid

from flask import Flask, jsonify, request

app = Flask(__name__)

state = {
    "token": None,
    "token_id": 0,
    "owner": None,
    "mode": "Programming",
    "brakes": "Locked",
    "fci": "Inactive",
    "recovery": None,
}


def _no_content():
    return "", 204


def _need_token():
    if state["token"] is None or request.headers.get("X-Control-Token") != state["token"]:
        return jsonify({"code": "ControlTokenError", "message": "control token mancante o non valido"}), 403
    return None


@app.get("/api/system")
def system():
    return jsonify({"status": "Started", "version": "sim"})


@app.get("/api/system/operating-mode")
def operating_mode():
    return jsonify({"mode": state["mode"]})


@app.post("/api/system/operating-mode:change")
def change_operating_mode():
    denied = _need_token()
    if denied:
        return denied
    state["mode"] = (request.get_json(silent=True) or {}).get("desiredOperatingMode", "Execution")
    return _no_content()


@app.get("/api/system/control-token")
def token_state():
    return jsonify({"active": state["token"] is not None, "owner": state["owner"], "tokenId": state["token_id"]})


@app.post("/api/system/control-token:take")
def take_token():
    force = request.args.get("force") == "true"
    if state["token"] is not None and not force:
        return jsonify({"code": "ControlTokenError", "message": "token già preso da " + str(state["owner"])}), 423
    state["token"] = uuid.uuid4().hex
    state["token_id"] += 1
    state["owner"] = (request.get_json(silent=True) or {}).get("owner", "unknown")
    return jsonify({"token": state["token"], "tokenId": state["token_id"]})


@app.post("/api/system/control-token:release")
def release_token():
    denied = _need_token()
    if denied:
        return denied
    state["token"] = None
    state["owner"] = None
    return _no_content()


@app.post("/api/system:reboot")
@app.post("/api/system:shutdown")
def reboot():
    return _no_content()


@app.get("/api/arm")
def arm():
    return jsonify({"model": "fr3", "serial": "SIM-0001"})


@app.get("/api/arm/joints")
def joints():
    return jsonify([{"joint": i, "brakeStatus": state["brakes"]} for i in range(1, 8)])


@app.get("/api/arm/warnings")
def warnings():
    return jsonify({"warnings": []})


@app.post("/api/arm/joints:unlock")
def unlock():
    denied = _need_token()
    if denied:
        return denied
    state["brakes"] = "Unlocked"
    return _no_content()


@app.post("/api/arm/joints:lock")
def lock():
    denied = _need_token()
    if denied:
        return denied
    state["brakes"] = "Locked"
    state["fci"] = "Inactive"
    return _no_content()


@app.get("/api/fci")
def fci():
    return jsonify({"status": state["fci"]})


@app.post("/api/fci:activate")
def fci_activate():
    denied = _need_token()
    if denied:
        return denied
    if state["mode"] != "Execution" or state["brakes"] != "Unlocked":
        return jsonify({"code": "FailedDependency", "message": "servono modalità Execution e giunti sbloccati"}), 424
    state["fci"] = "Active"
    return _no_content()


@app.post("/api/fci:deactivate")
def fci_deactivate():
    denied = _need_token()
    if denied:
        return denied
    state["fci"] = "Inactive"
    return _no_content()


@app.get("/api/safety/self-tests")
def self_tests():
    return jsonify({"selfTests": []})


@app.post("/api/safety/self-tests:execute")
def run_self_tests():
    return _no_content()


@app.get("/api/safety/recovery")
def recovery():
    return jsonify({"recovery": state["recovery"]})


@app.post("/api/safety/recovery:confirm")
def confirm_recovery():
    state["recovery"] = None
    return _no_content()


# ---- impostazioni del simulatore (non fanno parte della Desk API reale) ----
CONFIG_FILE = os.getenv("SIM_CONFIG_FILE", "/tmp/cobot_sim_config.json")


def _read_config():
    try:
        with open(CONFIG_FILE) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        value = os.getenv("SIM_CONTACT_Z")
        return {"contact_z": float(value) if value else None}


@app.get("/sim/contact")
def get_contact():
    return jsonify(_read_config())


@app.post("/sim/contact")
def set_contact():
    """Piano di contatto orizzontale a quota z (m, frame base); null = nessun contatto."""
    value = (request.get_json(silent=True) or {}).get("contact_z")
    if value is not None:
        try:
            value = float(value)
        except (TypeError, ValueError):
            return jsonify({"error": "contact_z deve essere un numero o null"}), 400
        if not -0.5 <= value <= 1.5:
            return jsonify({"error": "contact_z in metri nel frame base (tra -0.5 e 1.5): "
                                     f"{value} è fuori dal raggio d'azione del robot"}), 400
    with open(CONFIG_FILE, "w") as handle:
        json.dump({"contact_z": value}, handle)
    return jsonify({"contact_z": value})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("DESK_PORT", "8080")), threaded=True)
