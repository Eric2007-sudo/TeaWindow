/* 验证与证据页：所有数字来自 data.json / phenology.json / 版本接口（失败时回退 data.js） */
(function () {
  var $ = function (s) { return document.querySelector(s); };
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]; }); }
  function num(x, d) { return (x == null || isNaN(x)) ? "-" : Number(x).toFixed(d == null ? 3 : d); }

  async function j(u) {
    try { var r = await fetch(u, { cache: "no-store" }); if (r.ok) return await r.json(); } catch (e) { /* ignore */ }
    return null;
  }

  (async function () {
    var ov = await j("api/overview");
    var ph = await j("phenology.json");
    var ver = await j("api/data/versions?limit=1");
    var D = ov || window.TW_DATA || {};
    var M = D.metrics || {};

    if (!ov) {
      var el = document.getElementById("snapnote");
      if (el) {
        el.textContent = "⚡ 服务唤醒中：本页用本地缓存快照；指标口径不受影响（评估集已冻结）。";
        el.hidden = false;
      }
    }

    var ml = M.ml || {}, base = M["baseline_single_threshold(tmin<=2)"] || {};

    /* ---- 顶部卡片 ---- */
    var fixedMae = ph && ph.fixed ? ph.fixed.mae : null;
    var fwdMae = ph && ph.forward ? ph.forward.mae : null;
    var cards = [
      { k: "官方开采日 MAE（不拟合）", v: fixedMae == null ? "-" : fixedMae + " 天", s: "外部真值：杭州市官方开采日" },
      { k: "前向验证 MAE", v: fwdMae == null ? "-" : fwdMae + " 天", s: "2022–2023 拟合 → 2024–2026 测试" },
      { k: "复合模型 AUC", v: num(ml.auc), s: "冻结评估集 · 2024-01-01 至 " + (M.__test_end || "2026-10-10") },
      { k: "复合模型 F1", v: num(ml.f1), s: "单阈值基线 " + num(base.f1, 2) }
    ];
    $("#cards").innerHTML = cards.map(function (c) {
      return '<div class="card"><div class="k">' + esc(c.k) + '</div><div class="v">' + esc(c.v) + '</div><div class="s">' + esc(c.s) + '</div></div>';
    }).join("");

    /* ---- 1. 对照表 ---- */
    var rows = [
      ["复合风险模型（GBDT）", ml.auc, ml.f1, ml.precision, ml.recall, ml.n],
      ["单阈值基线（Tmin ≤ 2℃）", base.auc, base.f1, base.precision, base.recall, base.n]
    ];
    $("#evalTable").innerHTML = '<table><thead><tr><th>方法</th><th>AUC</th><th>F1</th><th>Precision</th><th>Recall</th><th>n</th></tr></thead><tbody>'
      + rows.map(function (r) {
        return "<tr><td>" + esc(r[0]) + "</td><td>" + num(r[1]) + "</td><td>" + num(r[2]) + "</td><td>"
          + num(r[3]) + "</td><td>" + num(r[4]) + "</td><td>" + esc(r[5]) + "</td></tr>";
      }).join("") + "</tbody></table>";
    $("#evalNote").textContent = "评估集固定在提交日（2024-01-01 至 2026-10-10，n=" + (ml.n || "-")
      + "），之后新增日期只进训练/展示，不再改变指标——避免每次刷新数字漂移。标签为专家农艺规则生成的弱标签，"
      + "不是田间产量真值。";

    /* ---- 2. 混淆矩阵（由指标反推） ---- */
    if (ml.n && ml.n_pos && ml.recall != null && ml.precision) {
      var tp = Math.round(ml.recall * ml.n_pos);
      var fn = ml.n_pos - tp;
      var fp = Math.round(tp * (1 / ml.precision - 1));
      var tn = ml.n - tp - fn - fp;
      $("#cm").innerHTML =
        '<div class="h"></div><div class="h">预测：有风险</div><div class="h">预测：无风险</div>' +
        '<div class="h">实际：有</div><div><b class="ok">TP ' + tp + '</b></div><div><b class="bad">FN ' + fn + '</b></div>' +
        '<div class="h">实际：无</div><div><b class="warn">FP ' + fp + '</b></div><div><b class="ok">TN ' + tn + '</b></div>';
      $("#cmNote").textContent = "TP/FN/FP/TN 由 precision/recall/n_pos 反推（四舍五入），用于直觉理解，不替代原始预测文件。";
    }

    /* ---- 3. 官方开采日 ---- */
    if (ph && ph.rows && ph.rows.length) {
      $("#phenoTable").innerHTML = '<table><thead><tr><th>年份</th><th>官方开采日</th><th>模型预测</th><th>偏差</th></tr></thead><tbody>'
        + ph.rows.map(function (r) {
          var d = (r.diff == null) ? "-" : (r.diff > 0 ? "+" + r.diff : String(r.diff));
          return "<tr><td>" + r.year + "</td><td>" + esc(r.official) + "</td><td>" + esc(r.pred) + "</td><td>"
            + d + "</td></tr>";
        }).join("") + "</tbody></table>";
      var parts = [];
      parts.push("不拟合官方日期（文献阈值 基温 " + ph.fixed.base + "℃ / " + ph.fixed.start + " / " + ph.fixed.thr + "℃·d）：MAE " + ph.fixed.mae + " 天。");
      if (ph.forward) parts.push("前向验证（" + ph.forward.fit_years.join("–") + " 拟合 → " + ph.forward.test_years.join("–") + " 测试）：MAE " + ph.forward.mae + " 天。");
      parts.push("固定日期 03-19 基线 MAE " + ph.naive.mae + " 天——所以真正的价值在异常年与可迁移性，而不是平均值。");
      $("#phenoNote").textContent = parts.join(" ");
    } else {
      $("#phenoTable").innerHTML = '<div class="note">phenology.json 未加载（可运行 <code>python src/phenology.py</code> 生成）。</div>';
    }

    /* ---- 4. 血缘 ---- */
    var v = ver && ver.versions && ver.versions[0];
    if (v) {
      $("#lineage").innerHTML =
        "版本 <b>#" + esc(v.id) + "</b> · " + esc(v.ts) + " · 构建 " + esc(v.build || "-")
        + '<br>上游：<a href="' + esc(v.upstream_url || "#") + '" target="_blank" rel="noopener">' + esc(v.upstream_url || "-") + "</a>"
        + "<br>原始数据 SHA-256：<code>" + esc((v.raw_sha256_full || "").slice(0, 32)) + "…</code>"
        + "<br>生成时间 " + esc(v.gen_time || "-") + " · 天数 " + esc(v.n_days || "-");
    } else {
      $("#lineage").textContent = "版本接口未返回（离线或服务唤醒中）。仓库内 report/ 与 web/data.json 仍含同样的血缘字段。";
    }

    /* ---- 6. 边界 ---- */
    var limits = [
      "官方开采日只有 5 个样本（2022–2026），MAE 的不确定性很大；它验证的是「预测开采日」，不验证产量或品质。",
      "模型的 AUC/F1 是弱标签复现，不是田间精度；真实精度要等 90 天 pilot 的正/负样本。",
      "地块风险是 DEM 下推的相对差异，不是实测；示例传感器站点目前只登记坐标，未接硬件。",
      "所有建议是决策辅助，不替代田间实勘与官方预警。"
    ];
    $("#limits").innerHTML = limits.map(function (x) { return "· " + esc(x); }).join("<br>");
  })();
})();
