/* TeaWindow 自播放演示（外部脚本，配合 CSP script-src 'self'） */
(function () {
  "use strict";
  const D = (typeof window !== "undefined" && window.TW_DATA) ? window.TW_DATA : null;
  const auc = D ? (D.metrics && D.metrics.ml ? D.metrics.ml.auc : "0.998") : "0.998";
  const f1 = D ? (D.metrics && D.metrics.ml ? D.metrics.ml.f1 : "0.854") : "0.854";

  const slides = [
    { hero: true, title: "梅坞采候 TeaWindow",
      sub: "梅家坞（西湖龙井核心产区）· 龙井 43 号「倒春寒 × 高温」复合风险预警与采摘窗口决策助手",
      kpis: ["AI4Climate 赛道 01", "One Place · One Climate Problem · One AI Solution", "在线 Demo + 开源仓库"] },
    { title: "问题：真实且有证据", img: "demo_assets/fig_yearly.png",
      cap: "梅家坞七成茶园为特早生、抗旱弱的龙井 43 号；逐年霜冻/倒春寒/高温天数清晰可见。" },
    { title: "方案：把信号变成行动", img: "demo_assets/dashboard.png",
      cap: "气象 + 遥感 + 地形 → 复合风险等级 → 采摘适宜度与最佳窗口 → 茶农白话建议（离线/在线双形态）。" },
    { title: "AI 为什么必要", img: "demo_assets/fig_importance.png",
      cap: "纯 numpy 梯度提升树融合多变量与交互项；留出年 AUC " + auc + " / F1 " + f1 + "，显著优于单阈值基线（AUC 0.78 / F1 0.50）。" },
    { title: "从预测到决策（新颖点）", img: "demo_assets/dashboard.png",
      cap: "预测之上再加：采摘调度排班 + 决策论期望效用(抢采/等待/防护) + 价值闭环(预期损失/保费) + 天气指数保险。" },
    { title: "天气指数保险", img: "demo_assets/fig_insurance.png",
      cap: "客观气候指数触发自动赔付；历史赔付年 7/12、公平保费≈1000 元/亩，支持地块级差异化定价。" },
    { title: "智能问答（自研引擎）", img: "demo_assets/chat.png",
      cap: "口语提问「明天该采哪块地」→ 自研意图分类（ONNX）+ 接地生成 + 来源链；可选 DeepSeek 润色。" },
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