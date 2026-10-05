import pandas as pd

from utils.analysis import classify_alignment, normalize_industry_data
from utils.fund_metadata import _resolve_moneydj_wrapper_url, extract_fund_metadata


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


def test_extract_fund_name_and_benchmark():
    html = """
    <html><head><title>5808統一奔騰基金｜基金資訊</title></head>
    <body><h1>5808統一奔騰基金</h1>
    <div>比較基準：台灣資訊科技指數</div></body></html>
    """
    result = extract_fund_metadata(html, "https://example.com/fund/5808")
    assert result["fund_name"] == "5808統一奔騰基金"
    assert result["benchmark"] == "台灣資訊科技指數"


def test_benchmark_is_not_guessed_when_missing():
    result = extract_fund_metadata("<h1>5808統一奔騰基金</h1>")
    assert result["fund_name"] == "5808統一奔騰基金"
    assert result["benchmark"] == ""


def test_moneydj_bank_wrapper_is_resolved_to_fund_page():
    wrapper = (
        "https://tcbbankfund.moneydj.com/main.html?"
        "sUrl=%24W%24WR%24WR03%5DDJHTM%7BA%7DACPS10-5808"
    )
    assert _resolve_moneydj_wrapper_url(wrapper) == (
        "https://tcbbankfund.moneydj.com/w/wr/wr03.djhtm?a=ACPS10-5808"
    )


def test_specific_fund_name_wins_over_generic_page_heading():
    html = "<h1>國內基金-績效比較</h1><h3>5808統一奔騰基金 基金</h3>"
    assert extract_fund_metadata(html)["fund_name"] == "5808統一奔騰基金"
