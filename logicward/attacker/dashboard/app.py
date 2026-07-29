"""LogicWard Attacker Dashboard — standalone red-team console.

A completely independent web UI for launching cyber attacks against the
Raspberry Pi PLC during demonstrations.  Runs on its own port (default 9090)
and does NOT share any code paths with the SOC dashboard.

    python -m logicward.attacker_dashboard --host 10.119.190.53
    python -m logicward.attacker_dashboard --host 10.119.190.53 --port 9090

Open http://localhost:9090 to access the attacker console.
"""
from __future__ import annotations

import argparse
import json
import os
import traceback

from flask import Flask, Response, jsonify, render_template, request

from logicward.attacker.attacks import Attacker

# ---------------------------------------------------------------------------

ATTACK_CATALOGUE = [
    {
        "id": "setpoint-drift",
        "name": "Setpoint Drift",
        "category": "Modbus",
        "severity": "high",
        "mitre": "T0836 — Modify Parameter",
        "description": "Silently change the Drum Level Low-Low trip setpoint from 220 mm to 40 mm over Modbus. The boiler protection is now blind to a dangerously low drum level.",
        "icon": "📉",
    },
    {
        "id": "logic-inversion",
        "name": "Logic Inversion",
        "category": "Program Download",
        "severity": "critical",
        "mitre": "T0889 — Modify Program",
        "description": "Invert the drum-level trip comparator (LES → GRT). The safety interlock now trips when the drum is FULL instead of EMPTY — exactly backwards.",
        "icon": "🔄",
    },
    {
        "id": "condition-stripping",
        "name": "Condition Stripping",
        "category": "Program Download",
        "severity": "critical",
        "mitre": "T0889 — Modify Program",
        "description": "Strip the Plant_Running interlock from the furnace flame-trip rung. The fuel trip can now fire even when the plant is offline, causing an unnecessary shutdown.",
        "icon": "✂️",
    },
    {
        "id": "coil-hijack",
        "name": "Coil Hijack",
        "category": "Program Download",
        "severity": "critical",
        "mitre": "T0889 — Modify Program",
        "description": "Redirect the Feedwater_Trip output coil to Cooling_Pump_Stop. A drum emergency now kills cooling instead of feedwater — catastrophic mismatch.",
        "icon": "🎯",
    },
    {
        "id": "rung-injection",
        "name": "Rung Injection",
        "category": "Program Download",
        "severity": "critical",
        "mitre": "T0843 — Program Download",
        "description": "Inject a hidden backdoor rung (Rung 6) that unlatches the turbine overspeed trip when the attacker's coil is set. Invisible to operators.",
        "icon": "💉",
    },
    {
        "id": "force-coil",
        "name": "Force Coil",
        "category": "Modbus",
        "severity": "high",
        "mitre": "T0855 — Unauthorized Command",
        "description": "Force the Fuel_Valve_Open coil to OFF over Modbus, cutting fuel to the boiler. The plant trips on flame loss.",
        "icon": "⚡",
    },
    {
        "id": "ddos",
        "name": "DDoS Flood",
        "category": "Modbus",
        "severity": "medium",
        "mitre": "T0814 — Denial of Service",
        "description": "Flood the PLC Modbus server with 500 rapid-fire FC03 read requests, saturating the control network and spiking CPU.",
        "icon": "🌊",
    },
]

UTILITY_ACTIONS = [
    {
        "id": "clean-pi",
        "name": "Reset to Baseline",
        "description": "Overwrite live.L5X with the clean ThermalPlant_baseline.L5X on the Pi.",
        "icon": "🧹",
    },
    {
        "id": "restart-pi",
        "name": "Restart Pi Services",
        "description": "Kill all LogicWard processes on the Pi and restart run_pi.sh.",
        "icon": "🔄",
    },
    {
        "id": "verify-pi",
        "name": "Verify Pi State",
        "description": "SSH into the Pi and check if baseline/live hashes match and services are running.",
        "icon": "🔍",
    },
]

# ---------------------------------------------------------------------------

def _run_ssh_command(host: str, commands: list[str]) -> str:
    """Run commands on Pi over SSH. Returns combined stdout."""
    try:
        import paramiko
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        password = os.environ.get("PI_PASSWORD", "123456789")
        username = os.environ.get("PI_USERNAME", "siddhesh")
        client.connect(host, username=username, password=password, timeout=10)
        output_lines = []
        for cmd in commands:
            _, stdout, stderr = client.exec_command(cmd)
            out = stdout.read().decode()
            err = stderr.read().decode()
            if out:
                output_lines.append(out)
            if err:
                output_lines.append(f"[stderr] {err}")
        client.close()
        return "\n".join(output_lines)
    except Exception as exc:
        return f"SSH error: {exc}"


