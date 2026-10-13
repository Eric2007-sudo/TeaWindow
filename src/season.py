"""
统一季节与业务日（Asia/Shanghai）策略。
- 所有"今天/明天/季节边界/data_age"必须使用北京时间，禁止用 UTC 字符串截日期。
- 季节策略为**共享对象**：所有 intent handler、主页与 LLM 改写都消费同一 policy，
  避免"霜冻无风险→可以采摘"绕过非春采期约束。
"""
from __future__ import annotations

import datetime

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # noqa: BLE001
    TZ = None

# 春采季月份（西湖龙井 43；3–4 月）
SPRING_MONTHS = (3, 4)


def now() -> datetime.datetime:
    return datetime.datetime.now(TZ) if TZ else datetime.datetime.now()


def today() -> datetime.date:
    return now().date()


def iso_today() -> str:
    return today().isoformat()


def policy(date: datetime.date | None = None) -> dict:
    """返回统一季节策略对象（被所有处理器/前端/LLM 共享）。"""
    d = date or today()
    if d.month in SPRING_MONTHS:
        return {
            "season": "spring",
            "allowed_actions": ["采摘", "抢采", "防冻", "防旱", "排涝", "监测"],
            "forbidden_actions": [],
            "reason": "春采季（3–4 月）",
        }
    return {
        "season": "off",
        "allowed_actions": ["养护", "防冻监测", "防旱监测", "排涝", "修剪", "施肥", "清沟", "越冬准备"],
        "forbidden_actions": ["采摘", "抢采", "采摘排班", "建议正常采摘", "推荐采摘窗口"],
        "reason": "当前不在春采季（西湖龙井 43 春采季为 3–4 月）",
    }


def is_off(date: datetime.date | None = None) -> bool:
    return policy(date)["season"] == "off"


def care_hint() -> str:
    p = policy()
    return f"{p['reason']}，以{'、'.join(p['allowed_actions'][:4])}为主。"


# 用户可见文本禁止出现的占位/空值
BAD_TOKENS = ("None", "nan", "NaN", "undefined", "Null")


def clean_text(text: str) -> str:
    """输出完整性：清理 None/NaN/undefined 等占位；若整体残缺则返回兜底。"""
    if not text:
        return "抱歉，暂时无法生成建议，请换个说法或稍后再试。"
    out = text
    for t in (" undefined", " undefined", " None", " none", " NaN", " nan"):
        out = out.replace(t, "")
    out = out.replace("None", "—").replace("nan", "—").replace("NaN", "—").replace("undefined", "—")
    if out.strip() in ("", "—", "-", "。"):
        return "抱歉，暂时无法生成建议，请换个说法或稍后再试。"
    return out