/* LogicWard SOC dashboard — polling + rendering + role-gated actions */
(function () {
  "use strict";
  const ROLE_RANK = { operator: 1, engineer: 2, soc_analyst: 3 };
  const role = document.body.dataset.role || "operator";
  const myRank = ROLE_RANK[role] || 0;
  const SEV_RANK = { critical: 4, high: 3, medium: 2, low: 1, info: 0 };

  let cursor = 0;
  const events = [];
  const seen = new Set();
  let activeTab = "overview";

  const $ = (s, r) => (r || document).querySelector(s);
  const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
  const pretty = (t) => (t || "").replace(/_/g, " ");
  const fmt = (n) => (typeof n === "number" ? (Number.isInteger(n) ? n : n.toFixed(1)) : n);
  const jpost = (url, body) => fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) }).then(r => r.json());

  function toast(msg) {
    const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden");
    clearTimeout(t._h); t._h = setTimeout(() => t.classList.add("hidden"), 2600);
  }

  // role-gate action controls
  document.querySelectorAll("[data-role-min]").forEach(e => {
    if (myRank < ROLE_RANK[e.dataset.roleMin]) e.remove();
  });

  // tabs
  document.querySelectorAll(".nav-item").forEach(item => {
    item.addEventListener("click", () => {
      document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
      item.classList.add("active");
      activeTab = item.dataset.tab;
      document.querySelectorAll(".panel").forEach(p => p.classList.add("hidden"));
      $("#tab-" + activeTab).classList.remove("hidden");
      if (activeTab === "diff") loadDiff();
      if (activeTab === "alerts" || activeTab === "evidence") render();
    });
  });

  // topbar actions
  const lockBtn = $("#btn-lock"); if (lockBtn) lockBtn.addEventListener("click", () =>
    jpost("/api/baseline/lock").then(r => toast("Baseline re-locked · " + (r.hash || "").slice(7, 19))));
  const restoreBtn = $("#btn-restore"); if (restoreBtn) restoreBtn.addEventListener("click", () =>
    jpost("/api/response/restore").then(() => toast("Approved baseline restored")));

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
    }).catch(() => {});
  }

  function pollPlant() {
    fetch("/api/plant").then(r => r.json()).then(p => renderPlant(p)).catch(() => {});
  }

  // ---- rendering ----
  function alertActions(e) {
    const wrap = el("div", "alert-actions");
    const mk = (label, fn) => { const b = el("button", "mini-btn", label); b.onclick = fn; wrap.appendChild(b); };
    mk("Ack", () => jpost("/api/response/ack", { ref: e.event_id }).then(() => toast("Acknowledged")));
    if (myRank >= ROLE_RANK.soc_analyst && e.type === "physical.rogue_device")
      mk("Quarantine", () => jpost("/api/response/quarantine", { mac: e.details.mac, ip: e.details.ip, ref: e.event_id }).then(() => toast("Device quarantined")));
    if (myRank >= ROLE_RANK.soc_analyst && e.details && e.details.safety_critical && e.type.startsWith("cyber."))
      mk("Safe-state", () => jpost("/api/response/safe_state", { rung_id: e.details.rung_id, ref: e.event_id }).then(() => toast("Safe-state recommended")));
    return wrap;
  }

  function alertRow(e, withActions) {
    const row = el("div", "alert-row");
    row.appendChild(el("span", "sev " + e.severity, e.severity));
    const main = el("div", "alert-main");
    main.appendChild(el("div", "alert-type", e.type));
    main.appendChild(el("div", "alert-reason", (e.details && e.details.reason) || ""));
    const meta = el("div", "alert-meta");
    if (e.mitre && e.mitre.technique_id) {
      const m = el("span", "mitre-tag", e.mitre.technique_id + " " + e.mitre.technique_name);
      meta.appendChild(m);
    }
    meta.appendChild(el("span", null, "src: " + e.source));
    if (e.identity && e.identity.channel) meta.appendChild(el("span", null, "via: " + e.identity.channel));
    meta.appendChild(el("span", null, (e.timestamp || "").slice(11, 19)));
    main.appendChild(meta);
    row.appendChild(main);
    row.appendChild(el("span", null, ""));
    if (withActions) row.appendChild(alertActions(e)); else row.appendChild(el("span"));
    return row;
  }

  function sortedEvents() {
    return events.slice().sort((a, b) =>
      (SEV_RANK[b.severity] - SEV_RANK[a.severity]) || (b.seq - a.seq));
  }

  function render() {
    const crit = events.filter(e => e.severity === "critical").length;
    const badge = $("#alert-badge"); badge.textContent = events.length;
    badge.style.background = crit ? "var(--crit)" : "var(--muted-2)";

    if (activeTab === "alerts") {
      const box = $("#alerts-table"); box.innerHTML = "";
      sortedEvents().forEach(e => box.appendChild(alertRow(e, true)));
    }
    if (activeTab === "evidence") {
      const box = $("#evidence-table"); box.innerHTML = "";
      events.slice().sort((a, b) => b.seq - a.seq).forEach(e => box.appendChild(alertRow(e, false)));
    }
    // overview recent
    const ov = $("#ov-alerts"); if (ov) {
      ov.innerHTML = "";
      sortedEvents().slice(0, 6).forEach(e => ov.appendChild(alertRow(e, false)));
      if (!events.length) ov.appendChild(el("div", "muted tiny", "No drift detected — plant nominal."));
    }
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
  setInterval(() => { pollPlant(); if (activeTab === "diff") loadDiff(); }, 1500);
})();
