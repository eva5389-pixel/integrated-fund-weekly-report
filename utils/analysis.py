from __future__ import annotations

import pandas as pd


MARKET_COLUMNS = ["市場", "指數", "本週漲跌%", "近1月%", "趨勢", "資料日期"]
INDUSTRY_COLUMNS = ["產業", "指標", "本週變化%", "近1月變化%", "趨勢", "資料日期"]


def _normalize(df: pd.DataFrame, columns: list[str], numeric: list[str]) -> pd.DataFrame:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise ValueError(f"缺少必要欄位：{', '.join(missing)}")
    result = df.copy()
    for column in numeric:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result["資料日期"] = pd.to_datetime(result["資料日期"], errors="coerce")
    if result[numeric].isna().all(axis=None):
        raise ValueError("數值欄位沒有可用資料")
    extras = [column for column in result.columns if column not in columns]
    return result[columns + extras]


def normalize_market_data(df: pd.DataFrame) -> pd.DataFrame:
    return _normalize(df, MARKET_COLUMNS, ["本週漲跌%", "近1月%"])


def normalize_industry_data(df: pd.DataFrame) -> pd.DataFrame:
    return _normalize(df, INDUSTRY_COLUMNS, ["本週變化%", "近1月變化%"])


def classify_alignment(
    fund_week: float,
    benchmark_week: float,
    industry_week: float,
    sharpe: float,
) -> str:
    score = 0
    score += 1 if fund_week > 0 else -1
    score += 1 if fund_week >= benchmark_week else -1
    score += 1 if industry_week > 0 else -1
    score += 1 if sharpe >= 1 else (-1 if sharpe < 0 else 0)
    if score >= 3:
        return "偏多觀察"
    if score <= -2:
        return "風險升高"
    return "中性觀望"


def _table_markdown(df: pd.DataFrame, columns: list[str], limit: int = 8) -> str:
    view = df[columns].head(limit).copy()
    for column in [c for c in columns if "%" in c]:
        view[column] = view[column].map(lambda value: "資料不足" if pd.isna(value) else f"{value:.2f}%")
    for column in [c for c in columns if "日期" in c]:
        view[column] = pd.to_datetime(view[column], errors="coerce").dt.strftime("%Y-%m-%d").fillna("資料不足")
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    rows = [
        "| " + " | ".join(str(value).replace("|", "\\|") for value in row) + " |"
        for row in view.itertuples(index=False, name=None)
    ]
    return "\n".join([header, separator, *rows])


def build_markdown_report(
    inputs: dict,
    market_df: pd.DataFrame,
    industry_df: pd.DataFrame,
    alignment: str,
    holdings_df: pd.DataFrame | None = None,
) -> str:
    excess = inputs["fund_week"] - inputs["benchmark_week"]
    industry_mean = industry_df["本週變化%"].mean()
    market_table = _table_markdown(
        market_df.sort_values("本週漲跌%", ascending=False), MARKET_COLUMNS
    )
    industry_table = _table_markdown(
        industry_df.sort_values("本週變化%", ascending=False), INDUSTRY_COLUMNS
    )
    holding_columns = ["產業", "公司／持股", "代碼", "基金持股權重%", "本週變化%", "近1月變化%", "趨勢", "行情日期", "資料性質"]
    holdings_table = (
        _table_markdown(holdings_df, holding_columns, limit=20)
        if holdings_df is not None and not holdings_df.empty
        else "逐檔行情資料不足。"
    )
    news_content = str(inputs.get("news_content", "")).strip() or "未提供新聞內容。"
    return f"""# {inputs['fund_name']} 一週基金分析報告

資料日期：{inputs['report_date']}

## 結論

綜合判讀為 **{alignment}**。基金本週報酬為 {inputs['fund_week']:.2f}%，Benchmark 本週報酬為 {inputs['benchmark_week']:.2f}%，超額報酬為 {excess:+.2f}%。相關產業平均一週變化為 {industry_mean:+.2f}%。

## 基金風險與績效

- 近一月報酬：{inputs['fund_month']:.2f}%
- Sharpe：{inputs['sharpe']:.2f}
- Beta：{inputs['beta']:.2f}
- 最大回撤：{inputs['max_drawdown']:.2f}%
- Benchmark：{inputs['benchmark']}
- 基金來源：{inputs['fund_url'] or '未提供'}

## 全球市場一週

{market_table}

## 相關產業一週

{industry_table}

## 前三大產業代表持股／公司一週變化

{holdings_table}

## 新聞內容與市場觀察

{news_content}

> 本段新聞為使用者貼入內容，未經本工具獨立查證；請保留原始來源與日期並另行核對。

## 觀察重點

1. 基金是否持續領先 Benchmark，而非只看單週絕對報酬。
2. 半導體、記憶體、PCB、矽晶圓、光通訊及 AI 電力供應鏈是否同向。
3. 若基金上漲但產業與 Benchmark 同步轉弱，需提防落後反應及回撤風險。
4. 資料不足時不產生買賣結論，應回到基金淨值、持股與原始產業資料核對。

> 本報告僅供市場研究，不構成投資建議。
"""
