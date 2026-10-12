"""
LLM 建议层：把风险指标转成茶农可执行的白话建议。
- 若设置了环境变量 DEEPSEEK_API_KEY，则调用 DeepSeek（deepseek-chat）；
- 否则使用规则模板后备（保证离线 Demo 有可用内容）。
"""
import json
import os

try:
    import requests
except Exception:  # noqa: BLE001
    requests = None


def load_env():
    """从项目根目录 .env 读取环境变量（无需 python-dotenv）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


load_env()

API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"

SYSTEM = (
    "你是西湖龙井核心产区（杭州梅家坞）的气候服务助手，服务对象是本地茶农与采茶队。"
    "请根据给定的气象与风险指标，输出简洁、口语化、可执行的中文建议。"
    "要求：1) 先给结论；2) 分条给出具体动作（采摘/遮阳/灌溉/防冻等）；3) 不要编造数据；"
    "4) 涉及灾害预警要提示不确定性；5) 总字数 120–220 字。"
)


def rule_based(ctx):
    """基于风险要素的中文规则建议。"""
    parts = []
    lv = ctx.get("risk_level", "低")
    date = ctx.get("date", "")
    parts.append(f"{date} 综合风险：{lv}（{ctx.get('risk_type', '无明显风险')}）。")
    acts = []
    if ctx.get("frost"):
        acts.append("防霜冻：夜里至清晨注意低温，可临时覆盖/熏烟/喷水，达标的芽叶优先抢采。")
    if ctx.get("cold_shock"):
        acts.append("倒春寒：前期偏暖后骤冷，嫩芽易受冻，暂停修剪、加强覆盖保温。")
    if ctx.get("heat"):
        acts.append("抗高温：上午10点后上遮阳网，傍晚浇透水，避免正午修剪。")
    if ctx.get("drought"):
        acts.append("防干旱：土壤偏干、水分亏缺，每4–5天灌一次并稻草覆盖保墒。")
    if ctx.get("rain"):
        acts.append("连阴雨：鲜叶含水高，注意及时摊青、防闷堆；采后尽快杀青。")
    if not acts:
        acts.append("条件平稳，适合采制；按标准一芽一叶及时采摘，保证均匀嫩净。")
    parts.append("；".join(acts))
    parts.append(f"采摘适宜度约 {ctx.get('suitability', '-')}/100，仅供参考，请结合田间实际情况。")
    return "".join(parts)


def deepseek(ctx):
    if not (requests and os.environ.get("DEEPSEEK_API_KEY")):
        return None
    prompt = ("指标(JSON):\n" + json.dumps(ctx, ensure_ascii=False) +
              "\n请给出面向茶农的当日建议。")
    try:
        r = requests.post(API_URL, timeout=60,
                          headers={"Authorization": "Bearer " + os.environ["DEEPSEEK_API_KEY"],
                                   "Content-Type": "application/json"},
                          json={"model": MODEL,
                                "messages": [{"role": "system", "content": SYSTEM},
                                             {"role": "user", "content": prompt}],
                                "temperature": 0.3, "max_tokens": 400})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:  # noqa: BLE001
        print("  [llm] 调用失败，使用规则后备:", e)
        return None


def advice_for(ctx):
    return {"ctx": ctx, "source": None, "text": None}


def generate(ctx):
    txt = deepseek(ctx)
    src = "deepseek-chat"
    if not txt:
        txt = rule_based(ctx)
        src = "rule_fallback"
    return {"source": src, "text": txt}


def ctx_from_row(row):
    r = row
    def f(k):
        try:
            v = float(r[k])
            return 0.0 if v != v else v  # NaN guard
        except Exception:  # noqa: BLE001
            return 0.0
    rt = []
    if f("frost") or f("cold_shock"):
        rt.append("倒春寒/霜冻")
    if f("heat") or f("heat_severe"):
        rt.append("高温")
    if f("dry_run") >= 5 or f("water_deficit_10d") >= 45:
        rt.append("干旱")
    if f("wet_run") >= 4:
        rt.append("连阴雨")
    return {
        "date": str(r["date"])[:10],
        "risk_level": str(r.get("risk_level", "")),
        "risk_type": "、".join(rt) if rt else "无明显风险",
        "risk_R": round(f("risk_R"), 2),
        "tmax": round(f("temperature_2m_max"), 1),
        "tmin": round(f("temperature_2m_min"), 1),
        "precip": round(f("precipitation_sum"), 1),
        "deficit": round(f("water_deficit_10d"), 1),
        "dry_run": int(f("dry_run")),
        "wet_run": int(f("wet_run")),
        "frost": int(f("frost")),
        "cold_shock": int(f("cold_shock")),
        "heat": int(f("heat")),
        "drought": int(1 if (f("dry_run") >= 5 or f("water_deficit_10d") >= 45) else 0),
        "rain": int(1 if f("wet_run") >= 4 else 0),
        "suitability": round(f("suitability"), 0),
    }


if __name__ == "__main__":
    demo = {"date": "2026-04-12", "risk_level": "高", "risk_type": "倒春寒/霜冻", "tmin": 1.5,
            "frost": 1, "cold_shock": 1, "suitability": 35, "risk_R": 0.7}
    print(generate(demo))
