/* LogicWard SOC dashboard — polling + rendering + role-gated actions */
/* Modified by Komal & Antigravity (Adani Project RBAC Fixes) */
(function () {
  "use strict";
  const role = document.body.dataset.role || "operator";
  // capability-based RBAC (6 roles) — the server sends this user's capabilities
  const caps = (document.body.dataset.caps || "").split(",").filter(Boolean);
  const hasCap = (c) => caps.includes(c);
  const SEV_RANK = { critical: 4, high: 3, medium: 2, low: 1, info: 0 };

  let cursor = 0;
  const events = [];
  const seen = new Set();
  let activeTab = "overview";
  const acked = new Set();

  // ---- multi-site ----
  let activeSite = "thermal-pi";          // "thermal-pi" | "grfics-chem" | "all"
  let chemAvailable = false;
  let chemFrameLoaded = false;
  const SITE_META = {
    "thermal-pi": { name: "Thermal Power Plant", icon: "⚡" },
    "grfics-chem": { name: "GRFICS Chemical Reactor", icon: "⚗️" },
    "all": { name: "All Sites", icon: "🌐" },
  };
  const eventSite = (e) => (e.details && e.details.site) || "thermal-pi";
  const siteVisible = (e) => activeSite === "all" || eventSite(e) === activeSite;
  const siteLabel = (id) => (SITE_META[id] ? SITE_META[id].name : id);

  const $ = (s, r) => (r || document).querySelector(s);
  const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
  const pretty = (t) => (t || "").replace(/_/g, " ");
  const fmt = (n) => (typeof n === "number" ? (Number.isInteger(n) ? n : n.toFixed(1)) : n);
  const jpost = (url, body) => fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) }).then(r => r.json());

  function toast(msg) {
    const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden");
    clearTimeout(t._h); t._h = setTimeout(() => t.classList.add("hidden"), 2600);
  }

  // capability-gate action controls: remove any control this role can't use
  document.querySelectorAll("[data-cap]").forEach(e => {
    if (!hasCap(e.dataset.cap)) e.remove();
  });

  // tabs
  document.querySelectorAll(".nav-item").forEach(item => {
    item.addEventListener("click", () => {
      document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
      item.classList.add("active");
      activeTab = item.dataset.tab;
      document.querySelectorAll(".panel").forEach(p => p.classList.add("hidden"));
      $("#tab-" + activeTab).classList.remove("hidden");
      if (activeTab === "diff" && activeSite !== "grfics-chem") loadDiff();
      if (activeTab === "alerts" || activeTab === "evidence") render();
    });
  });

  // ---- site selector ----
  const SITE_SHORT = { "thermal-pi": "⚡ Thermal", "grfics-chem": "⚗️ Chemical", "all": "🌐 All" };

  function buildSiteTabs(list) {
    const box = $("#siteTabs"); if (!box) return;
    const ids = ["thermal-pi"];
    (list || []).forEach(s => { if (s.site_id === "grfics-chem" && s.available) chemAvailable = true; });
    if (chemAvailable) { ids.push("grfics-chem"); ids.push("all"); }
    box.innerHTML = "";
    ids.forEach(id => {
      const b = el("button", "site-tab" + (id === activeSite ? " active" : ""), SITE_SHORT[id] || id);
      b.dataset.site = id;
      b.onclick = () => setSite(id);
      box.appendChild(b);
    });
  }

  function setSite(id) {
    activeSite = id;
    document.querySelectorAll("#siteTabs .site-tab").forEach(b => b.classList.toggle("active", b.dataset.site === id));
    const t = $("#site-title"); if (t) t.textContent = siteLabel(id);
    const showChem = id === "grfics-chem";
    const pt = $("#plant-thermal"), pc = $("#plant-chem");
    if (pt) pt.classList.toggle("hidden", showChem);
    if (pc) pc.classList.toggle("hidden", !showChem);
    const dt = $("#diff-thermal"), dc = $("#diff-chem-note");
    if (dt) dt.classList.toggle("hidden", showChem);
    if (dc) dc.classList.toggle("hidden", !showChem);
    // lazy-load the 200 MB 3D scene only when the chemical site is first opened
    if (showChem && !chemFrameLoaded) { const f = $("#chem-frame"); if (f) { f.src = "/viz/"; chemFrameLoaded = true; } }
    const pdf = $("#btn-pdf"); if (pdf) pdf.href = "/api/evidence/report.pdf" + (id === "all" ? "" : "?site=" + id);
    render();
  }

  fetch("/api/sites").then(r => r.json()).then(d => buildSiteTabs(d.sites)).catch(() => {});

  // ---- chemical site: gauges + attacks ----
  function setCG(vid, mid, val, unit, max, warn, crit) {
    const v = $("#" + vid), m = $("#" + mid);
    if (v) v.innerHTML = (val == null ? "—" : val.toFixed(1)) + ' <span class="cg-u">' + unit + "</span>";
    if (m && val != null) {
      m.style.width = Math.max(0, Math.min(100, (val / max) * 100)) + "%";
      m.style.background = val >= crit ? "var(--crit)" : val >= warn ? "var(--med)" : "var(--ok, #37d67a)";
    }
  }
  function pollChem() {
    if (!chemAvailable) return;
    fetch("/api/site-b/state").then(r => r.json()).then(s => {
      const o = s.feed.outputs, st = s.feed.state;
      setCG("cg-press", "cgm-press", o.pressure, "kPa", 4000, 2600, 3200);
      setCG("cg-level", "cgm-level", o.liquid_level, "%", 120, 85, 100);
      setCG("cg-f1", "cgm-f1", st.f1_valve_pos, "%", 100, 101, 101);
      setCG("cg-f2", "cgm-f2", st.f2_valve_pos, "%", 100, 101, 101);
      setCG("cg-purge", "cgm-purge", st.purge_valve_pos, "%", 100, 101, 101);
      setCG("cg-product", "cgm-product", st.product_valve_pos, "%", 100, 101, 101);
      const esd = $("#cg-esd");
      if (esd) {
        if (st.e_stop) { esd.className = "pill bad"; esd.textContent = "Reactor: EMERGENCY SHUTDOWN"; }
        else { esd.className = "pill ok"; esd.textContent = "Reactor: RUNNING"; }
      }
    }).catch(() => {});
  }
  document.querySelectorAll(".chem-atk[data-atk]").forEach(b => {
    b.addEventListener("click", () => {
      b.disabled = true;
      jpost("/api/site-b/attack/" + b.dataset.atk).then(r => toast("Chemical: " + (r.note || r.attack || "attack fired")))
        .finally(() => setTimeout(() => (b.disabled = false), 500));
    });
  });
  const chemReset = $("#chem-reset"); if (chemReset) chemReset.addEventListener("click", () =>
    jpost("/api/site-b/reset").then(() => toast("Chemical plant restored to baseline")));

  // topbar actions
  const lockBtn = $("#btn-lock"); if (lockBtn) lockBtn.addEventListener("click", () =>
    jpost("/api/baseline/lock").then(r => toast("Baseline re-locked · " + (r.hash || "").slice(7, 19))));
  const restoreBtn = $("#btn-restore"); if (restoreBtn) restoreBtn.addEventListener("click", () =>
    jpost("/api/response/restore").then(() => toast("Approved baseline restored")));
  const clearLogsBtn = $("#btn-clear-logs"); if (clearLogsBtn) clearLogsBtn.addEventListener("click", () =>
    jpost("/api/alerts/clear").then(() => { toast("All alerts cleared"); setTimeout(() => window.location.reload(), 500); }));

  // baseline upload (L5X / XML / JSON)
  const blBtn = $("#bl-upload-btn");
  if (blBtn) blBtn.addEventListener("click", () => {
    const fileEl = $("#bl-file"), msg = $("#bl-upload-msg");
    const f = fileEl && fileEl.files[0];
    if (!f) { if (msg) msg.textContent = "choose a .L5X / .xml / .json file first"; return; }
    const fd = new FormData(); fd.append("file", f);
    if (msg) msg.textContent = "uploading…";
    fetch("/api/baseline/upload", { method: "POST", body: fd }).then(r => r.json()).then(d => {
      if (d.error) { if (msg) msg.textContent = "✗ " + d.error; toast("Baseline upload rejected"); }
      else {
        if (msg) msg.textContent = "✓ baseline set (" + d.kind + ") · " + (d.hash || "").slice(7, 19);
        toast("Approved baseline updated"); if (activeSite !== "grfics-chem") loadDiff();
      }
    }).catch(() => { if (msg) msg.textContent = "✗ upload error"; });
  });

  // ---- polling ----
  function pollEvents() {
    fetch("/api/events?since=" + cursor).then(r => r.json()).then(d => {
      cursor = d.cursor;
      let newCrit = false;
      (d.events || []).forEach(e => {
        if (seen.has(e.event_id)) return;
        seen.add(e.event_id); events.push(e);
        if (e.severity === "critical") newCrit = true;
      });
      if (newCrit) { toast("⚠ Critical drift detected"); }
      render();
    }).catch(() => {});
  }

  function pollOverview() {
    fetch("/api/overview").then(r => r.json()).then(o => {
      $("#controller").textContent = o.controller || "—";
      const c = o.severity_counts || {};
      $("#c-crit").textContent = c.critical || 0;
      $("#c-high").textContent = c.high || 0;
      $("#c-med").textContent = c.medium || 0;
      $("#kpi-crit").textContent = c.critical || 0;
      $("#kpi-total").textContent = o.event_total || 0;
      const integ = $("#kpi-integrity"); integ.textContent = o.baseline_integrity;
      integ.className = "kpi-val " + (o.baseline_integrity === "VALID" ? "ok" : "bad");
      const sync = $("#kpi-sync"); sync.textContent = o.program_in_sync ? "IN SYNC" : "DRIFTED";
      sync.className = "kpi-val " + (o.program_in_sync ? "ok" : "bad");
      $("#side-hash").textContent = (o.baseline_hash || "").slice(0, 30) + "…";
      const sp = $("#side-integrity"); sp.textContent = o.baseline_integrity;
      sp.className = "pill " + (o.baseline_integrity === "VALID" ? "ok" : "bad");
      // -- production-grade panels (additive) --
      renderRisk(o.risk_score, o.risk_band);
      renderHealth(o.sites || []);
      renderRollback(o.rollback || {});
    }).catch(() => {});
  }

  // ---- risk score / system health / rollback (production-grade) ----
  const RISK_COLOR = { LOW: "var(--good)", MODERATE: "var(--warn)", ELEVATED: "var(--serious)", HIGH: "var(--crit)", CRITICAL: "var(--crit)" };
  function renderRisk(score, band) {
    if (score == null) return;
    const s = $("#risk-score"); if (s) s.textContent = score;
    const b = $("#risk-band"); if (b) { b.textContent = band || "—"; b.style.color = RISK_COLOR[band] || "var(--muted)"; }
    const f = $("#risk-bar-fill"); if (f) { f.style.width = score + "%"; f.style.background = RISK_COLOR[band] || "var(--accent)"; }
  }
  function renderHealth(sites) {
    const box = $("#site-health"); if (!box) return;
    box.innerHTML = "";
    sites.forEach(s => {
      const row = el("div", "health-row");
      row.appendChild(el("span", "health-dot " + (s.online ? "up" : "down")));
      const main = el("div", "health-main");
      main.appendChild(el("div", "health-name", (s.icon || "") + " " + s.name));
      main.appendChild(el("div", "health-sub", (s.online ? "online" : "offline") + " · " + s.events + " events"));
      row.appendChild(main);
      row.appendChild(el("span", "health-status st-" + (s.status || "").toLowerCase(), s.status || ""));
      box.appendChild(row);
    });
  }
  function renderRollback(rb) {
    const box = $("#rollback-status"); if (!box) return;
    box.innerHTML = "";
    const mk = (label, val, ok) => {
      const r = el("div", "rb-row");
      r.appendChild(el("span", "rb-label", label));
      r.appendChild(el("span", "rb-val " + (ok ? "ok" : "bad"), val));
      box.appendChild(r);
    };
    mk("Baseline integrity", rb.baseline_integrity || "—", rb.baseline_integrity === "VALID");
    mk("Program vs baseline", rb.program_in_sync ? "IN SYNC" : ((rb.drifted_rungs || 0) + " rung(s) drifted"), !!rb.program_in_sync);
    mk("Rollback", rb.restorable ? "restore available" : "not needed", !rb.restorable);
  }
  function renderTimeline(evs) {
    const box = $("#timeline"); if (!box) return;
    if (!evs.length) { box.innerHTML = '<div class="muted tiny" style="padding:14px">No events yet.</div>'; return; }
    const recent = evs.slice().sort((a, b) => a.seq - b.seq).slice(-48);
    box.innerHTML = "";
    recent.forEach(e => {
      const tick = el("div", "tl-tick " + e.severity);
      const sid = (typeof eventSite === "function") ? eventSite(e) : "thermal-pi";
      const sname = (typeof SITE_SHORT !== "undefined" && SITE_SHORT[sid]) || sid;
      tick.title = sname + " · " + e.type + " · " + (e.timestamp || "").slice(11, 19);
      box.appendChild(tick);
    });
  }

  function pollPlant() {
    fetch("/api/plant").then(r => r.json()).then(p => renderPlant(p)).catch(() => {});
  }

  // ---- rendering ----
  function alertActions(e) {
    const wrap = el("div", "alert-actions");
    const mk = (label, fn) => { const b = el("button", "mini-btn", label); b.onclick = fn; wrap.appendChild(b); };
    if (hasCap("ack"))
      mk("Ack", () => { acked.add(e.event_id); flagMimic(); jpost("/api/response/ack", { ref: e.event_id }).then(() => toast("Acknowledged")); });
    if (hasCap("network_response") && e.type === "physical.rogue_device")
      mk("Quarantine", () => jpost("/api/response/quarantine", { mac: e.details.mac, ip: e.details.ip, ref: e.event_id }).then(() => toast("Device quarantined")));
    if (hasCap("safe_state") && e.details && e.details.safety_critical && e.type.startsWith("cyber."))
      mk("Safe-state", () => jpost("/api/response/safe_state", { rung_id: e.details.rung_id, ref: e.event_id }).then(() => toast("Safe-state recommended")));
    return wrap;
  }

  function alertRow(e, withActions) {
    const row = el("div", "alert-row");
    row.appendChild(el("span", "sev " + e.severity, e.severity));
    const main = el("div", "alert-main");
    main.appendChild(el("div", "alert-type", e.type));
    main.appendChild(el("div", "alert-reason", (e.details && e.details.reason) || ""));
    const cmd = e.details && e.details.command;
    if (cmd) {
      const c = el("div", "alert-cmd");
      c.appendChild(el("span", "cmd-label", "HOW"));
      c.appendChild(el("code", null, cmd));
      main.appendChild(c);
    }
    const meta = el("div", "alert-meta");
    const sid = eventSite(e);
    meta.appendChild(el("span", "site-chip s-" + sid, (SITE_SHORT[sid] || sid)));
    if (e.mitre && e.mitre.technique_id) {
      const m = el("span", "mitre-tag", e.mitre.technique_id + " " + e.mitre.technique_name);
      meta.appendChild(m);
    }
    const who = e.identity && e.identity.who;
    if (who && who !== "unknown") meta.appendChild(el("span", "who-chip", "by " + who));
    meta.appendChild(el("span", null, "src: " + e.source));
    if (e.identity && e.identity.channel) meta.appendChild(el("span", null, "via: " + e.identity.channel));
    const d = new Date(e.timestamp); meta.appendChild(el("span", null, isNaN(d) ? (e.timestamp || "").slice(11, 19) : d.toLocaleTimeString([], {hour12: false})));
    main.appendChild(meta);
    row.appendChild(main);
    row.appendChild(el("span", null, ""));
    if (withActions) row.appendChild(alertActions(e)); else row.appendChild(el("span"));
    return row;
  }

  function sortedEvents(list) {
    return (list || events).slice().sort((a, b) =>
      (SEV_RANK[b.severity] - SEV_RANK[a.severity]) || (b.seq - a.seq));
  }

  function render() {
    const vis = events.filter(siteVisible);
    const crit = vis.filter(e => e.severity === "critical").length;
    const badge = $("#alert-badge"); badge.textContent = vis.length;
    badge.style.background = crit ? "var(--crit)" : "var(--muted-2)";

    if (activeTab === "alerts") {
      const box = $("#alerts-table"); box.innerHTML = "";
      sortedEvents(vis).forEach(e => box.appendChild(alertRow(e, true)));
    }
    if (activeTab === "evidence") {
      const box = $("#evidence-table"); box.innerHTML = "";
      vis.slice().sort((a, b) => b.seq - a.seq).forEach(e => box.appendChild(alertRow(e, false)));
    }
    // overview recent
    const ov = $("#ov-alerts"); if (ov) {
      ov.innerHTML = "";
      sortedEvents(vis).slice(0, 6).forEach(e => ov.appendChild(alertRow(e, false)));
      if (!vis.length) ov.appendChild(el("div", "muted tiny", "No drift detected — plant nominal."));
    }
    renderTimeline(vis);
    flagMimic();
  }

  function renderPlant(p) {
    const vg = $("#plant-values"); if (vg) {
      vg.innerHTML = "";
      Object.entries(p.input_registers || {}).forEach(([tag, v]) => {
        const d = el("div", "v");
        d.appendChild(el("div", "v-label", pretty(tag)));
        const num = el("div", "v-num"); num.textContent = fmt(v.eng);
        num.appendChild(el("span", "v-unit", v.unit)); d.appendChild(num);
        vg.appendChild(d);
      });
    }
    const sg = $("#plant-setpoints"); if (sg) {
      sg.innerHTML = "";
      Object.entries(p.holding_registers || {}).forEach(([tag, v]) => {
        const d = el("div", "v");
        d.appendChild(el("div", "v-label", pretty(tag)));
        const num = el("div", "v-num"); num.textContent = fmt(v.eng);
        num.appendChild(el("span", "v-unit", v.unit)); d.appendChild(num);
        sg.appendChild(d);
      });
    }
    const tg = $("#plant-trips"); if (tg) {
      tg.innerHTML = "";
      Object.entries(p.coils || {}).filter(([t]) => /trip|alarm/i.test(t)).forEach(([tag, on]) => {
        const d = el("div", "trip");
        d.appendChild(el("span", null, pretty(tag)));
        d.appendChild(el("span", "st " + (on ? "tripped" : "clear"), on ? "TRIPPED" : "CLEAR"));
        tg.appendChild(d);
      });
    }
    const mp = $("#ov-plant"); if (mp) {
      mp.innerHTML = "";
      const keys = ["Generator_MW", "Steam_Pressure", "Drum_Level", "Turbine_Speed", "Condenser_Vacuum", "Bearing_Vibration"];
      keys.forEach(k => {
        const v = (p.input_registers || {})[k]; if (!v) return;
        const d = el("div", "mp");
        d.appendChild(el("span", "muted", pretty(k)));
        d.appendChild(el("b", null, fmt(v.eng) + " " + v.unit));
        mp.appendChild(d);
      });
    }
    renderTrends(p);
    updateMimic(p);
  }

  // ---- live trend sparklines ----
  const TREND_KEYS = ["Generator_MW", "Steam_Pressure", "Main_Steam_Temp", "Drum_Level",
                      "Turbine_Speed", "Condenser_Vacuum", "Bearing_Vibration"];
  const trendHist = {};
  const TREND_MAX = 60;
  const SVGNS = "http://www.w3.org/2000/svg";

  function renderTrends(p) {
    const box = $("#plant-trends"); if (!box) return;
    const ir = p.input_registers || {};
    TREND_KEYS.forEach(k => {
      const v = ir[k]; if (!v) return;
      (trendHist[k] = trendHist[k] || []).push(v.eng);
      if (trendHist[k].length > TREND_MAX) trendHist[k].shift();
    });
    box.innerHTML = "";
    TREND_KEYS.forEach(k => {
      const v = ir[k]; if (!v) return;
      const d = el("div", "trend");
      const head = el("div", "trend-head");
      head.appendChild(el("span", "trend-label", pretty(k)));
      const cur = el("span", "trend-cur", fmt(v.eng));
      cur.appendChild(el("span", "trend-unit", " " + v.unit));
      head.appendChild(cur);
      d.appendChild(head);
      d.appendChild(sparkline(trendHist[k] || []));
      box.appendChild(d);
    });
  }

  function sparkline(vals) {
    const w = 170, h = 34, pad = 3;
    const svg = document.createElementNS(SVGNS, "svg");
    svg.setAttribute("viewBox", "0 0 " + w + " " + h);
    svg.setAttribute("class", "spark");
    if (vals.length < 2) return svg;
    let lo = Math.min(...vals), hi = Math.max(...vals);
    if (hi - lo < 1e-6) hi = lo + 1;
    const x = i => pad + i * (w - 2 * pad) / (vals.length - 1);
    const y = val => h - pad - (val - lo) / (hi - lo) * (h - 2 * pad);
    const rising = vals[vals.length - 1] >= vals[vals.length - 2];
    const stroke = rising ? "var(--accent)" : "var(--serious)";
    const poly = document.createElementNS(SVGNS, "polyline");
    poly.setAttribute("points", vals.map((v, i) => x(i).toFixed(1) + "," + y(v).toFixed(1)).join(" "));
    poly.setAttribute("fill", "none");
    poly.setAttribute("stroke", stroke);
    poly.setAttribute("stroke-width", "1.6");
    poly.setAttribute("vector-effect", "non-scaling-stroke");
    svg.appendChild(poly);
    const dot = document.createElementNS(SVGNS, "circle");
    dot.setAttribute("cx", x(vals.length - 1)); dot.setAttribute("cy", y(vals[vals.length - 1]));
    dot.setAttribute("r", "2.2"); dot.setAttribute("fill", stroke);
    svg.appendChild(dot);
    return svg;
  }

  // ---- live SCADA mimic ----
  const fmtOrDash = (n) => (n == null ? "—" : fmt(n));
  const TAG_NODE = {
    Drum_Level: "n-drum", Drum_Level_LL_SP: "n-drum", Drum_Level_Sensor_OK: "n-drum",
    Feedwater_Trip: "r-feedwater", Feedwater_Pump_1: "n-fwp", Feedwater_Pump_2: "n-fwp",
    Steam_Pressure: "n-msv", Main_Steam_Temp: "n-msv", Steam_Press_HH_SP: "n-msv",
    Main_Steam_Valve_Open: "n-msv", Main_Steam_Trip: "r-steam",
    Turbine_Speed: "n-turbine", Turbine_Overspeed_SP: "n-turbine", Turbine_Trip: "r-turbine",
    Bearing_Vibration: "n-turbine", Bearing_Vib_HI_SP: "n-turbine", Vibration_Alarm: "r-turbine",
    Generator_MW: "n-gen", Load_Setpoint_MW: "n-gen", Generator_Breaker_Closed: "n-gcb",
    Condenser_Vacuum: "n-cond", Condenser_Vac_LO_SP: "n-cond", Condenser_Trip: "r-cond", Vacuum_Sensor_OK: "n-cond",
    Fuel_Valve_Open: "n-fuel", Fuel_Trip: "r-fuel", Flame_Detected: "n-furnace",
  };
  const TYPE_NODE = {
    "physical.enclosure_open": "n-plc", "physical.link_down": "n-grid", "physical.link_up": "n-grid",
    "physical.rogue_device": "n-net", "resource.cpu_spike": "n-plc", "resource.mem_spike": "n-plc",
    "cyber.baseline_tamper": "n-plc",
  };
  const RUNG_NODE = { Rung0: "n-drum", Rung1: "n-msv", Rung2: "n-turbine", Rung3: "n-furnace", Rung4: "n-cond", Rung5: "n-turbine" };

  function setNodeState(valId, on, onLabel, offLabel, nodeId) {
    const v = $("#" + valId); if (v) v.textContent = on ? onLabel : offLabel;
    if (nodeId) { const n = $("#" + nodeId); if (n) n.classList.toggle("off", !on); }
  }
  function relayState(id, tripped) { const n = $("#" + id); if (n) n.classList.toggle("tripped", !!tripped); }

  function updateMimic(p) {
    const ir = p.input_registers || {}, co = p.coils || {}, di = p.discrete_inputs || {};
    const g = (k) => (ir[k] ? ir[k].eng : null);
    const set = (id, v) => { const e = $("#" + id); if (e) e.textContent = v; };
    set("v-drum", fmtOrDash(g("Drum_Level")));
    set("v-steamp", fmtOrDash(g("Steam_Pressure")));
    set("v-steamt", fmtOrDash(g("Main_Steam_Temp")));
    set("v-turb", fmtOrDash(g("Turbine_Speed")));
    set("v-vib", fmtOrDash(g("Bearing_Vibration")));
    set("v-cond", fmtOrDash(g("Condenser_Vacuum")));
    set("v-gen", fmtOrDash(g("Generator_MW")));
    const rpm = g("Turbine_Speed"); set("v-freq", rpm != null ? (rpm / 60).toFixed(2) : "—");
    setNodeState("s-fuel", co.Fuel_Valve_Open, "OPEN", "SHUT", "n-fuel");
    setNodeState("s-flame", di.Flame_Detected, "FLAME OK", "NO FLAME", "n-furnace");
    setNodeState("s-fwp", co.Feedwater_Pump_1 || co.Feedwater_Pump_2, "RUNNING", "STOPPED", "n-fwp");
    setNodeState("s-msv", co.Main_Steam_Valve_Open, "OPEN", "SHUT", "n-msv");
    setNodeState("s-gcb", co.Generator_Breaker_Closed, "CLOSED", "OPEN", "n-gcb");
    relayState("r-feedwater", co.Feedwater_Trip);
    relayState("r-fuel", co.Fuel_Trip);
    relayState("r-steam", co.Main_Steam_Trip);
    relayState("r-turbine", co.Turbine_Trip || co.Vibration_Alarm);
    relayState("r-cond", co.Condenser_Trip);
  }

  function nodesForEvent(e) {
    const ids = new Set();
    if (TYPE_NODE[e.type]) ids.add(TYPE_NODE[e.type]);
    const blob = (e.type || "") + " " + JSON.stringify(e.details || {});
    Object.keys(TAG_NODE).forEach(name => { if (blob.indexOf(name) >= 0) ids.add(TAG_NODE[name]); });
    const rid = e.details && e.details.rung_id;
    if (rid) Object.keys(RUNG_NODE).forEach(rk => { if (rid.indexOf(rk) >= 0) ids.add(RUNG_NODE[rk]); });
    return [...ids];
  }

  function flagMimic() {
    if (!$("#mimic")) return;
    document.querySelectorAll("#mimic .pin").forEach(p => p.remove());
    document.querySelectorAll("#mimic .attacked").forEach(n => { n.classList.remove("attacked"); n.onclick = null; });
    const per = {};
    events.forEach(e => {
      if (acked.has(e.event_id)) return;
      nodesForEvent(e).forEach(id => {
        const r = per[id] || (per[id] = { sev: "info", mitre: null, ids: [] });
        r.ids.push(e.event_id);
        if (SEV_RANK[e.severity] >= SEV_RANK[r.sev]) { r.sev = e.severity; r.mitre = e.mitre; }
      });
    });
    Object.entries(per).forEach(([id, r]) => {
      const n = $("#" + id); if (!n) return;
      n.classList.add("attacked");
      const tech = (r.mitre && r.mitre.technique_id && r.mitre.technique_id !== "N/A") ? r.mitre.technique_id : r.sev.toUpperCase();
      n.appendChild(el("div", "pin " + r.sev, tech));
      n.onclick = () => {
        r.ids.forEach(x => acked.add(x));
        jpost("/api/response/ack", { ref: r.ids[0] }).catch(() => {});
        flagMimic();
        toast("Acknowledged · " + id.replace(/^[nr]-/, ""));
      };
    });
  }

  function loadDiff() {
    fetch("/api/diff").then(r => r.json()).then(d => {
      $("#diff-bhash").textContent = (d.baseline_hash || "").slice(7, 19);
      $("#diff-lhash").textContent = (d.live_hash || "").slice(7, 19);
      const s = d.summary || {};
      $("#diff-summary").textContent = d.changed === 0 ? "identical to baseline"
        : `${s.changed} changed · ${s.added} added · ${s.removed} removed`;
      const body = $("#diff-body"); body.innerHTML = "";
      (d.rows || []).forEach(row => {
        const r = el("div", "diff-row " + row.type);
        r.appendChild(segCell(row.left_seg));
        r.appendChild(segCell(row.right_seg));
        body.appendChild(r);
      });
    }).catch(() => {});
  }

  function segCell(segs) {
    const c = el("div", "diff-cell");
    (segs || []).forEach(s => {
      if (s.hl) { const sp = el("span", "hl", s.text); c.appendChild(sp); }
      else c.appendChild(document.createTextNode(s.text));
    });
    return c;
  }

  // ---- loops ----
  pollEvents(); pollOverview(); pollPlant();
  setInterval(pollEvents, 1000);
  setInterval(pollOverview, 2000);
  setInterval(() => { pollPlant(); if (activeTab === "diff" && activeSite !== "grfics-chem") loadDiff(); }, 1500);
  setInterval(() => { if (activeSite === "grfics-chem") pollChem(); }, 700);
})();
