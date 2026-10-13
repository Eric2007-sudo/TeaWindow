/* TeaWindow 智能问答前端：加载态 / 防重复提交 / 错误分类 / 重试 / IME 处理 / 无障碍 */
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const log = $("#log");
  const input = $("#q");
  const sendBtn = $("#send");
  const messages = [];           // 多轮上下文（刷新即清零）
  let busy = false;

  function nowHM() {
    const d = new Date();
    return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
  }

  function add(text, cls, meta, chain) {
    const d = document.createElement("div");
    d.className = "msg " + cls;
    d.appendChild(document.createTextNode(text));
    const info = [];
    if (meta) info.push(meta);
    info.push(nowHM());
    const m = document.createElement("div");
    m.className = "meta";
    m.textContent = info.join(" · ");
    d.appendChild(m);
    if (chain && chain.length) {
      const c = document.createElement("div");
      c.className = "chain";
      c.textContent = "来源链：" + chain.join(" → ");
      d.appendChild(c);
    }
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
    return d;
  }

  function addRetry(question) {
    const d = document.createElement("div");
    d.className = "msg bot err";
    d.textContent = "请求失败。";
    const b = document.createElement("button");
    b.className = "retry";
    b.type = "button";
    b.textContent = "重试";
    b.onclick = () => { d.remove(); submit(question); };
    d.appendChild(b);
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
  }

  const suggestions = ["今天有风险吗？", "要不要防冻？", "先采哪块地？", "保险多少钱一亩？", "今年什么时候开采？", "你们用什么模型？"];
  $("#chips").innerHTML = "";
  suggestions.forEach((t) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip";
    b.textContent = t;
    b.onclick = () => { input.value = t; submit(t); };
    $("#chips").appendChild(b);
  });

  async function submit(question) {
    const q = (question != null ? question : input.value).trim();
    if (!q || busy) return;
    busy = true;
    sendBtn.disabled = true;
    if (question == null) { add(q, "me"); input.value = ""; }
    else { add(q, "me"); }

    const engine = $("#enh").checked ? "llm" : "own";
    const history = messages.slice(-8);
    messages.push({ role: "user", content: q });

    const typing = document.createElement("div");
    typing.className = "typing";
    typing.textContent = "正在生成…";
    log.appendChild(typing);
    log.scrollTop = log.scrollHeight;

    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 60000);
      const r = await fetch("api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, engine: engine, history: history }),
        signal: ctrl.signal,
      });
      clearTimeout(timer);
      typing.remove();
      if (!r.ok) {
        // 错误分类：限流 / 请求错误 / 服务错误
        let detail = "";
        try { detail = (await r.json()).detail || ""; } catch (e) { /* ignore */ }
        if (r.status === 429) add("请求过于频繁，请稍后再试。" + (detail ? "（" + detail + "）" : ""), "bot err");
        else if (r.status >= 400 && r.status < 500) add("输入有误：" + (detail || r.status), "bot err");
        else add("服务暂时不可用（" + r.status + "），请稍后重试。", "bot err");
        addRetry(q);
        messages.pop();
        return;
      }
      const d = await r.json();
      const isLLM = d.engine === "teawindow-own+llm" || d.source === "deepseek-rephrase";
      const label = isLLM ? "引擎：自研 + DeepSeek 润色" : "引擎：TeaWindow 自研";
      const be = d.backend ? "　后端：" + d.backend : "";
      const meta = label + be + (d.intent ? "　意图：" + d.intent + "（置信 " + d.confidence + "）" + (d.follow_up ? " · 追问" : "") : "");
      add(d.text, "bot", meta, d.chain);
      messages.push({ role: "assistant", content: d.text });
    } catch (e) {
      typing.remove();
      const msg = (e && e.name === "AbortError") ? "请求超时，请重试。" : "网络异常或服务不可用，请检查网络后重试。";
      add(msg, "bot err");
      addRetry(q);
      messages.pop();
    } finally {
      busy = false;
      sendBtn.disabled = false;
      input.focus();
    }
  }

  $("#bar").addEventListener("submit", (e) => { e.preventDefault(); submit(); });
  input.addEventListener("keydown", (e) => {
    // 中文输入法组合期间不提交
    if (e.key === "Enter" && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); submit(); }
  });
  $("#clear").onclick = () => { log.innerHTML = ""; messages.length = 0; input.focus(); };
})();