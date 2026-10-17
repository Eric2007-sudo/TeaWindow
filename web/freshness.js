/* 实时新鲜度徽标：每 60s 读 /api/health；若已过期则自动触发一次"按需刷新"（自愈） */
(function () {
  var el = document.getElementById("freshness");
  if (!el) return;
  var asked = false;
  function tick() {
    fetch("api/health", { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (h) {
      var a = (h.age_minutes == null ? "-" : h.age_minutes);
      el.textContent = h.stale ? ("\u26a0\ufe0f 数据约 " + a + " 分钟前（正在自动刷新…）")
                              : ("\u25cf 新鲜 · " + a + " 分钟前更新 · 约每 15 分钟自动刷新");
      el.style.color = h.stale ? "#e5534b" : "#3fb950";
      if (h.stale && !asked) {
        asked = true;
        fetch("api/refresh/auto", { method: "POST" }).catch(function () {});
      }
    }).catch(function () { el.textContent = "新鲜度：离线"; });
  }
  tick();
  setInterval(tick, 60000);
  fetch("api/refresh/auto", { method: "POST" }).catch(function () {});   // 打开页面即预热/按需刷新
})();