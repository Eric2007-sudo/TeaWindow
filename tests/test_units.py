"""单元测试：指标引擎 / 模型 / LLM 后备 / API。"""
import numpy as np
import pandas as pd


def _synth(n=40):
    dates = pd.date_range("2024-03-01", periods=n, freq="D")
    tmax = np.linspace(10, 30, n)
    tmin = tmax - 8
    tmin[5] = 1.0   # 触发霜冻
    tmax[20] = 36.0  # 触发高温
    return pd.DataFrame({
        "date": dates,
        "temperature_2m_max": tmax,
        "temperature_2m_min": tmin,
        "temperature_2m_mean": (tmax + tmin) / 2,
        "precipitation_sum": np.where(np.arange(n) % 3 == 0, 0.0, 5.0),
        "relative_humidity_2m_mean": 75.0,
        "et0_fao_evapotranspiration": 2.5,
        "shortwave_radiation_sum": 15.0,
        "sunshine_duration": 20000.0,
        "wind_speed_10m_max": 10.0,
        "soil_moisture_0_to_7cm_mean": 0.3,
    })


def test_indices_frost_and_heat():
    import indices
    df = indices.compute(_synth())
    assert "frost" in df and "heat" in df and "gdd_cum" in df
    assert df["frost"].sum() >= 1
    assert df["heat"].sum() >= 1
    # 有效积温随日序单调不减（同一年）
    assert (df["gdd_cum"].diff().dropna() >= 0).all()


def test_rubric_range_and_labels():
    import indices
    from model import rubric
    df = indices.compute(_synth())
    y, R = rubric(df)
    R = np.asarray(R)
    assert R.min() >= 0 and R.max() <= 1
    assert set(np.unique(np.asarray(y))).issubset({0, 1})


def test_gbdt_trains_and_predicts():
    from model import GBDT
    rng = np.random.default_rng(0)
    X = rng.normal(size=(80, 4))
    y = ((X[:, 0] + X[:, 1]) > 0).astype(float)
    m = GBDT(n_estimators=25, max_depth=2, min_leaf=5).fit(X, y)
    p = m.predict_proba(X)
    assert p.shape == (80,)
    assert p.min() >= 0 and p.max() <= 1


def test_rule_fallback_nonempty():
    import llm_advice
    txt = llm_advice.rule_based({"date": "2024-03-10", "risk_level": "高",
                                 "risk_type": "倒春寒/霜冻", "frost": 1, "cold_shock": 1,
                                 "suitability": 30, "risk_R": 0.7})
    assert isinstance(txt, str) and len(txt) > 20
    assert "风险" in txt


def test_api_app_importable():
    import serve
    assert serve.app is not None
