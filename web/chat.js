/* TeaWindow 智能问答前端：加载态 / 防重复提交 / 错误分类 / 重试 / IME 处理 / 无障碍 */
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const log = $("#log");
  const input = $("#q");
  const sendBtn = $("#send");
  const messages = [];           // 多轮上下文（持久化到 localStorage，刷新不丢）
  let state = {};                // 结构化会话槽位（实体/格式/否定/摘要）
  let busy = false;
  const LS = "tw_chat_v1";
  const MEM_WINDOW = 10;         // 记忆窗口≈10 条消息

  function nowHM() {
    try {
      return new Date().toLocaleTimeString("zh-CN", { timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit" });
    } catch (e) { return ""; }
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
    const history = messages.slice(-MEM_WINDOW);
    const older = messages.slice(0, -MEM_WINDOW).filter((m) => m.role === "user").map((m) => m.content).join("；");
    const st = Object.assign({}, state);
    if (older) st.summary = older.slice(-220);
    messages.push({ role: "user", content: q });
    try { localStorage.setItem(LS, JSON.stringify({ messages: messages.slice(-20), state: st })); } catch (e) { /* ignore */ }

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
        body: JSON.stringify({ question: q, engine: engine, history: history, state: st }),
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
      if (d.state) state = d.state;
      const isLLM = d.engine === "teawindow-own+llm" || d.source === "deepseek-rephrase";
      const label = isLLM ? "引擎：自研 + DeepSeek 润色" : "引擎：TeaWindow 自研";
      const be = d.backend ? "　后端：" + d.backend : "";
      const meta = label + be + (d.intent ? "　意图：" + d.intent + "（置信 " + d.confidence + "）" + (d.follow_up ? " · 追问" : "") : "");
      add(d.text, "bot", meta, d.chain);
      messages.push({ role: "assistant", content: d.text });
      try { localStorage.setItem(LS, JSON.stringify({ messages: messages.slice(-20), state: state })); } catch (e) { /* ignore */ }
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
  $("#clear").onclick = () => { log.innerHTML = ""; messages.length = 0; state = {}; try { localStorage.removeItem(LS); } catch (e) { /* ignore */ } input.focus(); };

  // 恢复上次会话（记忆窗口≈10 条的工作基础）
  try {
    const saved = JSON.parse(localStorage.getItem(LS) || "null");
    if (saved && Array.isArray(saved.messages)) {
      saved.messages.forEach((m) => {
        if (m && typeof m.content === "string") add(m.content, m.role === "user" ? "me" : "bot", m.role === "assistant" ? "历史" : "");
      });
      messages.push(...saved.messages);
      state = saved.state || {};
    }
  } catch (e) { /* ignore */ }

  // 仅在没有历史时显示欢迎（避免追加到恢复历史末尾）
  if (!messages.length) {
    add("你好，我是梅坞采候助手。我能回答：风险、霜冻/高温、干旱/灌溉、连雨、采摘窗口、地块、保险与损失、开采期、数据与模型说明；非茶园问题我会拒答。点下方快捷问题即可开始。", "bot", "欢迎 · 能力边界");
  }

  // 支持从"地块风险图"等页面带问题跳转：chat.html?q=...
  try {
    const qp = new URLSearchParams(location.search).get("q");
    if (qp && qp.trim()) { input.value = qp.trim(); submit(qp.trim()); }
  } catch (e) { /* ignore */ }
})();