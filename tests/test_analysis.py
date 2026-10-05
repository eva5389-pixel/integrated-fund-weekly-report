import pandas as pd

from utils.analysis import classify_alignment, normalize_industry_data


def test_classify_alignment_positive():
    assert classify_alignment(4.0, 3.0, 2.0, 1.2) == "偏多觀察"


def test_classify_alignment_risk():
    assert classify_alignment(-3.0, -1.0, -2.0, -0.2) == "風險升高"


def test_missing_columns_raise():
    try:
        normalize_industry_data(pd.DataFrame({"產業": ["半導體"]}))
    except ValueError as exc:
        assert "缺少必要欄位" in str(exc)
    else:
        raise AssertionError("Expected ValueError")

