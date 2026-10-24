/* TeaWindow 自播放演示（外部脚本，配合 CSP script-src 'self'） */
(function () {
  "use strict";
  const D = (typeof window !== "undefined" && window.TW_DATA) ? window.TW_DATA : null;
  const auc = D ? (D.metrics && D.metrics.ml ? D.metrics.ml.auc : "0.998") : "0.998";
  const f1 = D ? (D.metrics && D.metrics.ml ? D.metrics.ml.f1 : "0.854") : "0.854";

  const slidesCN = [
    { hero: true, title: "梅坞采候 TeaWindow",
      sub: "梅家坞（西湖龙井核心产区）· 龙井 43 号「倒春寒 × 高温」复合风险预警与采摘窗口决策助手",
      kpis: ["AI4Climate 赛道 01", "One Place · One Climate Problem · One AI Solution", "在线 Demo + 开源仓库"] },
    { title: "问题：真实且有证据", img: "demo_assets/fig_yearly.png",
      cap: "梅家坞七成茶园为特早生、抗旱弱的龙井 43 号；逐年霜冻/倒春寒/高温天数清晰可见。" },
    { title: "方案：把信号变成行动", img: "demo_assets/dashboard.png",
      cap: "气象（Open-Meteo ERA5 历史 + MET Norway 预报，双源互备）+ 遥感 + 地形 → 复合风险等级 → 采摘适宜度与最佳窗口 → 茶农白话建议（离线/在线双形态）。" },
    { title: "AI 为什么必要", img: "demo_assets/fig_importance.png",
      cap: "纯 numpy 梯度提升树融合多变量与交互项；留出年 AUC " + auc + " / F1 " + f1 + "，显著优于单阈值基线（AUC 0.78 / F1 0.50）。" },
    { title: "从预测到决策（新颖点）", img: "demo_assets/dashboard.png",
      cap: "预测之上再加：采摘调度排班 + 决策论期望效用(抢采/等待/防护) + 价值闭环(预期损失/保费) + 天气指数保险。" },
    { title: "天气指数保险", img: "demo_assets/fig_insurance.png",
      cap: "客观气候指数触发自动赔付；历史赔付年 7/12、公平保费≈1000 元/亩，支持地块级差异化定价。" },
    { title: "智能问答（自研引擎）", img: "demo_assets/chat.png",
      cap: "口语提问 → 自训意图分类（ONNX）+ 事实接地生成 + 来源链；支持多维复合提问分项作答、JSON/表格跨轮一致、任务引用与记忆；可选 DeepSeek 润色。" },
    { title: "运行与告警闭环", img: "demo_assets/dashboard.png",
      cap: "约每 15 分钟自动刷新 + 无访问 20 分钟自愈；上游漂移检测与数据陈旧降级；业务就绪 decision_ready；告警（过期/漂移/无传感器）经钉钉加签真实送达。" },
    { title: "地块级：新增功能与用法", img: "demo_assets/terrain.png",
      cap: "打开「地块风险图」→ 点任意位置自动生成该点数据（海拔/坡向/下推 Tmin·Tmax/风险 R/建议）→ 追问「这块地未来 3 天怎么管」或打印「地块体检卡」；支持多站传感器与地块边界。" },
    { title: "地块风险图：看什么", img: "demo_assets/terrain.png",
      cap: "五档图层（综合/霜冻/高温/干旱/仅地形）；DEM 山体阴影 + 等高线 + 200m 比例尺 + 指北针；黄色虚线是 OSM 参考地块边界，蓝点是已登记传感器站点。" },
    { title: "点选生成数据：字段与算法", img: "demo_assets/terrain.png",
      cap: "点任意位置返回：海拔/坡度/坡向；按海拔递减率（约 −0.65℃/100m）+ 低洼冷池与坡向修正，得到该点下推 Tmin/Tmax；再用同一套风险规则算 R 与等级，并给一句建议。" },
    { title: "地块体检卡：一页看懂", img: "demo_assets/plot_report.png",
      cap: "含地块坐标/海拔/坡向、当日 R 与下推温度、未来 3 天逐日（Tmin/Tmax/雨/R/等级）、建议，以及数据版本/上游 URL/SHA；右上角一键打印或存 PDF。" },
    { title: "地块多日问答：示例", img: "demo_assets/chat.png",
      cap: "问「这块地未来 3 天怎么管」→ 逐日：10-17 Tmin16.7/Tmax29.4℃ R=0.57；10-18 R=0.65；10-19 R=0.73，并给重点日与建议；与单日问答使用同一算法，链里带地块上下文。" },
    { title: "多站传感器：怎么接", img: "demo_assets/dashboard.png",
      cap: "POST /api/station 登记任意 station_id + 地块坐标；POST /api/sensor 上报（按 station_id+ts 幂等）；可选设备令牌 + HMAC 签名 + nonce 防重放；地图即时显示站点标记。" },
    { title: "可追溯与新鲜度", img: "demo_assets/mobile.png",
      cap: "无访问 20 分钟自动刷新；每个数据版本记录上游 URL/参数/完整 SHA-256；问答来源链带「地块上下文」；/api/ready 返回 decision_ready，过期自动降级为核验。" },
    { title: "众包物候闭环", img: "demo_assets/report.png",
      cap: "茶农上报开采/灾情 → 自动复校 GDD 阈值，形成『数据飞轮』。" },
    { title: "遥感：植被活力", img: "demo_assets/fig_ndvi_temp.png",
      cap: "接续 NASA GIBS MODIS NDVI（颜色近似反演）与 Sentinel-2 场景；作为长势背景信号。" },
    { title: "一手观测：台站交叉验证", img: "demo_assets/fig_station.png",
      cap: "Meteostat 杭州站 4303 天真实观测；温度相关 0.98–0.99，偏差反映梅家坞山谷的微气候差异。" },
    { title: "真实事件回测", img: "demo_assets/fig_backtest.png",
      cap: "2016 寒潮、2018 冰冻、2020/2022/2024 高温、2024 春霜、2025 倒春寒：事件级命中 7/7。" },
    { title: "移动端与离线", img: "demo_assets/mobile.png",
      cap: "响应式适配手机；离线单页双击即开，适合田间使用与演示视频录制。" },
    { hero: true, title: "ONE PLACE · ONE CLIMATE PROBLEM · ONE AI SOLUTION",
      sub: "梅坞采候，让 AI 走进真实茶园。",
      kpis: ["https://teawindow.onrender.com", "https://eric2007-sudo.github.io/TeaWindow/"] },
  ];


  const slidesEN = [
    { hero: true, title: "TeaWindow",
      sub: "Meijiawu, West Lake Longjing core area · compound risk (late frost x heat) and picking-window decision assistant for Longjing 43",
      kpis: ["AI4Climate Track 01", "One Place · One Climate Problem · One AI Solution", "Live demo + open-source repo"] },
    { title: "Problem: real and verifiable", img: "demo_assets/fig_yearly.png",
      cap: "About 70% of Meijiawu tea gardens grow early-budding, drought-sensitive Longjing 43; frost and heat days vary sharply by year." },
    { title: "Solution: turn signals into action", img: "demo_assets/dashboard.png",
      cap: "Weather (Open-Meteo ERA5 + MET Norway, dual source) + remote sensing + terrain -> compound risk -> picking suitability and window -> plain-language advice, online and offline." },
    { title: "Why AI is necessary", img: "demo_assets/fig_importance.png",
      cap: "A numpy gradient-boosted tree fuses multivariate thresholds and interactions; hold-out AUC " + auc + " / F1 " + f1 + ", clearly above the single-threshold baseline (0.78 / 0.50)." },
    { title: "From forecast to decision", img: "demo_assets/dashboard.png",
      cap: "Beyond prediction: picking schedule, expected-value decision (harvest / wait / protect), value closure (expected loss, premium) and weather index insurance." },
    { title: "Weather index insurance", img: "demo_assets/fig_insurance.png",
      cap: "An objective climate index triggers automatic payout; 7 of 12 historical years would pay, fair premium about CNY 1,000 per mu, with plot-level pricing." },
    { title: "Q&A engine (self-built)", img: "demo_assets/chat.png",
      cap: "Spoken question -> ONNX intent classifier -> grounded generation with a source chain; multi-intent questions, JSON/table consistency, task references and memory; optional DeepSeek polish." },
    { title: "Ops and alert loop", img: "demo_assets/dashboard.png",
      cap: "About 15-minute refresh plus self-healing after 20 minutes idle; upstream drift detection; decision_ready gate; signed DingTalk alerts." },
    { title: "Plot level: new features", img: "demo_assets/terrain.png",
      cap: "Open the terrain map, click any point to generate elevation, aspect, downscaled Tmin/Tmax, risk R and advice; then ask for a 3-day plan or print a plot report card." },
    { title: "Terrain map: what you see", img: "demo_assets/terrain.png",
      cap: "Five layers (compound / frost / heat / drought / terrain only), DEM hillshade, contours, 200 m scale and north arrow; OSM reference parcels; sensor stations." },
    { title: "Click to generate: fields and algorithm", img: "demo_assets/terrain.png",
      cap: "Each point returns elevation, slope and aspect; a lapse rate plus cold-pool and aspect correction yields downscaled Tmin/Tmax; the same risk rules produce R, level and one sentence of advice." },
    { title: "Plot report card", img: "demo_assets/plot_report.png",
      cap: "Coordinates, elevation and aspect, risk R, downscaled temperatures, a 3-day outlook, advice, plus data version, upstream URL and SHA-256; print or save as PDF." },
    { title: "Plot-level Q&A", img: "demo_assets/chat.png",
      cap: "Ask how to manage this plot for the next three days: per-day Tmin, Tmax, rain, R and level, using the same algorithm as single-day answers, with plot context in the source chain." },
    { title: "Multi-station sensors", img: "demo_assets/dashboard.png",
      cap: "Register any station via POST /api/station and report via POST /api/sensor; optional device key, HMAC signature and nonce; stations appear on the map." },
    { title: "Traceability and freshness", img: "demo_assets/mobile.png",
      cap: "Self-healing refresh after 20 minutes idle; every data version records upstream URL, parameters and full SHA-256; the source chain includes plot context; /api/ready exposes decision_ready." },
    { title: "Crowdsourced phenology", img: "demo_assets/report.png",
      cap: "Farmers report harvest dates and damage; thresholds are recalculated automatically, forming a data flywheel." },
    { title: "Remote sensing", img: "demo_assets/fig_ndvi_temp.png",
      cap: "NASA GIBS MODIS NDVI and Sentinel-2 scenes provide growth context." },
    { title: "Ground truth: station cross-check", img: "demo_assets/fig_station.png",
      cap: "Meteostat Hangzhou: 4,303 days of observations; correlation 0.98 to 0.99; the bias reflects the valley microclimate." },
    { title: "Historical events", img: "demo_assets/fig_backtest.png",
      cap: "2016 cold wave, 2018 freeze, 2020/2022/2024 heat, 2024 spring frost, 2025 late frost: 7 of 7 events detected." },
    { title: "Mobile and offline", img: "demo_assets/mobile.png",
      cap: "Responsive on phones; a single offline page opens with a double click, for field use." },
    { hero: true, title: "ONE PLACE · ONE CLIMATE PROBLEM · ONE AI SOLUTION",
      sub: "TeaWindow: bringing AI into a real tea garden",
      kpis: ["https://teawindow.onrender.com", "https://eric2007-sudo.github.io/TeaWindow/"] },
  ];

  const slides = (new URLSearchParams(location.search).get("lang") === "en") ? slidesEN : slidesCN;

  const stage = document.getElementById("stage");
  const bar = document.getElementById("bar");
  let i = 0, playing = true, DUR = 8000, elapsed = 0;

  const q = new URLSearchParams(location.search);
  if (q.has("slide")) { i = Math.max(0, Math.min(slides.length - 1, parseInt(q.get("slide"), 10) || 0)); playing = false; }
  if (q.get("clean") === "1") { bar.style.display = "none"; document.getElementById("hud").style.display = "none"; }

  function render() {
    const s = slides[i];
    let html = "";
    if (s.hero) {
      html = '<div class="hero"><div class="big">' + s.title + '</div><div class="sub">' + (s.sub || "") + "</div>" +
        '<div class="kpi">' + (s.kpis || []).map((k) => "<span>" + k + "</span>").join("") + "</div></div>";
    } else {
      html = "<h1>" + s.title + "</h1>" + (s.img ? '<img src="' + s.img + '" alt="">' : "") + '<div class="cap">' + (s.cap || "") + "</div>";
    }
    stage.innerHTML = html;
    elapsed = 0;
  }
  function next() { i = (i + 1) % slides.length; render(); }
  function prev() { i = (i - 1 + slides.length) % slides.length; render(); }
  function tick() {
    if (playing) { elapsed += 40; }
    bar.style.width = Math.min(100, elapsed / DUR * 100) + "%";
    if (elapsed >= DUR) { next(); }
  }
  setInterval(tick, 40);
  document.addEventListener("keydown", (e) => {
    if (e.code === "Space") { playing = !playing; e.preventDefault(); }
    if (e.code === "ArrowRight") { next(); }
    if (e.code === "ArrowLeft") { prev(); }
  });
  stage.addEventListener("click", () => next());
  render();
})();