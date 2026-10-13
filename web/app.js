/* 梅坞采候 TeaWindow — 仪表盘逻辑（在线读 /api/overview，失败回退内嵌 data.js） */
(async function () {
  let D = window.TW_DATA;              // 离线内嵌数据（data.js）
  try {                                 // 在线模式：优先实时 API
    const r = await fetch("api/overview", { cache: "no-store" });
    if (r.ok) D = await r.json();
  } catch (e) { /* 离线：忽略，使用内嵌数据 */ }
  if (!D) { alert("数据未加载：在线需 /api/overview，离线需 data.js"); return; }
  const days = D.days;
  const hist = days.filter(d => d.source === "history");
  const fc = days.filter(d => d.source === "forecast");
  const byDate = {}; days.forEach(d => byDate[d.date] = d);
  const RISK = { "低": "#3fb950", "中": "#d6b657", "高": "#e08a3c", "极高": "#e5534b" };
  const md = s => (s || "").slice(5);
  const fmt = v => (v === null || v === undefined) ? "–" : v;

  document.getElementById("hdr-meta").textContent =
    `坐标 ${D.meta.lat}°N, ${D.meta.lon}°E · 更新时间 ${D.meta.updated} · 历史 ${hist.length} 天 + 预报 ${fc.length} 天`;

  /* ---------------- KPI 卡片 ---------------- */
  const today = new Date().toISOString().slice(0, 10);
  let cur = hist[hist.length - 1];
  const curNext = hist.find(d => d.date >= today);
  if (curNext) cur = curNext;
  const next7 = fc.slice(0, 7);
  const maxRisk7 = next7.reduce((a, b) => (b.risk_R > a.risk_R ? b : a), next7[0] || cur);
  const win = D.pick_window[0] || {};
  const m = D.metrics;
  const cards = [
    { k: "最近研判日风险", v: `<span class="badge b${cur.risk_level}">${cur.risk_level}</span>`,
      s: `${cur.date} · 风险度 ${(cur.risk_R).toFixed(2)} · 适宜度 ${cur.suitability}` },
    { k: "未来 7 天最高风险", v: `<span class="badge b${maxRisk7.risk_level}">${maxRisk7.risk_level}</span>`,
      s: `${maxRisk7.date} · 风险度 ${(maxRisk7.risk_R).toFixed(2)}` },
    { k: "推荐采摘窗口", v: (win.date || "–").slice(5), s: `适宜度 ${fmt(win.suitability)} · 风险 ${win.risk_level || "–"}` },
    { k: "模型 AUC（测试年）", v: (m.ml.auc).toFixed(3), s: `F1 ${m.ml.f1} · 基线 AUC ${m["baseline_single_threshold(tmin<=2)"].auc}` }
  ];
  document.getElementById("cards").innerHTML = cards.map(c =>
    `<div class="card"><div class="k">${c.k}</div><div class="v">${c.v}</div><div class="s">${c.s}</div></div>`).join("");

  /* ---------------- 图表数据 ---------------- */
  const recent60 = hist.slice(-60);
  const rn = recent60.concat(fc);
  const labels = rn.map(d => md(d.date));
  const fcStart = recent60.length; // 预报起始索引

  const shade = {
    id: "fcShade",
    beforeDatasetsDraw(c) {
      const x = c.scales.x; if (!x) return;
      const xa = c.ctx; const left = x.getPixelForValue(fcStart - 0.5);
      xa.save(); xa.fillStyle = "rgba(74,168,255,0.07)";
      xa.fillRect(left, c.chartArea.top, c.chartArea.right - left, c.chartArea.bottom - c.chartArea.top);
      xa.restore();
    }
  };

  new Chart(document.getElementById("chartRisk"), {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "综合风险度", data: rn.map(d => d.risk_R), borderColor: "#e5534b", backgroundColor: "rgba(229,83,75,.15)", fill: true, tension: .3, pointRadius: 0, borderWidth: 2 },
        { label: "采摘适宜度", data: rn.map(d => d.suitability / 100), borderColor: "#3fb950", backgroundColor: "rgba(63,185,80,.10)", fill: true, tension: .3, pointRadius: 0, borderWidth: 2 }
      ]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: "#cfe0ee" } } },
      scales: { y: { min: 0, max: 1, ticks: { color: "#8aa0b2" }, grid: { color: "#26343f" } },
                x: { ticks: { color: "#8aa0b2", maxTicksLimit: 14 }, grid: { color: "#1d2b37" } } } },
    plugins: [shade]
  });

  const frost = rn.map(d => d.frost ? d.tmin : null);
  const heat = rn.map(d => d.heat ? d.tmax : null);
  const cold = rn.map(d => d.cold_shock ? d.tmin : null);
  new Chart(document.getElementById("chartTemp"), {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "Tmax", data: rn.map(d => d.tmax), borderColor: "#e08a3c", tension: .3, pointRadius: 0, borderWidth: 1.6 },
        { label: "Tmin", data: rn.map(d => d.tmin), borderColor: "#4aa8ff", tension: .3, pointRadius: 0, borderWidth: 1.6 },
        { label: "霜冻", data: frost, showLine: false, pointRadius: 5, pointStyle: "circle", backgroundColor: "#4aa8ff" },
        { label: "高温", data: heat, showLine: false, pointRadius: 5, pointStyle: "circle", backgroundColor: "#e5534b" },
        { label: "倒春寒", data: cold, showLine: false, pointRadius: 6, pointStyle: "triangle", backgroundColor: "#d6b657" }
      ]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: "#cfe0ee" } } },
      scales: { y: { ticks: { color: "#8aa0b2" }, grid: { color: "#26343f" } },
                x: { ticks: { color: "#8aa0b2", maxTicksLimit: 14 }, grid: { color: "#1d2b37" } } } },
    plugins: [shade]
  });

  const ns = D.ndvi.series || [];
  const s2 = (D.s2_ndvi && D.s2_ndvi.series) || [];
  new Chart(document.getElementById("chartNdvi"), {
    type: "line",
    data: { labels: ns.map(s => md(s.date)), datasets: [
      { label: "MODIS NDVI(近似)", data: ns.map(s => s.ndvi), borderColor: "#3fb950", backgroundColor: "rgba(63,185,80,.15)", fill: true, tension: .35, pointRadius: 2 },
      { label: "Sentinel-2 NDVI(数值)", data: ns.map(s => { const h = s2.find(x => x.date === s.date); return h ? h.ndvi : null; }),
        showLine: false, pointRadius: 6, pointStyle: "rectRot", backgroundColor: "#4aa8ff" }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: "#cfe0ee" } } },
      scales: { y: { min: -0.2, max: 1, ticks: { color: "#8aa0b2" }, grid: { color: "#26343f" } },
                x: { ticks: { color: "#8aa0b2", maxTicksLimit: 12 }, grid: { color: "#1d2b37" } } } }
  });
  document.getElementById("ndvi-note").textContent =
    `共 ${ns.length} 个真实 MODIS NDVI 8天合成点；另有 ${s2.length} 个 Sentinel-2 数值 NDVI 样本（蓝色方点，非颜色反演）。${D.ndvi.caveat}`;

  /* ---------------- 地块地形 ---------------- */
  if (D.terrain && D.terrain.plots) {
    document.querySelector("#plotTable tbody").innerHTML = D.terrain.plots.map(p => `<tr>
      <td>${p.name}</td><td>${p.elev_m}</td><td>${p.slope_deg}°</td><td>${p.aspect_deg}°</td>
      <td><span class="badge b${p.frost_risk}">${p.frost_risk}</span></td></tr>`).join("");
    document.getElementById("terrain-note").textContent =
      D.terrain.method + " " + D.terrain.disclaimer;
  }

  /* ---------------- 采摘调度 ---------------- */
  if (D.schedule && D.schedule.schedule) {
    document.querySelector("#schedTable tbody").innerHTML = D.schedule.schedule.map(s => `<tr>
      <td>${s.date}</td><td>${s.suitability}</td>
      <td><span class="badge b${s.risk_level}">${s.risk_level}</span></td>
      <td>${s.plots.map(p => `${p.name}<span class="tag">(${p.reason})</span>`).join("、") || "–"}</td>
    </tr>`).join("");
    const pr = D.schedule.priority.map(p => `<span class="pill">${p.name} 易感${p.frost_risk}</span>`).join("");
    document.getElementById("sched-note").innerHTML =
      `${D.schedule.method} 每日产能 ${D.schedule.capacity_per_day} 个地块。<br>抢采优先级：${pr}`;
  }

  /* ---------------- 决策建议（期望效用） ---------------- */
  if (D.decision && D.decision.days) {
    const badge = a => `<span class="badge b${a === "抢采" ? "低" : (a === "防护" ? "中" : "高")}">${a}</span>`;
    document.querySelector("#decTable tbody").innerHTML = D.decision.days.map(d => `<tr>
      <td>${d.date}</td><td>${(d.p_hazard * 100).toFixed(0)}%</td>
      <td>${d.ev_pick}</td><td>${d.ev_protect}</td><td>${d.ev_wait}</td><td>${badge(d.recommend)}</td></tr>`).join("");
    document.getElementById("dec-note").textContent =
      `${D.decision.method} 最佳采摘日：${D.decision.best_pick_day}。`;
  }

  /* ---------------- 价值闭环 ---------------- */
  if (D.value) {
    const v = D.value;
    document.getElementById("valueCards").innerHTML = [
      { k: "霜冻致损年概率", v: (v.p_frost * 100).toFixed(0) + "%" },
      { k: "高温致损年概率", v: (v.p_heat * 100).toFixed(0) + "%" },
      { k: "预期损失", v: "¥" + v.expected_loss_per_mu + "/亩·年" },
      { k: "参考保费", v: "¥" + v.premium_per_mu + "/亩" },
      { k: "工具减损价值", v: "¥" + v.tool_benefit_per_mu + "/亩·年" }
    ].map(c => `<div class="card"><div class="k">${c.k}</div><div class="v">${c.v}</div></div>`).join("");
    document.getElementById("value-note").textContent =
      "示意性测算（参数为公开锚点/合理假设）；详见 report/value_chain.md 与 submit/06_商业模式.md。";
  }

  /* ---------------- 预报表格 ---------------- */
  const tb = document.querySelector("#fcTable tbody");
  tb.innerHTML = fc.map(d => `<tr class="fc-row">
    <td>${d.date}<div class="tag">${"日一二三四五六"[new Date(d.date).getDay()]}</div></td>
    <td><span class="badge b${d.risk_level}">${d.risk_level}</span></td>
    <td>${d.suitability}</td>
    <td>${d.tmax}° / ${d.tmin}°</td>
    <td>${d.precip} mm</td>
    <td>${d.p_frost != null ? (100 * d.p_frost).toFixed(0) + "% / " + (100 * d.p_heat).toFixed(0) + "%" : "–"}</td>
    <td class="adv">${d.advice || ""}<div class="tag">来源：${d.advice_source === "deepseek-chat" ? "DeepSeek" : "规则模板"}</div></td>
  </tr>`).join("");

  /* ---------------- 模型指标 ---------------- */
  document.getElementById("metrics").innerHTML = `
    <div class="note">
      <b>模型</b>：${m.model}（弱标签监督：专家农艺规则生成复合风险标签）。<br>
      <b>训练</b>：${m.train_years}　<b>测试</b>：${m.test_years}。<br>
      <span class="pill">AUC ${m.ml.auc}</span>
      <span class="pill">精确率 ${m.ml.precision}</span>
      <span class="pill">召回率 ${m.ml.recall}</span>
      <span class="pill">F1 ${m.ml.f1}</span>
      <span class="pill">准确率 ${m.ml.accuracy}</span>
    </div>
    <div class="note" style="margin-top:8px">
      <b>对比单阈值基线（仅 Tmin≤2 判霜冻）</b>：
      <span class="pill">AUC ${m["baseline_single_threshold(tmin<=2)"].auc}</span>
      <span class="pill">F1 ${m["baseline_single_threshold(tmin<=2)"].f1}</span>
      <span class="pill">召回 ${m["baseline_single_threshold(tmin<=2)"].recall}</span>
    </div>
    <div class="note" style="margin-top:8px">
      <b>关键特征（置换重要性 Top）</b>：${Object.entries(m.permutation_importance_top).slice(0,6).map(([k,v])=>`<span class="pill">${k} ${v}</span>`).join("")}
    </div>
    ${D.calibration ? `<div class="note" style="margin-top:8px">
      <b>概率校准（Platt）</b>：Brier ${D.calibration.brier_raw} → <b>${D.calibration.brier_calibrated}</b>
      <span class="pill">AUC 95%CI ${D.calibration.auc_ci95[0]}–${D.calibration.auc_ci95[1]}</span>
    </div>` : ""}`;

  /* ---------------- 来源与免责 ---------------- */
  document.getElementById("sources").innerHTML = `
    <b>数据来源</b>：<br>${D.meta.sources.map(s => "· " + s).join("<br>")}
    <br><br><b>方法</b>：Open-Meteo 逐日气象 → 农业气象指标（有效积温/霜冻/倒春寒/高温/水分亏缺/连阴雨）→ numpy GBDT 复合风险识别 → 透明规则采摘适宜度 → 白话行动建议（DeepSeek / 规则后备）。
    <br><br><span style="color:#e5534b">免责声明：</span>${D.meta.disclaimer}`;

  document.getElementById("foot").textContent =
    "TeaWindow · AI4Climate 全球青年气候解决方案挑战赛 · 赛道01 梅家坞气候智慧茶园 · 本页为离线单文件 Demo，数据已内嵌。";
})();
