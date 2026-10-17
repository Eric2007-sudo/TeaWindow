/* 地块体检卡：读取 ?lat=&lon=[&name=]，渲染地形 + 下推 + 逐日 + 来源 */
(function () {
  "use strict";
  var $ = function (s) { return document.querySelector(s); };
  function qs(k) { try { return new URLSearchParams(location.search).get(k); } catch (e) { return null; } }
  var lat = parseFloat(qs("lat")), lon = parseFloat(qs("lon")), name = qs("name") || "";
  if (!isFinite(lat) || !isFinite(lon)) {
    $("#sub").textContent = "缺少经纬度参数：请从「地块风险图」点选后再进入。";
    return;
  }
  function cls(v) { return v >= 0.75 ? "极高" : v >= 0.6 ? "高" : v >= 0.4 ? "中" : "低"; }
  function clsSpan(c) { return (c === "高" || c === "极高") ? "hi" : (c === "中" ? "mid" : "lo"); }
  function kpi(k, v, colorCls) {
    return "<div class='kpi'><div class='k'>" + k + "</div><div class='v " + (colorCls || "") + "'>" + v + "</div></div>";
  }
  $("#print").onclick = function () { window.print(); };

  fetch("api/plot/series?lat=" + lat.toFixed(5) + "&lon=" + lon.toFixed(5) + "&n=3&scope=next", { cache: "no-store" })
    .then(function (r) { return r.json(); }).then(function (d) {
      if (d.detail) { $("#sub").textContent = d.detail; return; }
      var p = d.plot || {}, ser = d.series || [], m = d.meta || {};
      var t0 = ser[0] || {};
      $("#sub").textContent = (name ? name + " · " : "") + "地块 " + p.lon + ", " + p.lat +
        " · 生成于 " + (m.fetched_at || "-") + (m.stale ? "（数据可能过期）" : "");
      $("#kpis").innerHTML =
        kpi("海拔", (p.elev_m == null ? "-" : p.elev_m + " m")) +
        kpi("坡度 / 坡向", (p.slope_deg == null ? "-" : p.slope_deg + "° / " + p.aspect_deg + "°")) +
        kpi("今日下推 Tmin", (t0.tmin == null ? "-" : t0.tmin + "℃")) +
        kpi("今日风险 R", (t0.R == null ? "-" : t0.R + "（" + cls(t0.R) + "）"), clsSpan(cls(t0.R || 0))) +
        kpi("霜冻易感", (p.frost_susceptibility || "-"), clsSpan(p.frost_susceptibility)) +
        kpi("高温/旱易感", (p.heat_susceptibility || "-"), clsSpan(p.heat_susceptibility));

      var adv = "建议：常规养护，关注最新预报。";
      if (ser.some(function (x) { return x.tmin <= 2; })) adv = "建议防冻：夜晨覆盖/熏烟/喷水，重点看低温日。";
      else if (ser.some(function (x) { return x.tmax >= 33; })) adv = "建议防高温/补水：遮阳、傍晚浇透，避免正午作业。";
      else if (ser.some(function (x) { return (x.R || 0) >= 0.6; })) adv = "建议关注水分与高温叠加：先测根层墒情，再决定补水。";
      $("#advice").textContent = adv;

      var tb = $("#ser").querySelector("tbody");
      tb.innerHTML = "";
      ser.forEach(function (x) {
        var lv = cls(x.R || 0);
        tb.innerHTML += "<tr><td>" + x.date + "</td><td>" + x.tmin + "℃</td><td>" + x.tmax + "℃</td><td>" +
          (x.precip == null ? "-" : x.precip + " mm") + "</td><td>" + (x.R == null ? "-" : x.R) +
          "</td><td class='" + clsSpan(lv) + "'>" + lv + "</td></tr>";
      });
      $("#prov").innerHTML = "数据抓取：" + (m.fetched_at || "-") +
        " · 数据年龄：" + (m.age_minutes == null ? "-" : m.age_minutes + " 分钟") +
        " · 版本：v" + (m.version || "-") +
        "<br>上游：" + (m.upstream || "-") + " · 原始 SHA-256：" + (m.sha || "-") + " · 构建：" + (m.build || "-") +
        "<br>方法：DEM（Terrarium）海拔/坡度/坡向 + 海拔递减率与冷池/坡向修正 → 逐点下推 Tmin/Tmax → 风险规则。";
    }).catch(function () { $("#sub").textContent = "生成失败，请稍后重试。"; });
})();