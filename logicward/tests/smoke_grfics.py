"""Smoke suite for Site B — GRFICS chemical reactor (3D demo).

Exercises the real pipeline: physics stability at rest, real Modbus attacks
over the LogicWard raw-socket server, register-drift detection onto the shared
bus (types + severity + MITRE + site tag), the Unity feed schema, and reset.

Run:  python -m logicward.tests.smoke_grfics
"""
from __future__ import annotations

import sys
import time

from logicward.sites.grfics import SITE_ID
from logicward.sites.grfics.app import SiteB

_passed = 0
_failed = 0


def check(desc: str, cond: bool) -> None:
    global _passed, _failed
    if cond:
        _passed += 1
    else:
        _failed += 1
        print(f"  FAIL: {desc}")


def _press(site):
    return site.ds.feed_json()["outputs"]["pressure"]


def _drain(site):
    # advance the detector so emitted events are up to date
    site.detector.run_once()


def main() -> int:
    site = SiteB(modbus_port=5041)
    time.sleep(0.5)

    # -- 1. feed schema matches what the Unity build reads --
    feed = site.ds.feed_json()
    for k in ("f1_flow", "purge_flow", "pressure", "liquid_level", "A_in_purge"):
        check(f"feed.outputs has {k}", k in feed["outputs"])
    for k in ("f1_valve_pos", "purge_valve_pos", "e_stop"):
        check(f"feed.state has {k}", k in feed["state"])

    # -- 2. stable at rest: no drift, no trip over a couple of seconds --
    p0 = _press(site)
    time.sleep(2.0)
    p1 = _press(site)
    check("pressure stable at rest (~1800)", 1500 < p1 < 2100)
    check("no false trip at rest", site.ds.feed_json()["state"]["e_stop"] == 0)
    _drain(site)
    evs, cur = site.bus.get_since(0)
    check("no drift events at rest", len(evs) == 0)

    # -- 3. defeat-protection => high-severity safety setpoint drift --
    r = site.attacker.defeat_protection()
    check("defeat-protection write ok", r["ok"])
    time.sleep(0.3)
    _drain(site)
    evs, cur = site.bus.get_since(0)
    sp = [e for e in evs if e["type"] == "cyber.setpoint_drift"]
    check("setpoint_drift emitted", len(sp) == 1)
    check("setpoint_drift is high severity", sp and sp[0]["severity"] == "high")
    check("setpoint_drift tagged site", sp and sp[0]["details"].get("site") == SITE_ID)
    check("setpoint_drift has MITRE ICS id", sp and sp[0]["mitre"].get("technique_id"))

    # -- 4. valve-override => register_change events + pressure climbs past 3000 --
    before = _press(site)
    site.attacker.valve_override()
    time.sleep(0.3)
    _drain(site)
    evs, cur = site.bus.get_since(0)
    rc = [e for e in evs if e["type"] == "cyber.register_change"]
    check("valve register_change events emitted", len(rc) >= 3)
    check("register_change tagged site", all(e["details"].get("site") == SITE_ID for e in rc))
    # let physics run — with protection defeated it should exceed 3000 without tripping
    deadline = time.time() + 25
    peaked = False
    while time.time() < deadline:
        if _press(site) > 3000:
            peaked = True
            break
        time.sleep(0.5)
    check("pressure driven past 3000 kPa (protection defeated)", peaked)
    check("no auto-trip while protection defeated", site.ds.feed_json()["state"]["e_stop"] == 0)
    check("pressure actually rose under attack", _press(site) > before + 200)

    # -- 5. estop-injection => ESD coil forced, plant to safe-state --
    n_before = len(site.bus.get_since(0)[0])
    site.attacker.estop_injection()
    time.sleep(0.3)
    _drain(site)
    evs, cur = site.bus.get_since(0)
    esd_ev = [e for e in evs if e["details"].get("coil") == "Reactor_ESD"]
    check("ESD coil-force detected", len(esd_ev) == 1)
    check("ESD reflected in feed", site.ds.feed_json()["state"]["e_stop"] == 1)

    # -- 6. reset restores baseline and clears detector memory --
    site.reset()
    time.sleep(1.0)
    check("reset restores pressure", 1500 < _press(site) < 2100)
    check("reset clears ESD", site.ds.feed_json()["state"]["e_stop"] == 0)
    site.detector.run_once()
    # a fresh attack after reset must still detect (dedup memory cleared)
    site.attacker.defeat_protection()
    time.sleep(0.3)
    site.detector.run_once()
    post = [e for e in site.bus.get_since(cur)[0] if e["type"] == "cyber.setpoint_drift"]
    check("detection works after reset", len(post) >= 1)

    total = _passed + _failed
    print("=" * 52)
    print(f"RESULT: {_passed}/{total} checks passed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
