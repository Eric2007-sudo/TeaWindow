(function () {
  "use strict";
  var $ = function (s) { return document.querySelector(s); };
  var G = null, SITE = null, STATIONS = [], METRIC = "risk", PARCELS = null, SHOW_PARCELS = true;
  var map = $("#map"), cv = $("#cv"), lyr = $("#lyr"), tip = $("#tip");

  function cls(v) { return v >= 0.75 ? "极高" : v >= 0.6 ? "高" : v >= 0.4 ? "中" : "低"; }
  function clsSpan(c) { return (c === "高" || c === "极高") ? "hi" : (c === "中" ? "mid" : "lo"); }
  function colorFor(v) {
    var r = Math.max(0, Math.min(1, (v - 0.5) * 2)), g = Math.max(0, Math.min(1, 1 - Math.abs(v - 0.5) * 2)), b = Math.max(0, Math.min(1, (0.5 - v) * 2));
    return "rgba(" + Math.round(r * 255) + "," + Math.round(g * 255) + "," + Math.round(b * 255) + ",0.72)";
  }
  function metricOf(c, m) {
    if (!SITE || c.dtmin == null) return c.R;
    var tmin = SITE.tmin + c.dtmin, tmax = (SITE.tmax || 30) + c.dtmax;
    var fs = Math.max(0, Math.min(1, (2 - tmin) / 4));
    var hs = Math.max(0, Math.min(1, (tmax - 33) / 5));
    var ds = (c.drought || 0) * 0.6;
    if (m === "frost") return fs;
    if (m === "heat") return hs;
    if (m === "drought") return ds;
    return Math.max(fs, hs, ds);
  }
  function nearest(lon, lat) {
    var best = null, bd = 1e9;
    for (var i = 0; i < G.cells.length; i++) {
      var c = G.cells[i], d = (c.lon - lon) * (c.lon - lon) + (c.lat - lat) * (c.lat - lat);
      if (d < bd) { bd = d; best = c; }
    }
    return best;
  }

  function render() {
    if (!G) return;
    try { renderCanvas(); } catch (e) { $("#method").textContent = "绘制失败：" + e; }
    try { renderTop(); } catch (e) { $("#method").textContent = "清单失败：" + e; }
  }
  function renderCanvas() {
    var img = map.querySelector("img.ph");
    var W = (img && img.clientWidth) || map.clientWidth, H = (img && img.clientHeight) || map.clientHeight;
    if (!W || !H) return;
    cv.width = W; cv.height = H;
    var ctx = cv.getContext("2d");
    ctx.clearRect(0, 0, W, H);
    if (METRIC === "hill") return;
    var nx = G.nx, ny = G.ny, cw = W / nx, ch = H / ny;
    if (!nx || !ny || G.cells.length !== nx * ny) {   // 兜底
      nx = Math.max(1, Math.round(Math.sqrt(G.cells.length * (W / H))));
      ny = Math.ceil(G.cells.length / nx); cw = W / nx; ch = H / ny;
    }
    for (var j = 0; j < ny; j++) {
      for (var i = 0; i < nx; i++) {
        var c = G.cells[j * nx + i];
        if (!c) continue;
        ctx.fillStyle = colorFor(metricOf(c, METRIC));
        ctx.fillRect(i * cw, j * ch, cw + 1, ch + 1);
      }
    }
    STATIONS.forEach(function (s) {
      if (s.lat == null || s.lon == null) return;
      var x = (s.lon - G.bbox[0]) / (G.bbox[2] - G.bbox[0]) * W;
      var y = (G.bbox[3] - s.lat) / (G.bbox[3] - G.bbox[1]) * H;
      if (x < 0 || x > W || y < 0 || y > H) return;
      ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2);
      ctx.fillStyle = "#4aa8ff"; ctx.fill(); ctx.lineWidth = 1.5; ctx.strokeStyle = "#0b1219"; ctx.stroke();
    });
    // 地块边界（OSM 参考）+ 地块名
    if (SHOW_PARCELS && PARCELS) {
      ctx.save();
      ctx.setLineDash([5, 4]); ctx.lineWidth = 1.4; ctx.strokeStyle = "rgba(255,209,102,.95)";
      (PARCELS.parcels || []).forEach(function (p) {
        var r = p.ring || []; if (r.length < 4) return;
        ctx.beginPath();
        r.forEach(function (pt, i) {
          var x = (pt[0] - G.bbox[0]) / (G.bbox[2] - G.bbox[0]) * W;
          var y = (G.bbox[3] - pt[1]) / (G.bbox[3] - G.bbox[1]) * H;
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        });
        ctx.stroke();
      });
      ctx.setLineDash([]);
      ctx.font = "12px 'Microsoft YaHei',Segoe UI,sans-serif";
      (PARCELS.plots || []).forEach(function (pl) {
        var x = (pl.lon - G.bbox[0]) / (G.bbox[2] - G.bbox[0]) * W;
        var y = (G.bbox[3] - pl.lat) / (G.bbox[3] - G.bbox[1]) * H;
        if (x < 0 || x > W || y < 0 || y > H) return;
        ctx.lineWidth = 3; ctx.strokeStyle = "rgba(11,18,25,.9)"; ctx.strokeText(pl.name, x + 7, y - 6);
        ctx.fillStyle = "#ffe9a8"; ctx.fillText(pl.name, x + 7, y - 6);
      });
      ctx.restore();
    }
  }
  function renderTop() {
    var tb = $("#top").querySelector("tbody");
    tb.innerHTML = "";
    var arr = G.cells.map(function (c) { return { c: c, R: (metricOf(c, "risk") || 0) }; })
      .sort(function (a, b) { return b.R - a.R; }).slice(0, 8);
    arr.forEach(function (x) {
      var c = x.c, level = cls(x.R);
      var tr = document.createElement("tr"); tr.className = "click";
      tr.innerHTML = "<td>" + c.lon + ", " + c.lat + "</td><td>" + c.elev + " m</td><td>" +
        (x.R == null ? "-" : x.R.toFixed(2)) + "</td><td class='" + clsSpan(level) + "'>" + level + "</td>";
      tr.onclick = function () { ask(c, level); };
      tb.appendChild(tr);
    });
  }
  function renderStations() {
    var box = $("#stations");
    if (!STATIONS.length) {
      box.innerHTML = "现场传感器：<b>尚未登记</b>（支持多站；用 <code>POST /api/station</code> 登记地块站点，<code>POST /api/sensor</code> 上报）。";
      return;
    }
    box.innerHTML = "现场传感器 " + STATIONS.length + " 站：" + STATIONS.map(function (s) {
      return "<b>" + (s.name || s.station_id) + "</b>" + (s.plot ? "(" + s.plot + ")" : "") + (s.temp != null ? " " + s.temp + "℃" : "");
    }).join(" · ");
  }
  function ask(c, level) {
    var q = "地块(" + c.lon + ", " + c.lat + "，海拔" + c.elev + "m)当前" + level + "风险，今天该做什么？";
    location.href = "chat.html?q=" + encodeURIComponent(q);
  }

  function loadData() {
    fetch("terrain_grid.json", { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (g) {
      G = g;
      $("#method").textContent = g.method + "（分辨率≈" + g.res_m + " m/px）";
      render();
    }).catch(function (e) { $("#method").textContent = "地形数据未生成：" + e; });

    fetch("api/overview", { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (d) {
      var fc = (d.days || []).filter(function (x) { return x.source === "forecast"; });
      SITE = fc.length ? fc[0] : null;
      $("#base").innerHTML = "站点基准（" + (SITE ? SITE.date : "-") + "）：R=" + (SITE ? SITE.risk_R : "-") +
        "（" + (SITE ? SITE.risk_level : "-") + "）· Tmin " + (SITE ? SITE.tmin : "-") + "℃ · 更新 " +
        ((d.meta && d.meta.updated) || d.updated || "-") + "（每 60 秒自动刷新）";
      render();
    }).catch(function () {
      $("#base").textContent = "未能读取实时预报（显示网格内置 R）。";
      render();
    });

    fetch("api/sensors", { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (d) {
      STATIONS = d.stations || []; renderStations(); render();
    }).catch(function () {});

    fetch("terrain_parcels.json", { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (d) {
      PARCELS = d; render();
    }).catch(function () {});
  }

  function setMetric(m, btn) {
    METRIC = m;
    ["bRisk", "bFrost", "bHeat", "bDrought", "bHill"].forEach(function (id) { $("#" + id).classList.remove("on"); });
    btn.classList.add("on");
    lyr.style.display = "none";
    render();
  }
  $("#bRisk").onclick = function () { setMetric("risk", this); };
  $("#bFrost").onclick = function () { setMetric("frost", this); };
  $("#bHeat").onclick = function () { setMetric("heat", this); };
  $("#bDrought").onclick = function () { setMetric("drought", this); };
  $("#bHill").onclick = function () { setMetric("hill", this); };
  $("#bParcel").onclick = function () { SHOW_PARCELS = !SHOW_PARCELS; this.classList.toggle("on", SHOW_PARCELS); render(); };

  map.addEventListener("mousemove", function (e) {
    if (!G) return;
    var r = map.getBoundingClientRect();
    var fx = (e.clientX - r.left) / r.width, fy = (e.clientY - r.top) / r.height;
    if (fx < 0 || fx > 1 || fy < 0 || fy > 1) { tip.style.display = "none"; return; }
    var lon = G.bbox[0] + fx * (G.bbox[2] - G.bbox[0]), lat = G.bbox[3] - fy * (G.bbox[3] - G.bbox[1]);
    var c = nearest(lon, lat), R = metricOf(c, "risk");
    tip.style.display = "block"; tip.style.left = (e.clientX - r.left) + "px"; tip.style.top = (e.clientY - r.top) + "px";
    tip.innerHTML = "海拔 " + c.elev + " m · 坡度 " + c.slope + "° · 坡向 " + c.aspect + "°<br>综合风险 <b>" +
      cls(R) + "</b>（R=" + (R == null ? "-" : R.toFixed(2)) + "）" + (SITE && c.dtmin != null ? " · 下推 Tmin " + (SITE.tmin + c.dtmin).toFixed(1) + "℃" : "");
  });
  map.addEventListener("mouseleave", function () { tip.style.display = "none"; });
  map.addEventListener("click", function (e) {
    if (!G) return;
    var r = map.getBoundingClientRect();
    var fx = (e.clientX - r.left) / r.width, fy = (e.clientY - r.top) / r.height;
    var lon = G.bbox[0] + fx * (G.bbox[2] - G.bbox[0]), lat = G.bbox[3] - fy * (G.bbox[3] - G.bbox[1]);
    var box = $("#plotCard"); box.style.display = "block"; box.textContent = "正在生成该点数据…";
    fetch("api/plot?lat=" + lat.toFixed(5) + "&lon=" + lon.toFixed(5), { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (d) {
      if (d.detail) { box.textContent = d.detail; return; }
      function row(k, v) { return "<tr><td style='width:40%;color:var(--muted)'>" + k + "</td><td>" + v + "</td></tr>"; }
      var h = "<table><tbody>" + row("经纬", d.lon + ", " + d.lat) + row("海拔", d.elev_m + " m") +
        row("坡度 / 坡向", d.slope_deg + "° / " + d.aspect_deg + "°") +
        (d.downscaled ? row("下推 Tmin / Tmax", d.downscaled.tmin + " / " + d.downscaled.tmax + " ℃") : "") +
        (d.risk ? row("综合风险 R", "<b class='" + clsSpan(d.risk.level) + "'>" + d.risk.R + "（" + d.risk.level + "）</b>") : "") +
        row("霜冻易感", d.frost_susceptibility) + row("高温/旱易感", d.heat_susceptibility) +
        row("建议", d.advice || "-") + "</tbody></table>" +
        '<div style="margin-top:8px"><button id="askBtn">用问答追问这个地块 →</button></div>';
      box.innerHTML = h;
      $("#askBtn").onclick = function () { location.href = "chat.html?q=" + encodeURIComponent(d.question || ("地块(" + d.lon + "," + d.lat + ")今天该做什么？")); };
    }).catch(function () { box.textContent = "生成失败，请稍后重试。"; });
  });

  var himg = map.querySelector("img.ph");
  if (himg) himg.addEventListener("load", render);
  window.addEventListener("resize", render);
  window.addEventListener("load", render);
  loadData();
  setInterval(loadData, 60000);
})();
