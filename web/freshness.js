/* 实时新鲜度徽标：读 /api/ready；过期(>25min)自动触发"按需刷新"，刷新中显示进度，完成后自动重载一次 */
(function () {
  var el = document.getElementById("freshness");
  if (!el) return;
  var lastAsk = 0, timer = null, reloaded = false;

  function sget(k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } }
  function sset(k, v) { try { sessionStorage.setItem(k, v); } catch (e) { /* ignore */ } }
  function sdel(k) { try { sessionStorage.removeItem(k); } catch (e) { /* ignore */ } }

  function paint(age, stale, running) {
    var a = (age == null ? "-" : Math.round(age));
    var txt;
    if (running) {
      txt = "\u23f3 正在刷新数据…（约 1–2 分钟）" + (age == null ? "" : " · 当前 " + a + " 分钟前");
    } else if (stale) {
      txt = "\u26a0\ufe0f 数据约 " + a + " 分钟前（已触发自动刷新，稍后自动更新）";
    } else {
      txt = "\u25cf 数据约 " + a + " 分钟前更新 · 有访问时自动保持新鲜";
    }
    el.textContent = txt + "（上游预报逐小时）";
    el.style.color = running ? "#d29922" : (stale ? "#e5534b" : "#3fb950");
  }

  function schedule(ms) {
    clearTimeout(timer);
    timer = setTimeout(tick, ms);
  }

  function tick() {
    fetch("api/ready", { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (d) {
      var age = d.age_minutes, stale = d.stale === true;
      var running = (d.refresh || {}).status === "running";
      paint(age, stale, running);

      if (running) { schedule(10000); return; }

      if (stale) {
        sset("tw_was_stale", "1");
        if (Date.now() - lastAsk > 5 * 60 * 1000) {
          lastAsk = Date.now();
          fetch("api/refresh/auto", { method: "POST" }).catch(function () {});
          paint(age, stale, true);
        }
        schedule(10000);
        return;
      }

      /* 打开时是过期数据、现在已刷新完成 → 自动重载一次，让图表用上新数据 */
      if (!reloaded && age != null && age < 10 && sget("tw_was_stale") === "1") {
        reloaded = true;
        sdel("tw_was_stale");
        location.reload();
        return;
      }
      schedule(60000);
    }).catch(function () {
      el.textContent = "新鲜度：离线";
      schedule(60000);
    });
  }

  tick();
  fetch("api/refresh/auto", { method: "POST" }).catch(function () {});   /* 打开页面即预热/按需刷新 */
})();
