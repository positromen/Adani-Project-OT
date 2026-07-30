# Adani Project - GRFICS 3D Simulation Limitations & Recompile Plan

## The Core Problem
The Modbus physics backend and the HTML SOC Dashboard are operating perfectly in sync. However, the pre-compiled Unity WebGL binary (`ChemicalPlant.json`) is not animating the physical consequences of our attacks. It remains visually static or completely ignores the telemetry data provided to it by the Python backend.

## Limitations by Attack Type
Our attack console features 3 highly polished attacks, but the 3D simulation fails to visualize them properly:

1. **Tank Overfill Attack**
   - *Expected:* The purple liquid level visibly rises until the reactor tank physically overflows onto the floor.
   - *Current Bug:* The liquid level is visually frozen at ~40% fill, even when the backend correctly calculates and sends 99.9% to the game engine.

2. **Pressure Redline (Combo) Attack**
   - *Expected:* The reactor pressure gauge spins out of control, the tank shakes or glows red, and a catastrophic steam explosion triggers.
   - *Current Bug:* The Unity simulation simply ignores the massive pressure spike (or crashes internally). No explosion animation exists in the compiled binary.

3. **E-Stop Injection Attack (Denial of Control)**
   - *Expected:* The factory physically halts. Pumps stop spinning, warning lights flash red, and valves slam shut.
   - *Current Bug:* The backend successfully safe-states the plant, but the 3D model lacks any flashing warning lights or mechanical indicators that an Emergency Stop was triggered.

## What We Tried (Backend Mitigations)
We attempted to force the Unity engine to respond by heavily modifying the backend:
- **Physics Tuning:** Slowed down the liquid and pressure accumulation rates in `datastore.py` so the values climb gradually, attempting to prevent Unity interpolation (Lerp) errors.
- **Payload Capping:** Capped the JSON `liquid_level` at `99.9%` to prevent out-of-bounds WebGL crashes when the tank overfills.
- **Auto-Reload:** Injected a Javascript auto-reload script into `viz.html` so the Unity iframe recovers if it freezes. 
- *Conclusion:* None of these backend fixes can bypass the fact that the original Unity C# code simply lacks the animation logic for these scenarios.

---

## Recommendations for the 3D Graphics Team
To make this Chemical Plant a competition-winning demonstration specifically tailored for the **Adani Project**, the Unity source project must be opened in the Unity Editor and recompiled with the following upgrades:

### 1. UI Cleanup & Adani Branding
- **Remove Default UI:** Delete the "Physical Vulnerabilities Found 0/9" overlay and the "TAB - options and controls" text box. They clutter the screen and break the immersion of our unified SOC dashboard.
- **Adani Customization:** Add Adani corporate logos to the central reactor and the factory walls to make the simulation feel like a bespoke, premium digital twin built exclusively for this presentation.

### 2. Implement Missing Attack Animations
- **Tank Overfill:** Properly hook up the Y-scale transform of the liquid mesh to the `"liquid_level"` JSON float. Add a fluid particle emitter at the top of the tank that spills liquid onto the floor when `liquid_level >= 100.0`.
- **Pressure Redline:** Add a dramatic steam/fire explosion particle effect that triggers when `pressure >= 4000`. Include a camera shake effect and shatter the glass window of the reactor.
- **E-Stop Injection:** Add spinning animations to the pump motors that immediately halt when `e_stop == 1`. Add flashing red emergency strobe lights around the factory floor that activate during a shutdown.

### 3. Data Sync Polish
- Ensure the green digital dials floating above the pipes in the 3D scene correctly read and display `f1_valve_pos`, `f2_valve_pos`, `product_valve_pos`, and `purge_valve_pos` from the `index.php` JSON payload.