def create_app(host: str = "127.0.0.1", modbus_port: int = 5020,
               program_port: int = 8081) -> Flask:
    app = Flask(__name__,
                template_folder=os.path.join(os.path.dirname(__file__), "templates"),
                static_folder=os.path.join(os.path.dirname(__file__), "static"))
    app.secret_key = "attacker-dashboard-key"

    atk = Attacker(host, modbus_port=modbus_port,
                   program_base=f"http://{host}:{program_port}")

    @app.route("/")
    def index():
        return render_template("attacker.html",
                               attacks=ATTACK_CATALOGUE,
                               utilities=UTILITY_ACTIONS,
                               target_host=host,
                               modbus_port=modbus_port,
                               program_port=program_port)

    @app.post("/api/attack")
    def run_attack():
        data = request.get_json(silent=True) or {}
        attack_id = data.get("id", "")
        try:
            if attack_id == "setpoint-drift":
                ok = atk.setpoint_drift_modbus("Drum_Level_LL_SP", 40)
                return jsonify({"status": "success" if ok else "failed",
                                "detail": "Drum_Level_LL_SP → 40 mm"})

            elif attack_id in ("logic-inversion", "condition-stripping",
                               "coil-hijack", "rung-injection"):
                result = atk.program_mutation(attack_id)
                return jsonify({"status": "success", "detail": json.dumps(result)})

            elif attack_id == "force-coil":
                ok = atk.force_coil("Fuel_Valve_Open", False)
                return jsonify({"status": "success" if ok else "failed",
                                "detail": "Fuel_Valve_Open → OFF"})

            elif attack_id == "ddos":
                rate = atk.ddos(500)
                return jsonify({"status": "success",
                                "detail": f"Flood complete — {rate:.0f} req/s"})

            else:
                return jsonify({"status": "error", "detail": f"Unknown attack: {attack_id}"}), 400

        except Exception as exc:
            return jsonify({"status": "error",
                            "detail": f"{type(exc).__name__}: {exc}"}), 500

    @app.post("/api/utility")
    def run_utility():
        data = request.get_json(silent=True) or {}
        action_id = data.get("id", "")
        try:
            if action_id == "clean-pi":
                out = _run_ssh_command(host, [
                    "cd ~/Adani-Project-OT/logicward/plant/program && cp ThermalPlant_baseline.L5X live.L5X",
                    "cd ~/Adani-Project-OT/logicward/plant/program && sha256sum ThermalPlant_baseline.L5X live.L5X",
                ])
                return jsonify({"status": "success", "detail": out})

            elif action_id == "restart-pi":
                import time
                out_parts = []
                out_parts.append(_run_ssh_command(host, [
                    "sudo pkill -f 'python -m logicward' || true",
                ]))
                time.sleep(2)
                out_parts.append(_run_ssh_command(host, [
                    "cd ~/Adani-Project-OT && nohup bash -c 'SUDO_AGENT=1 bash deploy/run_pi.sh' > deploy/nohup.log 2>&1 &",
                ]))
                time.sleep(3)
                out_parts.append(_run_ssh_command(host, [
                    "pgrep -af 'python -m logicward'",
                ]))
                return jsonify({"status": "success", "detail": "\n".join(out_parts)})

            elif action_id == "verify-pi":
                out = _run_ssh_command(host, [
                    "cd ~/Adani-Project-OT/logicward/plant/program && sha256sum ThermalPlant_baseline.L5X live.L5X",
                    "pgrep -af 'python -m logicward'",
                ])
                return jsonify({"status": "success", "detail": out})

            else:
                return jsonify({"status": "error", "detail": f"Unknown action: {action_id}"}), 400

        except Exception as exc:
            return jsonify({"status": "error",
                            "detail": f"{type(exc).__name__}: {exc}"}), 500

    return app


def main() -> None:
    p = argparse.ArgumentParser(description="LogicWard Attacker Dashboard")
    p.add_argument("--host", default="10.119.190.53", help="Pi IP address")
    p.add_argument("--port", type=int, default=9090, help="Dashboard port")
    p.add_argument("--modbus-port", type=int, default=5020)
    p.add_argument("--program-port", type=int, default=8081)
    args = p.parse_args()

    app = create_app(args.host, args.modbus_port, args.program_port)
    print(f"\n  [*] LogicWard ATTACKER CONSOLE")
    print(f"  Target  : {args.host}  (Modbus :{args.modbus_port}, Program :{args.program_port})")
    print(f"  Console : http://localhost:{args.port}/")
    print()
    app.run(host="0.0.0.0", port=args.port, threaded=True)


if __name__ == "__main__":
    main()
