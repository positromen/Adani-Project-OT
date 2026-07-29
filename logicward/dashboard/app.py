"""LogicWard SOC dashboard — Flask app (runs on the laptop).

Composes the whole laptop side: mounts the engine ingest/poll blueprint (so the
Pi agent can POST and the UI can poll), runs the drift engine on a background
loop, watches the signed baseline with FIM, wires the response engine, and serves
the role-gated SOC UI (live plant view, GitHub-style program diff, alert feed,
evidence + PDF).

Runs single-machine by default (an embedded plant), or against a real Pi when
LOGICWARD_EMBED_PLANT=0.

Run:  python -m logicward.dashboard.app
Logins:  operator/operator123 · engineer/engineer123 · soc/soc123
"""
from __future__ import annotations

import functools
import os
import threading

from flask import (Flask, Response, jsonify, redirect, render_template, request,
                   session, url_for)

from logicward import config
from logicward.agent.sensors.fim_watch import BaselineFileMonitor
from logicward.dashboard import evidence as evidence_mod
from logicward.engine import baseline as bl
from logicward.engine import l5x, l5x_diff
from logicward.engine.drift import DriftEngine
from logicward.engine.events import EventBus
from logicward.engine.response import ResponseEngine
from logicward.engine.server import api as engine_api
from logicward.engine.sources import EmbeddedPlant, RemotePlant

# ── demo-grade RBAC user directory ────────────────────────────────────────────
USERS = {
    "operator": {"password": "operator123", "role": "operator", "name": "Ops Console"},
    "engineer": {"password": "engineer123", "role": "engineer", "name": "Control Engineer"},
    "soc":      {"password": "soc123",      "role": "soc_analyst", "name": "SOC Analyst"},
}
ROLE_RANK = {"operator": 1, "engineer": 2, "soc_analyst": 3}


class Dashboard:
    """Holds the live objects the routes act on."""

    def __init__(self, embed: bool = True):
        self.bus = EventBus(evidence_path=config.EVIDENCE_PATH,
                            history_max=config.EVENT_HISTORY_MAX)
        if embed:
            self.plant = EmbeddedPlant().start()
        else:
            self.plant = RemotePlant(config.PI_HOST, config.MODBUS_PORT, config.PROGRAM_URL)

        # lock (or load) the baseline from the current approved program + registers
        self.baseline_path = config.BASELINE_MANIFEST_PATH
        self.signed = self._load_or_capture_baseline()
        self.baseline_prog = l5x.parse(self.signed["manifest"]["l5x"].encode())

        self.drift = DriftEngine(self.bus, self.signed,
                                 program_source=self.plant.program_source,
                                 register_source=self.plant.register_source)
        self.response = ResponseEngine(self.bus, restore_hook=self._restore_baseline_program)
        self.baseline_fim = BaselineFileMonitor(self.baseline_path, self.bus.emit)

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- baseline lifecycle --
    def _load_or_capture_baseline(self) -> dict:
        try:
            signed = bl.load(self.baseline_path)
            if bl.verify(signed):
                return signed
        except Exception:  # noqa: BLE001
            pass
        return self._capture_baseline()

    def _capture_baseline(self) -> dict:
        signed = bl.capture(self.plant.program_source(), self.plant.register_source())
        bl.save(signed, self.baseline_path)
        return signed

    def relock_baseline(self) -> dict:
        self.signed = self._capture_baseline()
        self.baseline_prog = l5x.parse(self.signed["manifest"]["l5x"].encode())
        self.drift = DriftEngine(self.bus, self.signed,
                                 program_source=self.plant.program_source,
                                 register_source=self.plant.register_source)
        return self.signed

    def _restore_baseline_program(self) -> bool:
        """Restore hook: re-download the approved program to the plant."""
        l5x_str = self.signed["manifest"]["l5x"]
        live = getattr(self.plant, "live_path", None)
        if live is not None:
            live.write_text(l5x_str, encoding="utf-8")
            return True
        
        prog_url = getattr(self.plant, "program_url", None)
        if prog_url:
            import requests
            try:
                requests.post(f"{prog_url}/download", json={"l5x": l5x_str}, timeout=5)
                return True
            except Exception:
                pass
        return False

    # -- background drift loop --
    def start(self) -> "Dashboard":
        self.baseline_fim.start()
        self._thread = threading.Thread(target=self._loop, name="lw-drift", daemon=True)
        self._thread.start()
        return self

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.drift.run_once()
            except Exception:  # noqa: BLE001
                pass
            self._stop.wait(config.POLL_INTERVAL_SEC)

    def stop(self) -> None:
        self._stop.set()
        self.baseline_fim.stop()
        if hasattr(self.plant, "stop"):
            self.plant.stop()

    # -- views' data --
    def overview(self) -> dict:
        events = self.bus.snapshot()
        counts = evidence_mod.summary(events)
        live = l5x.parse(self.plant.program_source())
        diff = l5x_diff.diff_programs(self.baseline_prog, live)
        return {
            "controller": self.signed["manifest"]["controller"],
            "baseline_hash": self.signed["manifest"]["structural_hash"],
            "baseline_integrity": "VALID" if bl.verify(self.signed) else "TAMPERED",
            "live_hash": diff["live_hash"],
            "program_in_sync": diff["changed"] == 0,
            "severity_counts": counts,
            "event_total": len(events),
            "critical_open": counts.get("critical", 0),
        }

    def diff(self) -> dict:
        live = l5x.parse(self.plant.program_source())
        return l5x_diff.diff_programs(self.baseline_prog, live)


