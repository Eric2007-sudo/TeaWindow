"""预测辅助（不是预测器）：让决策模型判断"这次预报该不该信、属于哪种情形"。

边界要说清楚：
- 数值预测仍由 ERA5 + GBDT + DEM 下推给出，决策模型**不改数**；
- 它只做三件事：判霜型、判一致性、给置信等级；
- 输出用于"是否加不确定性提示 / 是否需要人工复核"，属于预测的元信息。

如果将来要用它提升精度，正确做法是：把它的判定当作**分组变量**（霜型/一致性），
在冻结评估集上检验分组后的误差是否下降；没有下降就不进入模型。
"""
import os

import decision_client

QUESTIONS = {
    "frost_type": {
        "type": "choice",
        "instructions": "根据给定气象条件，这次低温过程更接近哪种类型？",
        "criteria": {
            "辐射霜": "晴空、静风、夜间辐射降温，谷底冷池明显",
            "平流霜": "冷空气大风降温，风大、湿度不一定高",
            "无霜冻": "最低温明显高于霜冻阈值，或暖湿多云",
        },
    },
    "confidence": {
        "type": "score",
        "instructions": "仅依据给定证据，这条预报的可用程度如何？",
        "criteria": ["低（建议复核）", "中（可参考）", "高（可直接用）"],
    },
    "consistent": {
        "type": "noul",
        "instructions": "规则给出的风险等级，与给定的温度/降水/风/湿度条件是否一致？",
    },
}

LABEL = {0: "低", 1: "中", 2: "高"}


def assess(row, timeout=None):
    """row: 单日数据（含 tmin/tmax/precip/risk_R/p_frost/tmin_lo/tmin_hi/wind/rh）。"""
    state = {
        "date": row.get("date"),
        "tmin": row.get("tmin"),
        "tmax": row.get("tmax"),
        "precip": row.get("precip"),
        "risk_R": row.get("risk_R"),
        "risk_level": row.get("risk_level"),
        "p_frost": row.get("p_frost"),
        "tmin_p10": row.get("tmin_lo"),
        "tmin_p90": row.get("tmin_hi"),
        "wind": row.get("wind"),
        "rh": row.get("rh"),
        "season": row.get("season"),
        "note": "以上为再分析/预报与地形下推结果；请只依据这些证据判断。",
    }
    t = timeout or float(os.environ.get("STARTLUX_ASSIST_TIMEOUT", "15"))
    out = decision_client.try_decide(state, QUESTIONS, think_mode="never", timeout=t)
    if not out:
        return None

    ans = out.get("answers") or {}
    frost, fconf, _ = decision_client.best(ans, "frost_type")
    try:
        level = float((ans.get("confidence") or {}).get("score"))
    except Exception:  # noqa: BLE001
        level = None
    consistent = float((ans.get("consistent") or {}).get("noul") or 0.0)

    notes = []
    if frost == "辐射霜":
        notes.append("辐射霜型：重点看谷底/背阴坡，防霜布与风扇优先。")
    elif frost == "平流霜":
        notes.append("平流霜型：风大，防霜布效果有限，优先抢采与覆盖。")
    if level is not None and level < 0.8:
        notes.append("预报置信偏低：建议对照上游实况后再行动。")
    if consistent < 0.35:
        notes.append("规则风险与气象条件存在分歧：建议人工复核。")

    return {
        "frost_type": frost,
        "frost_confidence": round(fconf, 3),
        "confidence": level,
        "confidence_label": LABEL.get(int(round(level)) if level is not None else -1, "-"),
        "consistent": round(consistent, 3),
        "note": " ".join(notes),
        "model": out.get("model") or decision_client.model_id(),
    }
