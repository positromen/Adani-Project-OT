/* ═══════════════════════════════════════════════════════════════════════════
   LogicWard Red Team Console — frontend logic
   ═══════════════════════════════════════════════════════════════════════════ */

function ts() {
  return new Date().toLocaleTimeString([], { hour12: false });
}

function log(msg, cls = "system") {
  const c = document.getElementById("logContainer");
  const d = document.createElement("div");
  d.className = "log-line " + cls;
  d.innerHTML = `<span class="timestamp">[${ts()}]</span> ${msg}`;
  c.appendChild(d);
  c.scrollTop = c.scrollHeight;
}

/* ── Fire an attack ───────────────────────────────────────────────────── */
async function fireAttack(id, btn) {
  const card = btn.closest(".attack-card");
  const result = card.querySelector(".card-result");

  btn.classList.add("loading");
  card.classList.remove("success", "failed");
  card.classList.add("firing");
  result.textContent = "";
  result.className = "card-result";

  log(`EXECUTING attack: <strong>${id}</strong>`, "attack");

  try {
    const resp = await fetch("/api/attack", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    const data = await resp.json();

    if (data.status === "success") {
      card.classList.remove("firing");
      card.classList.add("success");
      result.textContent = "✓ " + (data.detail || "OK");
      result.className = "card-result ok";
      log(`✓ ${id}: ${data.detail || "success"}`, "success");
    } else {
      card.classList.remove("firing");
      card.classList.add("failed");
      result.textContent = "✗ " + (data.detail || "failed");
      result.className = "card-result fail";
      log(`✗ ${id}: ${data.detail || "failed"}`, "error");
    }
  } catch (err) {
    card.classList.remove("firing");
    card.classList.add("failed");
    result.textContent = "✗ " + err.message;
    result.className = "card-result fail";
    log(`✗ ${id}: ${err.message}`, "error");
  }

  btn.classList.remove("loading");

  // Reset card glow after 4s
  setTimeout(() => card.classList.remove("success", "failed"), 4000);
}

/* ── Fire a utility action ────────────────────────────────────────────── */
async function fireUtility(id, btn) {
  btn.classList.add("loading");
  log(`Running utility: <strong>${id}</strong>`, "utility");

  try {
    const resp = await fetch("/api/utility", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    const data = await resp.json();

    if (data.status === "success") {
      log(`✓ ${id} complete`, "success");
      if (data.detail) log(data.detail.replace(/\n/g, "<br>"), "system");
    } else {
      log(`✗ ${id}: ${data.detail || "failed"}`, "error");
    }
  } catch (err) {
    log(`✗ ${id}: ${err.message}`, "error");
  }

  btn.classList.remove("loading");
}

/* ── Connection check on load ─────────────────────────────────────────── */
(async function checkTarget() {
  const dot = document.getElementById("statusDot");
  try {
    const r = await fetch("/api/attack", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: "__ping__" }),
    });
    // Even a 400 means our server is alive; the Pi connectivity
    // is tested when an actual attack is fired.
    dot.classList.add("online");
    dot.title = "Console online";
    log("Console ready. Select an attack to execute.", "system");
  } catch {
    dot.classList.add("offline");
    dot.title = "Console offline";
    log("WARNING: Could not reach attacker backend.", "error");
  }
})();