# ── auth helpers ──────────────────────────────────────────────────────────────

def _current_role() -> str | None:
    u = session.get("user")
    return USERS[u]["role"] if u in USERS else None


def login_required(fn):
    @functools.wraps(fn)
    def wrap(*a, **k):
        if session.get("user") not in USERS:
            if request.path.startswith("/api/"):
                return jsonify({"error": "authentication required"}), 401
            return redirect(url_for("login"))
        return fn(*a, **k)
    return wrap


def role_required(min_role: str):
    def deco(fn):
        @functools.wraps(fn)
        def wrap(*a, **k):
            role = _current_role()
            if not role:
                return jsonify({"error": "authentication required"}), 401
            if ROLE_RANK.get(role, 0) < ROLE_RANK[min_role]:
                return jsonify({"error": f"requires role >= {min_role}"}), 403
            return fn(*a, **k)
        return wrap
    return deco


def create_app(dashboard: Dashboard | None = None, embed: bool | None = None) -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ.get("LOGICWARD_SECRET", "logicward-dev-secret")
    if embed is None:
        embed = os.environ.get("LOGICWARD_EMBED_PLANT", "1") != "0"
    dash = dashboard or Dashboard(embed=embed).start()

    # engine ingest/poll blueprint shares our bus + token
    app.config["LOGICWARD_BUS"] = dash.bus
    app.config["LOGICWARD_TOKEN"] = config.INGEST_TOKEN
    app.register_blueprint(engine_api)
    app.config["DASH"] = dash

    # -- auth --
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            u = request.form.get("username", "")
            p = request.form.get("password", "")
            if u in USERS and USERS[u]["password"] == p:
                session["user"] = u
                return redirect(url_for("dashboard_page"))
            return render_template("login.html", error="Invalid credentials"), 401
        return render_template("login.html", error=None)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    def index():
        return redirect(url_for("dashboard_page") if session.get("user") in USERS else url_for("login"))

    @app.route("/dashboard")
    @login_required
    def dashboard_page():
        u = session["user"]
        return render_template("dashboard.html", user=USERS[u]["name"], username=u,
                               role=USERS[u]["role"])

    # -- data APIs --
    @app.get("/api/overview")
    @login_required
    def api_overview():
        return jsonify(dash.overview())

    @app.get("/api/plant")
    @login_required
    def api_plant():
        return jsonify(dash.plant.named_snapshot())

    @app.get("/api/diff")
    @login_required
    def api_diff():
        return jsonify(dash.diff())

    @app.get("/api/evidence")
    @login_required
    def api_evidence():
        sev = request.args.get("severity")
        return jsonify({"events": evidence_mod.query(dash.bus.snapshot(), severity=sev, limit=300)})

    @app.post("/api/alerts/clear")
    def api_alerts_clear():
        dash.bus.clear()
        return jsonify({"status": "cleared", "message": "All alerts have been cleared from memory and disk."})

    @app.get("/api/evidence/report.pdf")
    @role_required("soc_analyst")
    def api_report():
        events = dash.bus.snapshot()
        meta = {"controller": dash.signed["manifest"]["controller"],
                "baseline_hash": dash.signed["manifest"]["structural_hash"],
                "baseline_integrity": "VALID" if bl.verify(dash.signed) else "TAMPERED"}
        pdf = evidence_mod.build_pdf(events, meta)
        return Response(pdf, mimetype="application/pdf",
                        headers={"Content-Disposition": "attachment; filename=logicward_forensic_report.pdf"})

    # -- actions (role-gated) --
    @app.post("/api/baseline/lock")
    @role_required("engineer")
    def api_lock():
        dash.relock_baseline()
        dash.bus.emit_new("response.restore_baseline", "dashboard",
                          {"reason": f"Baseline re-locked by {session['user']}", "performed": True},
                          identity={"who": session["user"], "channel": "operator"})
        return jsonify({"status": "locked", "hash": dash.signed["manifest"]["structural_hash"]})

    @app.post("/api/response/ack")
    @login_required
    def api_ack():
        d = request.get_json(silent=True) or {}
        ev = dash.response.operator_ack(d.get("ref", ""), actor=session["user"], note=d.get("note"))
        return jsonify(ev)

    @app.post("/api/response/quarantine")
    @role_required("soc_analyst")
    def api_quarantine():
        d = request.get_json(silent=True) or {}
        ev = dash.response.quarantine_device(d.get("mac", "?"), d.get("ip"), actor=session["user"],
                                             ref=d.get("ref"))
        return jsonify(ev)

    @app.post("/api/response/safe_state")
    @role_required("soc_analyst")
    def api_safe_state():
        d = request.get_json(silent=True) or {}
        ev = dash.response.recommend_safe_state(d.get("rung_id"), actor=session["user"], ref=d.get("ref"))
        return jsonify(ev)

    @app.post("/api/response/restore")
    @role_required("engineer")
    def api_restore():
        d = request.get_json(silent=True) or {}
        ev = dash.response.restore_baseline(actor=session["user"], ref=d.get("ref"))
        return jsonify(ev)

    return app


def main() -> None:
    app = create_app()
    print("LogicWard SOC dashboard")
    print(f"  http://0.0.0.0:{config.INGEST_PORT}/   (login: soc/soc123)")
    app.run(host=config.INGEST_HOST, port=config.INGEST_PORT, threaded=True)


if __name__ == "__main__":
    main()
