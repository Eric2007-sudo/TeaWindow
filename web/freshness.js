/* 实时新鲜度徽标：每 60s 读 /api/health；超过 25 分钟自动触发一次"按需刷新"（自愈） */
(function () {
  var el = document.getElementById("freshness");
  if (!el) return;
  var lastAsk = 0;
  function tick() {
    fetch("api/health", { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (h) {
      var a = (h.age_minutes == null ? "-" : h.age_minutes);
      el.textContent = (h.stale ? "\u26a0\ufe0f 数据约 " + a + " 分钟前（正在自动刷新…）"
                                : "\u25cf 数据约 " + a + " 分钟前更新 · 有访问时自动保持新鲜")
        + "（上游预报逐小时）";
      el.style.color = h.stale ? "#e5534b" : "#3fb950";
      if (h.age_minutes != null && h.age_minutes > 25 && Date.now() - lastAsk > 15 * 60 * 1000) {
        lastAsk = Date.now();
        fetch("api/refresh/auto", { method: "POST" }).catch(function () {});
      }
    }).catch(function () { el.textContent = "新鲜度：离线"; });
  }
  tick();
  setInterval(tick, 60000);
  fetch("api/refresh/auto", { method: "POST" }).catch(function () {});   // 打开页面即预热/按需刷新
})();