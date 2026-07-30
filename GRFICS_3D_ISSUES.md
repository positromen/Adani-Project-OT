# GRFICS 3D Simulation Investigation & Limitations Report

This document outlines the investigation into the 3D Unity WebGL simulation (Chemical Reactor), the attempts made to fix the visual animations (specifically the Tank Overfill), and the final recommendations for the 3D team.

## The Problem
During the **Tank Overfill** attack, the backend Modbus physics engine correctly calculates the liquid level rising (e.g., reaching 96.2% or 117.1%). The HTML "Live Process" gauges on the SOC Dashboard accurately reflect this data in real-time. 

However, the **3D Unity Simulation** fails to animate the liquid level rising. The purple fluid inside the reactor glass remains visually stuck at approximately 40% fill, regardless of the actual backend data.

## What We Tried & Modified
We made several deep-level modifications to the Python backend and HTML frontend to try and force the Unity engine to respond:

1. **Physics Engine Speed Tuning (`datastore.py`)**
   - **Hypothesis:** The physical accumulation of liquid was happening so fast that the Unity engine was missing the intermediate frames and breaking the animation interpolation (Lerp).
   - **Action:** We modified the mathematical multipliers in `datastore.py` to slow down the liquid accumulation (`level += ... * dt * 0.75`), ensuring the values climbed gradually and realistically.
   - **Result:** No effect on the 3D visual.

2. **Capping the JSON Feed (`datastore.py`)**
   - **Hypothesis:** The Unity C# script was throwing an `ArgumentOutOfRangeException` and crashing the WebGL renderer when the liquid level exceeded 100.0%.
   - **Action:** We clamped the `"liquid_level"` variable sent in the `/data/index.php` JSON payload to a maximum of `99.9%`.
   - **Result:** While this prevented potential WebGL crashes, the liquid level still did not visually rise.

3. **Auto-Reload Injection (`viz.html`)**
   - **Hypothesis:** The Unity engine was becoming permanently desynced from the backend after a plant reset.
   - **Action:** We injected a Javascript polling loop that forces the Unity `<iframe>` to execute a full `window.location.reload()` whenever the `generation` counter changes (e.g., clicking Reset).
   - **Result:** The game reloads perfectly on reset, but the liquid animation is still non-functional.

## Conclusion: Unity Engine Limitations
The failure of the liquid animation is **not** a backend bug. The Modbus server, the Python physics engine, and the HTML dashboards are in perfect sync. 

The issue lies entirely within the **pre-compiled Unity WebGL binary** (`ChemicalPlant.json` / `UnityLoader.js`). Because we do not have the original Unity C# source code, we are hitting hardcoded limitations:
- The Unity C# script likely does not have an animation hooked up to the `"liquid_level"` JSON key, or it expects a different legacy variable name (e.g., `"level"`, `"reactor_level"`).
- The 3D model does not contain particle physics for liquid overflowing the tank or gas exploding.

## Recommendations: Recompiling the 3D Project
To achieve the polished, competition-ready visual experience required for the Adani project, the Unity 3D project **must be opened in the Unity Editor and recompiled** by the graphics team. 

When recompiling, the following changes must be made to the Unity source code:

1. **Remove Unnecessary UI Overlays:**
   - Delete the `"Physical Vulnerabilities Found 0/9"` text overlay in the top left.
   - Delete the `"TAB - options and controls, ESC - get cursor back"` text box in the bottom left.
   - These overlays clutter the SOC dashboard integration.

2. **Hook Up Liquid Animation:**
   - Ensure the C# script that parses the `index.php` JSON properly reads the `"liquid_level"` float.
   - Map this float to the Y-scale transform of the purple liquid mesh inside the reactor window so it visually rises from 0% to 100%.

3. **Add Attack Particle Effects (Optional but highly recommended):**
   - **Overfill:** Add a water particle emitter at the top of the tank that triggers when `liquid_level >= 100.0`.
   - **Pressure Redline:** Add a steam explosion particle effect that triggers when `pressure >= 4000`.
