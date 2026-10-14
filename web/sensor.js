/* TeaWindow 传感器接入页（外部脚本，配合 CSP script-src 'self'） */
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  $("#ts").value = new Date().toISOString().slice(0, 19) + "+08:00";

  let busy = false;
  $("#send").onclick = async () => {
    if (busy) return;
    busy = true;
    const btn = $("#send");
    btn.disabled = true;
    const body = { station_id: $("#sid").value, ts: $("#ts").value };
    const map = { temp: "temp", rh: "rh", soil_moisture: "soil", precip: "precip", wind: "wind" };
    for (const k of Object.keys(map)) {
      const v = $("#" + map[k]).value;
      if (v !== "") body[k] = Number(v);
    }
    try {
      const r = await fetch("api/sensor", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Sensor-Token": $("#token").value },
        body: JSON.stringify(body),
      });
      let d = {};
      try { d = await r.json(); } catch (e) { /* ignore */ }
      $("#msg").textContent = r.ok ? ("✅ 上报成功，累计 " + d.count + " 条") : ("⚠️ " + (d.detail || r.status));
    } catch (e) {
      $("#msg").textContent = "⚠️ 失败（需在线服务）";
    } finally {
      busy = false;
      btn.disabled = false;
    }
  };

  async function renderRealtime() {
    try {
      const d = await (await fetch("api/realtime", { cache: "no-store" })).json();
      const st = d.stations || {};
      const ks = Object.keys(st);
      if (!ks.length) { $("#rt").textContent = "暂无上报。"; return; }
      const frag = document.createDocumentFragment();
      ks.forEach((k) => {
        const x = st[k];
        const p = [];
        if (x.temp != null) p.push(x.temp + "℃");
        if (x.rh != null) p.push("RH " + x.rh + "%");
        if (x.soil_moisture != null) p.push("土湿 " + x.soil_moisture);
        if (x.precip != null) p.push("雨 " + x.precip + "mm");
        const span = document.createElement("span");
        span.className = "kv";
        const b = document.createElement("b");
        b.textContent = k;
        span.appendChild(b);
        span.appendChild(document.createTextNode("：" + (p.join(" · ") || "–") + "（" + String(x.ts || "").slice(11, 16) + "）"));
        frag.appendChild(span);
      });
      const note = document.createElement("div");
      note.className = "note";
      note.style.marginTop = "8px";
      note.textContent = "共 " + d.n + " 条 · 更新于 " + d.updated;
      frag.appendChild(note);
      const box = $("#rt");
      box.innerHTML = "";
      box.appendChild(frag);
    } catch (e) {
      $("#rt").textContent = "（离线或服务不可用）";
    }
  }
  renderRealtime();
  setInterval(() => { if (!document.hidden) renderRealtime(); }, 15000);
})();