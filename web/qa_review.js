(function () {
  var $ = function (s) { return document.querySelector(s); };
  var tok = function () { return $("#tok").value.trim(); };
  try { var t = localStorage.getItem("tw_admin_tok"); if (t) $("#tok").value = t; } catch (e) {}
  $("#tok").addEventListener("change", function () { try { localStorage.setItem("tw_admin_tok", tok()); } catch (e) {} });

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]; }); }

  async function load() {
    try { localStorage.setItem("tw_admin_tok", tok()); } catch (e) {}
    var r = await fetch("api/qa/logs?limit=200", { headers: { "X-Admin-Token": tok() }, cache: "no-store" });
    if (r.status === 403) { $("#list").innerHTML = '<div class="row bad">令牌无效或未配置 ADMIN_TOKEN。</div>'; return; }
    var d = await r.json();
    $("#cnt").textContent = "共 " + d.count + " 条 · 待审 " + d.pending.length;
    $("#list").innerHTML = d.pending.map(function (x) {
      var chain = (x.chain && x.chain.length)
        ? '<div class="meta">来源链：' + esc(x.chain.join(" → ")) + '</div>' : '';
      var ev = x.evidence
        ? '<details class="ev"><summary>证据快照（当天数据）</summary><div class="a">' + esc(x.evidence) + '</div></details>' : '';
      return '<div class="row"><div class="q">' + esc(x.question) + '</div>'
        + '<div class="meta">#' + x.id + " · " + esc(x.ts) + " · 意图 " + esc(x.intent) + " · 引擎 " + esc(x.engine) + '</div>'
        + '<div class="a">' + esc(x.answer) + '</div>'
        + chain + ev
        + '<div class="act"><button class="p" data-id="' + x.id + '" data-rel="1">相关·收藏</button>'
        + '<button data-id="' + x.id + '" data-rel="0">不相关</button>'
        + '<button data-id="' + x.id + '" data-rel="1" data-done="1">已审阅</button></div></div>';
    }).join("") || '<div class="row">暂无待审记录。多问几句就会有。</div>';
    $("#list").querySelectorAll("button").forEach(function (b) {
      b.onclick = async function () {
        var body = { id: +b.dataset.id, relevant: +b.dataset.rel, reviewed: b.dataset.done ? 1 : 0 };
        await fetch("api/qa/review", { method: "POST", headers: { "Content-Type": "application/json", "X-Admin-Token": tok() }, body: JSON.stringify(body) });
        b.closest(".row").style.opacity = .45; b.textContent = "已处理 ✓";
      };
    });
  }
  $("#load").onclick = load;
  if ($("#tok").value) load();
})();
