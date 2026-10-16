/* 梅坞采候 TeaWindow — 仪表盘逻辑（在线读 /api/overview，失败回退内嵌 data.js） */
(async function () {
  let D = window.TW_DATA;              // 离线内嵌数据（data.js）
  let online = false;
  try {                                 // 在线模式：优先实时 API
    const r = await fetch("api/overview", { cache: "no-store" });
    if (r.ok) { D = await r.json(); online = true; }
  } catch (e) { /* 离线：忽略，使用内嵌数据 */ }
  if (!D) { alert("数据未加载：在线需 /api/overview，离线需 data.js"); return; }
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const days = D.days;
  const hist = days.filter(d => d.source === "history");
  const todayIsoCN = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Shanghai" });
  const fc = days.filter(d => d.source === "forecast" && d.date >= todayIsoCN);   // 未来窗口仅今天起
  const byDate = {}; days.forEach(d => byDate[d.date] = d);
  const RISK = { "低": "#3fb950", "中": "#d6b657", "高": "#e08a3c", "极高": "#e5534b" };
  const md = s => (s || "").slice(5);
  const fmt = v => (v === null || v === undefined) ? "–" : v;

  document.getElementById("hdr-meta").textContent =
    `坐标 ${D.meta.lat}°N, ${D.meta.lon}°E · 更新时间 ${D.meta.updated} · 历史 ${hist.length} 天 + 预报 ${fc.length} 天`;

  /* ---------------- KPI 卡片 ---------------- */
  const today = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Shanghai" });
  let cur = days.find(d => d.date === today)
         || [...days].reverse().find(d => d.date <= today)
         || hist[hist.length - 1];
  const next7 = fc.slice(0, 7);
  const maxRisk7 = next7.reduce((a, b) => (b.risk_R > a.risk_R ? b : a), next7[0] || cur);
  const win = D.pick_window[0] || {};
  const m = D.metrics;
  const riskType = [
    (cur.frost || cur.cold_shock) ? "霜冻/倒春寒" : null,
    cur.heat ? "高温" : null,
    ((cur.dry_run || 0) >= 5 || (cur.deficit || 0) >= 45) ? "干旱/水分" : null,
    (cur.wet_run || 0) >= 4 ? "连阴雨" : null
  ].filter(Boolean).join("、") || "无明显主导风险";
  const ageDays = Math.round((new Date(today) - new Date(cur.date)) / 86400000);
  const offSeason = D.meta && D.meta.season === "off";
  const cards = [
    { k: "最近研判日风险", v: `<span class="badge b${cur.risk_level}">${cur.risk_level}</span>`,
      s: `${cur.date} · R ${(cur.risk_R).toFixed(2)} · 适宜度 ${cur.suitability} · ${riskType}` },
    { k: "未来 7 天最高风险", v: `<span class="badge b${maxRisk7.risk_level}">${maxRisk7.risk_level}</span>`,
      s: `${maxRisk7.date} · 风险度 ${(maxRisk7.risk_R).toFixed(2)}` },
    { k: offSeason ? "非春采期（养护为主）" : "推荐采摘窗口",
      v: offSeason ? "—" : (win.date || "–").slice(5),
      s: offSeason ? "春采季 3–4 月；当前以防冻/防旱/排涝等养护为主" : `适宜度 ${fmt(win.suitability)} · 风险 ${win.risk_level || "–"}` },
    offSeason
      ? { k: "今日行动建议", v: "养护", s: "防冻/防旱/排涝巡查 + 修剪/施肥/越冬准备（非春采期）" }
      : { k: "今日行动建议", v: (D.decision && D.decision.days && D.decision.days[0]) ? D.decision.days[0].recommend : "–",
          s: `最佳采摘日 ${D.decision ? (D.decision.best_pick_day || "–") : "–"}` }
  ];
  const notes = [];
  if (!online) notes.push(`<div class="card" style="grid-column:1/-1;border-color:#e08a3c"><div class="k">数据来源</div><div class="v" style="font-size:15px;color:#e08a3c">⚠️ 离线/缓存（演示）数据，非实时；行动建议请以在线服务与官方预警为准</div></div>`);
  const fetched = (D.meta && (D.meta.fetched_at || D.meta.updated)) || "";
  let ageMin = null;
  if (fetched) { const t = new Date(String(fetched).replace(" ", "T")); if (!isNaN(t)) ageMin = Math.round((Date.now() - t) / 60000); }
  if (ageMin != null && ageMin > 90) notes.push(`<div class="card" style="grid-column:1/-1;border-color:#e5534b"><div class="k">数据新鲜度</div><div class="v" style="font-size:15px;color:#e5534b">⚠️ 数据约 ${ageMin} 分钟前获取（可能已过期）；请以最新预报与官方预警为准</div></div>`);
  else if (ageMin != null) notes.push(`<div class="card" style="grid-column:1/-1;border-color:#3fb950"><div class="k">数据新鲜度</div><div class="v" style="font-size:15px;color:#3fb950">数据约 ${ageMin} 分钟前更新 · 服务每 10 分钟自动刷新（上游预报逐小时更新）</div></div>`);
  if (ageDays > 2) notes.push(`<div class="card" style="grid-column:1/-1;border-color:#e5534b"><div class="k">数据时效</div><div class="v" style="font-size:15px;color:#e5534b">⚠️ 数据日 ${cur.date}（已 ${ageDays} 天），行动建议请谨慎，以实况与官方预警为准</div></div>`);
  if (offSeason) notes.push(`<div class="card" style="grid-column:1/-1;border-color:#4aa8ff"><div class="k">季节提示</div><div class="v" style="font-size:15px;color:#cfe0ee">当前为非春采期（春采季 3–4 月）：采摘窗口/排班仅供参考，请以园间养护为主</div></div>`);
  document.getElementById("cards").innerHTML = notes.join("") + cards.map(c =>
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
      <td>${esc(p.name)}</td><td>${esc(p.elev_m)}</td><td>${esc(p.slope_deg)}°</td><td>${esc(p.aspect_deg)}°</td>
      <td><span class="badge b${esc(p.frost_risk)}">${esc(p.frost_risk)}</span></td></tr>`).join("");
    document.getElementById("terrain-note").textContent =
      D.terrain.method + " " + D.terrain.disclaimer;
  }

  /* ---------------- 采摘调度 ---------------- */
  if (D.schedule && D.schedule.mode === "care") {
    document.querySelector("#schedTable tbody").innerHTML =
      '<tr><td colspan="4">非春采期：不生成采摘排班，转为园间养护。</td></tr>';
    document.getElementById("sched-note").textContent =
      "养护任务：" + ((D.schedule.care || []).join("、") || "防冻/防旱/排涝、修剪、施肥、越冬准备");
  } else if (D.schedule && D.schedule.schedule) {
    document.querySelector("#schedTable tbody").innerHTML = D.schedule.schedule.map(s => `<tr>
      <td>${esc(s.date)}</td><td>${esc(s.suitability)}</td>
      <td><span class="badge b${esc(s.risk_level)}">${esc(s.risk_level)}</span></td>
      <td>${s.plots.map(p => `${esc(p.name)}<span class="tag">(${esc(p.reason)})</span>`).join("、") || "–"}</td>
    </tr>`).join("");
    const pr = D.schedule.priority.map(p => `<span class="pill">${p.name} 易感${p.frost_risk}</span>`).join("");
    document.getElementById("sched-note").innerHTML =
      `${D.schedule.method} 每日产能 ${D.schedule.capacity_per_day} 个地块。<br>抢采优先级：${pr}`;
  }

  /* ---------------- 决策建议（期望效用） ---------------- */
  if (D.decision && D.decision.mode === "care") {
    document.querySelector("#decTable tbody").innerHTML =
      '<tr><td colspan="6">非春采期：不生成采摘决策（抢采/等待/防护），转为养护建议。</td></tr>';
    document.getElementById("dec-note").textContent = D.decision.task || "以园间养护为主。";
  } else if (D.decision && D.decision.days && D.decision.days.length) {
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

  /* ---------------- 天气指数保险 ---------------- */
  if (D.insurance && D.insurance.series) {
    document.querySelector("#insTable tbody").innerHTML = D.insurance.series.map(r => `<tr>
      <td>${r.year}</td><td>${r.frost_index}</td><td>${r.heat_index}</td>
      <td>${r.payout > 0 ? '<b>' + r.payout + '</b>' : '0'}</td></tr>`).join("");
    document.getElementById("ins-note").textContent =
      `【概念验证，非产品报价】触发阈值：霜冻 ${D.insurance.frost_threshold} 度日 / 高温 ${D.insurance.heat_threshold} 天；` +
      `历史赔付年 ${D.insurance.fire_years}/${D.insurance.n_years}；公平保费≈${D.insurance.fair_premium_per_mu} 元/亩（与政策性补贴保费的保障范围/口径不同，不可直接比较）。详见 report/index_insurance.md。`;
  }

  /* ---------------- 预报表格 ---------------- */
  const tb = document.querySelector("#fcTable tbody");
  const _fct = document.getElementById("fcTitle"); if (_fct) _fct.textContent = `未来 ${fc.length} 天预报与行动建议`;
  tb.innerHTML = fc.map(d => `<tr class="fc-row">
    <td data-label="日期">${d.date}<div class="tag">${"日一二三四五六"[new Date(d.date).getDay()]}</div></td>
    <td data-label="风险"><span class="badge b${d.risk_level}">${d.risk_level}</span></td>
    <td data-label="适宜度">${d.suitability}</td>
    <td data-label="Tmax/Tmin">${d.tmax}° / ${d.tmin}°</td>
    <td data-label="降水">${d.precip} mm</td>
    <td data-label="霜冻/高温概率">${d.p_frost != null ? (100 * d.p_frost).toFixed(0) + "% / " + (100 * d.p_heat).toFixed(0) + "%" : "–"}</td>
    <td data-label="建议" class="adv">${esc(d.advice || "")}<div class="tag">来源：${d.advice_source === "deepseek-chat" ? "DeepSeek" : "TeaWindow 自研规则"}</div></td>
  </tr>`).join("");

  /* ---------------- 模型指标 ---------------- */
  document.getElementById("metrics").innerHTML = `
    <div class="note" style="color:#e0b34c;margin-bottom:8px">
      ⚠️ 下表为<b>弱标签复现指标</b>：标签由专家农艺规则生成，模型用相近特征预测这些标签，
      AUC 高主要说明"能复现规则"，<b>不代表真实灾害预测准确率</b>；真实效果需田间验证。
    </div>
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

  /* ---------------- 数据版本 / 实时更新（公开只读） ---------------- */
  async function renderVersion() {
    try {
      const r = await fetch("api/data/versions?limit=1", { cache: "no-store" });
      if (!r.ok) return;
      const v = (await r.json()).versions?.[0];
      if (!v) return;
      const el = document.createElement("div");
      el.className = "note";
      el.style.marginTop = "8px";
      el.textContent = "数据版本 v" + v.id + " · 抓取 " + (v.fetched_at || v.ts || "-") +
        " · 源 " + (v.source || "-") + " · 快照hash " + String(v.raw_sha256 || "").slice(0, 12) +
        " · 构建 " + (v.build || "-");
      document.getElementById("sources").appendChild(el);
    } catch (e) { /* ignore */ }
  }
  renderVersion();
/* ---------------- 实时传感器（公开只读，20s 轮询） ---------------- */
  async function renderSensor() {
    const box = document.getElementById("sensorCards");
    if (!box) return;
    try {
      const r = await fetch("api/realtime", { cache: "no-store" });
      const d = await r.json();
      const st = d.stations || {};
      const keys = Object.keys(st);
      if (!keys.length) {
        box.innerHTML = '<div class="note">' + ((d.message || "尚未接入现场传感器") + '。可通过 <a href="sensor.html">sensor.html</a> 或 POST /api/sensor 接入。') + '</div>';
        document.getElementById("sensor-note").textContent = "现场传感器：" + (d.status === "no_sensors" ? "尚未接入（0 个站点）" : "暂无数据");
        return;
      }
      box.innerHTML = keys.map(k => {
        const x = st[k]; const parts = [];
        if (x.temp != null) parts.push(`${x.temp}℃`);
        if (x.rh != null) parts.push(`RH ${x.rh}%`);
        if (x.soil_moisture != null) parts.push(`土湿 ${x.soil_moisture}`);
        if (x.precip != null) parts.push(`雨 ${x.precip}mm`);
        return `<div class="card"><div class="k">${esc(k)}</div><div class="v" style="font-size:18px">${parts.join(" · ") || "–"}</div><div class="s">${esc(x.ts || "")}</div></div>`;
      }).join("");
      document.getElementById("sensor-note").textContent = `共 ${d.n} 条上报 · 最新观测 ${d.latest_observation_at || "–"} · 服务时间 ${d.server_time || d.updated}（仅数值，公开只读）`;
    } catch (e) { box.innerHTML = '<div class="note">（离线或服务不可用）</div>'; }
  }
  renderSensor();
  setInterval(() => { if (!document.hidden) renderSensor(); }, 15000);
})();
