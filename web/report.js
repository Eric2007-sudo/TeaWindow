/* TeaWindow 物候/灾情上报前端（外部脚本，配合 CSP script-src 'self'） */
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const msg = $("#msg");
  $("#date").value = new Date().toISOString().slice(0, 10);

  const D = window.TW_DATA;
  if (D && D.terrain && D.terrain.plots) {
    const sel = $("#plot");
    D.terrain.plots.forEach((p) => {
      const o = document.createElement("option");
      o.value = p.name;
      o.textContent = p.name;
      sel.appendChild(o);
    });
  }

  let busy = false;
  async function submitOne() {
    if (busy) return;
    busy = true;
    const btn = $("#submit");
    btn.disabled = true;
    msg.textContent = "提交中…";
    const body = { date: $("#date").value, plot: $("#plot").value, kind: $("#kind").value, note: $("#note").value };
    try {
      const r = await fetch("api/report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (r.status === 429) { msg.textContent = "⚠️ 提交过于频繁，请稍后再试。"; return; }
      if (!r.ok) {
        let e = {};
        try { e = await r.json(); } catch (err) { /* ignore */ }
        msg.textContent = "⚠️ 提交失败：" + (e.detail || r.status);
        return;
      }
      const d = await r.json();
      msg.textContent = "✅ 提交成功，累计 " + d.count + " 条（去标识化，仅用于科研）。";
    } catch (e) {
      msg.textContent = "⚠️ 提交失败（需在线服务）。";
    } finally {
      busy = false;
      btn.disabled = false;
    }
  }
  $("#submit").addEventListener("click", submitOne);
})();