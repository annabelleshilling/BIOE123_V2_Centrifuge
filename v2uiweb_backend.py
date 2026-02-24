"""
Centrifuge Control System - Flask Backend
Run with: python app.py
Then open http://localhost:5000 in your browser.
"""

from flask import Flask, jsonify, request, render_template_string
import threading
import time
import json
from pathlib import Path

# Import your existing serial controller
try:
    from serial_controller import SerialController, SystemState, ArduinoStatus
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False
    print("Warning: serial_controller.py not found. Running in demo mode.")

app = Flask(__name__)

# ==================== SHARED STATE ====================
# This dict is written by the serial thread and read by Flask routes.
# Using a lock to keep it thread-safe.

state_lock = threading.Lock()
shared_state = {
    "state": "DISCONNECTED",
    "current_rpm": 0,
    "target_rpm": 0,
    "pwm": 0,
    "lid_closed": False,
    "level": False,
    "running": False,
    "remaining_ms": 0,
    "error_reason": "",
    "last_updated": 0,
    "connected": False,
}

# ==================== SERIAL CONTROLLER SETUP ====================
controller = None

def on_status(status):
    with state_lock:
        shared_state.update({
            "state": status.state.value,
            "current_rpm": status.current_rpm,
            "target_rpm": status.target_rpm,
            "pwm": status.pwm,
            "lid_closed": status.lid_closed,
            "level": status.level,
            "running": status.running,
            "remaining_ms": status.remaining_ms,
            "error_reason": status.error_reason,
            "last_updated": status.last_updated,
            "connected": True,
        })

def on_error(reason):
    with state_lock:
        shared_state["state"] = "ERROR"
        shared_state["error_reason"] = reason
        if reason == "SERIAL_DISCONNECTED":
            shared_state["connected"] = False

def on_complete():
    with state_lock:
        shared_state["state"] = "IDLE"
        shared_state["running"] = False

def init_controller():
    global controller
    if not SERIAL_AVAILABLE:
        return False
    controller = SerialController(
        auto_detect=True,
        on_status_update=on_status,
        on_error=on_error,
        on_complete=on_complete,
    )
    connected = controller.connect()
    with state_lock:
        shared_state["connected"] = connected
    return connected

# ==================== ROUTES ====================
@app.route("/")
def index():
    return render_template_string(open("v2ui_cute_frontend.html", encoding="utf-8").read())

@app.route("/api/status")
def get_status():
    with state_lock:
        return jsonify(dict(shared_state))

@app.route("/api/start", methods=["POST"])
def start():
    data = request.json
    rpm = int(data.get("rpm", 0))
    duration_sec = int(data.get("duration_sec", 0))

    if rpm <= 0 or rpm > 3000:
        return jsonify({"ok": False, "error": "RPM must be between 1 and 3000"}), 400
    if duration_sec <= 0 or duration_sec > 600:
        return jsonify({"ok": False, "error": "Duration must be between 1 and 600 seconds"}), 400

    if controller and shared_state["connected"]:
        ok = controller.start(rpm, duration_sec)
    else:
        # Demo mode: simulate state change
        with state_lock:
            shared_state.update({
                "state": "RAMPING_UP",
                "target_rpm": rpm,
                "running": True,
            })
        ok = True

    return jsonify({"ok": ok})

@app.route("/api/stop", methods=["POST"])
def stop():
    if controller and shared_state["connected"]:
        ok = controller.stop()
    else:
        with state_lock:
            shared_state.update({"state": "RAMPING_DOWN"})
        ok = True
    return jsonify({"ok": ok})

@app.route("/api/emergency_stop", methods=["POST"])
def emergency_stop():
    if controller and shared_state["connected"]:
        ok = controller.emergency_stop()
    else:
        with state_lock:
            shared_state.update({"state": "ERROR", "running": False, "current_rpm": 0})
        ok = True
    return jsonify({"ok": ok})

@app.route("/api/clear_error", methods=["POST"])
def clear_error():
    if controller and shared_state["connected"]:
        ok = controller.clear_error()
    else:
        with state_lock:
            shared_state.update({"state": "IDLE", "error_reason": ""})
        ok = True
    return jsonify({"ok": ok})

@app.route("/api/connect", methods=["POST"])
def reconnect():
    data = request.json or {}
    port = data.get("port")
    if controller:
        if port:
            controller.port = port
        ok = controller.connect()
        with state_lock:
            shared_state["connected"] = ok
        return jsonify({"ok": ok})
    return jsonify({"ok": False, "error": "Controller not initialized"})

@app.route("/api/ports")
def list_ports():
    if SERIAL_AVAILABLE:
        ports = SerialController.list_ports()
    else:
        ports = []
    return jsonify({"ports": ports})

# ==================== MAIN ====================
if __name__ == "__main__":
    print("Initializing serial connection...")
    init_controller()
    print("Starting web server at http://localhost:5000")
    app.run(debug=False, host="0.0.0.0", port=5000, threaded=True)