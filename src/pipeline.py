"""
一键管线：抓数 → 指标 → (遥感) → 模型 → 导出。
供命令行与 FastAPI 定时任务复用。
用法：
  python src\\pipeline.py            # 全量（含联网抓取）
  python src\\pipeline.py --no-fetch # 仅用本地已有原始数据重算
  python src\\pipeline.py --figs     # 额外生成报告图表
"""
import argparse
import os
import sys
import time

SRC = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SRC)
sys.path.insert(0, SRC)


def _step(name, fn):
    t = time.time()
    print(f"[pipeline] {name} ...", flush=True)
    fn()
    print(f"[pipeline] {name} 完成 ({time.time() - t:.1f}s)", flush=True)


def run(do_fetch=True, do_ndvi=True, do_figs=False):
    import indices
    import model
    import build_export

    if do_fetch:
        import fetch_weather
        _step("fetch_weather", fetch_weather.main)
        if do_ndvi:
            try:
                import fetch_ndvi
                _step("fetch_ndvi", fetch_ndvi.main)
            except Exception as e:  # noqa: BLE001
                print(f"[pipeline] 遥感抓取失败，跳过：{e}")
    _step("indices", indices.main)
    _step("model", model.main)
    # 可选：若有台站观测，做偏差订正（非破坏性，产出 daily_corrected.csv）
    try:
        if os.path.exists(os.path.join(ROOT, "data", "processed", "station_hangzhou.csv")):
            import station_correct
            _step("station_correct", station_correct.main)
    except Exception as e:  # noqa: BLE001
        print(f"[pipeline] 台站订正跳过：{e}")
    _step("build_export", build_export.main)
    # 新颖点：调度 / 决策论 / 价值闭环（读取并回写 data.json）
    for mod in ("scheduler", "decision", "value", "index_insurance", "climatology"):
        try:
            m = __import__(mod)
            _step(mod, m.main)
        except Exception as e:  # noqa: BLE001
            print(f"[pipeline] {mod} 跳过：{e}")
    # 分析类报告（无网络、较快）
    for mod in ("counterfactual", "phenology", "model_compare", "recalibrate", "label_sensitivity"):
        try:
            m = __import__(mod)
            _step(mod, m.main)
        except Exception as e:  # noqa: BLE001
            print(f"[pipeline] {mod} 跳过：{e}")
    if do_figs:
        import make_figs
        _step("make_figs", make_figs.main)
    print("[pipeline] 全部完成 ->", os.path.join(ROOT, "web", "data.json"), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true", help="跳过联网抓取，用本地原始数据重算")
    ap.add_argument("--no-ndvi", action="store_true", help="跳过遥感抓取")
    ap.add_argument("--figs", action="store_true", help="生成报告图表")
    a = ap.parse_args()
    run(do_fetch=not a.no_fetch, do_ndvi=not a.no_ndvi, do_figs=a.figs)


if __name__ == "__main__":
    main()
