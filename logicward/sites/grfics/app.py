"""LogicWard Site B - GRFICS Chemical Reactor demo dashboard.

One Flask app that runs the whole Site-B demo:

  * ChemicalDataStore + reactive physics (drives the real GRFICS Unity 3D scene),
  * LogicWard raw-socket Modbus TCP server over that datastore (attack surface),
  * ChemicalDriftDetector on a 1 s loop feeding a real LogicWard EventBus
    (severity + MITRE-for-ICS + evidence log),
  * the 3D scene embedded in an iframe next to a live alert feed, process gauges,
    and one-click attacks - so an attack visibly hits the plant AND lands in the
    detection feed on the same screen.

Run:  python -m logicward.sites.grfics.app
Open: http://127.0.0.1:8095/
"""
from __future__ import annotations

import threading
import time

from flask import (Flask, Response, jsonify, render_template,
                   send_from_directory)

from logicward import config
from logicward.engine.events import EventBus
from logicward.plant.modbus_server import ModbusTCPServer
from logicward.sites.grfics import SITE_ID, SITE_NAME
from logicward.sites.grfics import points as pts
from logicward.sites.grfics.attacks import ChemAttacker
from logicward.sites.grfics.datastore import ChemicalDataStore
from logicward.sites.grfics.detector import ChemicalDriftDetector


class SiteB:
    """Owns the live objects for the chemical site."""

    def __init__(self, modbus_port: int | None = None):
        self.bus = EventBus(evidence_path=config.DATA_DIR / "grfics_evidence.jsonl",
                            history_max=config.EVENT_HISTORY_MAX)
        self.ds = ChemicalDataStore().start(hz=10.0)
        self.server = ModbusTCPServer(host="127.0.0.1",
                                      port=modbus_port or config.GRFICS_MODBUS_PORT,
                                      datastore=self.ds)
        self.server.start(background=True)
        self.modbus_port = self.server.port
        self.detector = ChemicalDriftDetector(self.bus, self.ds.register_source)
        self.attacker = ChemAttacker(host="127.0.0.1", port=self.modbus_port)
        self._stop = threading.Event()
        threading.Thread(target=self._loop, name="grfics-detect", daemon=True).start()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.detector.run_once()
            except Exception:  # noqa: BLE001
                pass
            self._stop.wait(config.POLL_INTERVAL_SEC)

    def reset(self):
        """Restore the plant to its baseline and clear detector memory."""
        self.ds.stop()
        self.ds = ChemicalDataStore().start(hz=10.0)
        self.server.ds = self.ds
        self.server.handler.ds = self.ds
        self.detector.register_source = self.ds.register_source
        self.attacker = ChemAttacker(host="127.0.0.1", port=self.modbus_port)
        self.detector.relock()


def create_app(site: SiteB | None = None) -> Flask:
    app = Flask(__name__)
    site = site or SiteB()
    app.config["SITE"] = site

    build_dir = config.GRFICS_BUILD_DIR

    # -- dashboard --
    @app.route("/")
    def index():
        return render_template("grfics.html", site_name=SITE_NAME, site_id=SITE_ID,
                               modbus_port=site.modbus_port)

    # -- the Unity 3D scene (minimal host page + build assets) --
    @app.route("/viz/")
    def viz():
        return render_template("viz.html")

    @app.route("/viz/Build/<path:fname>")
    def viz_build(fname):
        return send_from_directory(build_dir / "Build", fname)

    @app.route("/viz/TemplateData/<path:fname>")
    def viz_template(fname):
        return send_from_directory(build_dir / "TemplateData", fname)

    # -- the process feed the Unity scene reads (exact GRFICS schema) --
    @app.route("/data/index.php", methods=["GET", "POST"])
    def data_feed():
        return jsonify(site.ds.feed_json())

    @app.route("/versions.php")
    @app.route("/version.php")
    def versions():
        return jsonify({"version": "logicward-site-b", "created": "local"})

    # -- APIs the dashboard polls --
    @app.get("/api/state")
    def api_state():
        return jsonify({"feed": site.ds.feed_json(),
                        "snapshot": site.ds.named_snapshot()})

    @app.get("/api/events")
    def api_events():
        from flask import request
        since = request.args.get("since", default=0, type=int)
        evs, cursor = site.bus.get_since(since)
        return jsonify({"events": evs, "cursor": cursor})

    @app.get("/api/points")
    def api_points():
        return jsonify({
            "holding": [{"tag": p.tag, "unit": p.unit} for p in pts.HOLDING_REGISTERS],
            "coils": [{"tag": p.tag} for p in pts.COILS if p.tag not in pts.PLANT_DRIVEN_COILS],
        })

    # -- actions --
    @app.post("/api/attack/<name>")
    def api_attack(name):
        fn = {
            "defeat-protection": site.attacker.defeat_protection,
            "valve-override": site.attacker.valve_override,
            "overfill": site.attacker.overfill,
            "estop-injection": site.attacker.estop_injection,
            "pump-kill": site.attacker.pump_kill,
        }.get(name)
        if not fn:
            return jsonify({"error": f"unknown attack {name}"}), 404
        return jsonify(fn())

    @app.post("/api/reset")
    def api_reset():
        site.reset()
        return jsonify({"status": "reset", "note": "Plant restored to approved baseline"})

    return app


def main() -> None:
    app = create_app()
    site = app.config["SITE"]
    print("=" * 60)
    print("LogicWard Site B - GRFICS Chemical Reactor")
    print(f"  dashboard : http://127.0.0.1:{config.GRFICS_DASH_PORT}/")
    print(f"  3D scene  : http://127.0.0.1:{config.GRFICS_DASH_PORT}/viz/")
    print(f"  Modbus    : 127.0.0.1:{site.modbus_port}  (unauthenticated)")
    print("=" * 60)
    app.run(host="127.0.0.1", port=config.GRFICS_DASH_PORT, threaded=True)


if __name__ == "__main__":
    main()
