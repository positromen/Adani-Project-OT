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

from logicward import config
from logicward.attacker.attacks import Attacker
from logicward.sites.grfics.attacks import ATTACKS as CHEM_ATTACK_METHODS
from logicward.sites.grfics.attacks import ChemAttacker

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
        "severity": "critical",
        "mitre": "T0814 — Denial of Service",
        "description": "Flood the PLC Modbus server with rapid-fire FC03 read requests, saturating the network and spiking the CPU. Use the slider to set intensity.",
        "icon": "🌊",
    },
]

# Site B — GRFICS chemical reactor (3D). Real FC05/FC06 writes to the chemical
# PLC's Modbus server; each has a visible consequence on the Unity 3D scene and
# trips LogicWard's chemical register-drift detector.
CHEM_CATALOGUE = [
    {
        "id": "pressure-redline",
        "name": "Pressure Redline (Combo)",
        "category": "Modbus",
        "severity": "critical",
        "mitre": "T0836 — Modify Parameter",
        "description": "First raises the reactor's high-pressure trip setpoint to defeat the safety interlock, then forces the feed valves open. Watch the pressure gauge fly off the chart!",
        "icon": "💥",
    },
    {
        "id": "overfill",
        "name": "Tank Overfill",
        "category": "Modbus",
        "severity": "high",
        "mitre": "T0855 — Unauthorized Command",
        "description": "Shut the product valve and drive the feeds high. Liquid level rises until the reactor vessel overflows.",
        "icon": "🌊",
    },
    {
        "id": "estop-injection",
        "name": "E-Stop Injection",
        "category": "Modbus",
        "severity": "critical",
        "mitre": "T0855 — Unauthorized Command",
        "description": "Force the emergency-shutdown coil. The plant slams to safe-state — a denial of control the operator never commanded.",
        "icon": "🛑",
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
        "id": "reset-chem",
        "name": "Reset Chemical Plant",
        "description": "Restore Site B (Chemical Reactor) to equilibrium state.",
        "icon": "♻️",
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
    {
        "id": "clear-alerts",
        "name": "Clear SOC Alerts",
        "description": "Delete evidence.jsonl on your laptop so the SOC dashboard shows zero alerts.",
        "icon": "🗑️",
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
               program_port: int = 8081, chem_host: str = "127.0.0.1",
               chem_port: int | None = None) -> Flask:
    app = Flask(__name__,
                template_folder=os.path.join(os.path.dirname(__file__), "templates"),
                static_folder=os.path.join(os.path.dirname(__file__), "static"))
    app.secret_key = "attacker-dashboard-key"

    atk = Attacker(host, modbus_port=modbus_port,
                   program_base=f"http://{host}:{program_port}")
    chem_port = chem_port or config.GRFICS_MODBUS_PORT
    chem = ChemAttacker(host=chem_host, port=chem_port)

    @app.route("/")
    def index():
        return render_template("attacker.html",
                               attacks=ATTACK_CATALOGUE,
                               chem_attacks=CHEM_CATALOGUE,
                               utilities=UTILITY_ACTIONS,
                               target_host=host,
                               modbus_port=modbus_port,
                               program_port=program_port,
                               chem_host=chem_host,
                               chem_port=chem_port)

    @app.post("/api/attack")
    def run_attack():
        data = request.get_json(silent=True) or {}
        attack_id = data.get("id", "")
        try:
            # -- Site B: chemical reactor (real Modbus writes to the 3D plant) --
            if attack_id in CHEM_ATTACK_METHODS:
                r = getattr(chem, CHEM_ATTACK_METHODS[attack_id])()
                return jsonify({"status": "success" if r.get("ok") else "failed",
                                "detail": r.get("note", attack_id)})

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
                count = int(data.get("count", 50000))
                rate = atk.ddos(count)
                return jsonify({"status": "success",
                                "detail": f"{count:,} req flood complete — {rate:.0f} req/s"})

            else:
                return jsonify({"status": "error", "detail": f"Unknown attack: {attack_id}"}), 400

        except Exception as exc:
            return jsonify({"status": "error",
                            "detail": f"{type(exc).__name__}: {exc}"}), 500

    @app.post("/api/utility")
    def run_utility():
        data = request.get_json(silent=True) or {}
        action_id = data.get("id", "")
        import time
        try:
            if action_id == "clear-alerts":
                import requests
                try:
                    res = requests.post("http://127.0.0.1:8080/api/alerts/clear", timeout=3)
                    if res.status_code == 200:
                        return jsonify({"status": "success", "detail": "Alerts cleared from SOC memory and disk. Refresh SOC dashboard (F5)."})
                    else:
                        return jsonify({"status": "error", "detail": f"SOC dashboard returned {res.status_code}"})
                except Exception as e:
                    return jsonify({"status": "error", "detail": f"Failed to contact SOC dashboard: {e}"})

            elif action_id == "reset-chem":
                import requests
                try:
                    res = requests.post("http://127.0.0.1:8080/api/site-b/reset", timeout=3)
                    if res.status_code == 200:
                        return jsonify({"status": "success", "detail": "Chemical plant reset to equilibrium!"})
                    else:
                        return jsonify({"status": "error", "detail": f"SOC dashboard returned {res.status_code}"})
                except Exception as e:
                    return jsonify({"status": "error", "detail": f"Failed to reset chemical plant: {e}"})

            elif action_id == "clean-pi":
                out = _run_ssh_command(host, [
                    "cd ~/Adani-Project-OT/logicward/plant/program && cp ThermalPlant_baseline.L5X live.L5X",
                    "cd ~/Adani-Project-OT/logicward/plant/program && sha256sum ThermalPlant_baseline.L5X live.L5X",
                ])
                return jsonify({"status": "success", "detail": out})

            elif action_id == "restart-pi":
                password = os.environ.get("PI_PASSWORD", "123456789")
                out_parts = []
                out_parts.append(_run_ssh_command(host, [
                    f"echo '{password}' | sudo -S pkill -f 'python -m logicward' || true",
                ]))
                time.sleep(2)
                out_parts.append(_run_ssh_command(host, [
                    f"cd ~/Adani-Project-OT && nohup bash -c 'echo {password} | sudo -S env PATH=$PATH SUDO_AGENT=1 bash deploy/run_pi.sh' > deploy/nohup.log 2>&1 &",
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
            return jsonify({"status": "error", "detail": f"{type(exc).__name__}: {exc}"}), 500

    return app


def main() -> None:
    p = argparse.ArgumentParser(description="LogicWard Attacker Dashboard")
    p.add_argument("--host", default="10.119.190.53", help="Pi IP address")
    p.add_argument("--port", type=int, default=9090, help="Dashboard port")
    p.add_argument("--modbus-port", type=int, default=5020)
    p.add_argument("--program-port", type=int, default=8081)
    p.add_argument("--chem-host", default="127.0.0.1",
                   help="Chemical (GRFICS) Modbus host — where the SOC dashboard's Site B runs")
    p.add_argument("--chem-port", type=int, default=config.GRFICS_MODBUS_PORT)
    args = p.parse_args()

    app = create_app(args.host, args.modbus_port, args.program_port,
                     chem_host=args.chem_host, chem_port=args.chem_port)
    print(f"\n  [*] LogicWard ATTACKER CONSOLE")
    print(f"  Thermal (Pi) : {args.host}  (Modbus :{args.modbus_port}, Program :{args.program_port})")
    print(f"  Chemical (3D): {args.chem_host}:{args.chem_port}")
    print(f"  Console      : http://localhost:{args.port}/")
    print()
    app.run(host="0.0.0.0", port=args.port, threaded=True)


if __name__ == "__main__":
    main()
