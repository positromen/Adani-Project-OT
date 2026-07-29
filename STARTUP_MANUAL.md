# LogicWard Demo - Manual Startup Guide

If the IP address of the Raspberry Pi changes (e.g., when the Mobile Hotspot restarts), follow these manual steps to start the demo.

### Prerequisites
1. Turn on your Mobile Hotspot.
2. Plug in the Raspberry Pi and wait ~60 seconds for it to boot.
3. Find the Pi's new IP address in your Mobile Hotspot settings (e.g., `192.168.137.129`).
4. Note your laptop's IP address on the hotspot network (usually `192.168.137.1`).

### Step 1: Bootstrap the Pi (Terminal 1)
Run this command to cleanly restart the Pi services and point it to your laptop's new IP:
```powershell
python deploy/pi_tools/bootstrap_pi.py --pi-ip <PI_IP> --laptop-ip <LAPTOP_IP>
```
*Example: `python deploy/pi_tools/bootstrap_pi.py --pi-ip 192.168.137.129 --laptop-ip 192.168.137.1`*

### Step 2: Start the SOC Dashboard (Terminal 1)
Once the Pi is bootstrapped, start the SOC dashboard:
```powershell
.\deploy\run_laptop.ps1 -PiHost <PI_IP>
```
*Example: `.\deploy\run_laptop.ps1 -PiHost 192.168.137.129`*

### Step 3: Start the Attacker Console (Terminal 2)
Open a new terminal and start the Red Team console:
```powershell
python -m logicward.attacker.dashboard --host <PI_IP>
```
*Example: `python -m logicward.attacker.dashboard --host 192.168.137.129`*
