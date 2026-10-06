from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from html import escape
from urllib.parse import quote

import pandas as pd
import requests


HEADERS = {"User-Agent": "Mozilla/5.0 IntegratedFundWeeklyReport/1.0"}
MARKETS = {
    "台灣": ("台灣加權指數", "^TWII"),
    "日本": ("日經225", "^N225"),
    "韓國": ("KOSPI", "^KS11"),
    "中國": ("上證指數", "000001.SS"),
    "香港": ("恆生指數", "^HSI"),
    "美國": ("S&P 500", "^GSPC"),
    "美國科技": ("Nasdaq", "^IXIC"),
    "歐洲": ("STOXX Europe 600", "^STOXX"),
}
BENCHMARK_TICKERS = {
    "滬深300": "000300.SS",
    "滬深300指數": "000300.SS",
    "上證指數": "000001.SS",
    "恆生指數": "^HSI",
    "日經225": "^N225",
    "日經225指數": "^N225",
    "台灣加權指數": "^TWII",
    "標普500指數": "^GSPC",
    "S&P 500": "^GSPC",
    "NASDAQ指數": "^IXIC",
    "費城半導體指數": "^SOX",
}
INDUSTRY_PROXIES = {
    "電子零組件業": [("台光電", "2383.TW"), ("健策", "3653.TW"), ("奇鋐", "3017.TW"), ("欣興", "3037.TW"), ("南電", "8046.TW")],
    "半導體業": [("台積電", "2330.TW"), ("聯發科", "2454.TW"), ("旺矽", "6223.TW"), ("日月光投控", "3711.TW"), ("聯詠", "3034.TW")],
    "電腦及週邊設備業": [("廣達", "2382.TW"), ("緯創", "3231.TW"), ("緯穎", "6669.TW"), ("華碩", "2357.TW")],
    "通信網路業": [("智邦", "2345.TW"), ("智易", "3596.TW"), ("啟碁", "6285.TW"), ("中磊", "5388.TWO")],
    "其他電子業": [("鴻海", "2317.TW"), ("台達電", "2308.TW"), ("旭隼", "6409.TW"), ("帆宣", "6196.TW")],
    "電機機械": [("上銀", "2049.TW"), ("台達電", "2308.TW"), ("華城", "1519.TW"), ("東元", "1504.TW")],
    "金融保險業": [("富邦金", "2881.TW"), ("國泰金", "2882.TW"), ("中信金", "2891.TW"), ("兆豐金", "2886.TW")],
    "生技醫療業": [("藥華藥", "6446.TW"), ("保瑞", "6472.TW"), ("美時", "1795.TWO"), ("中天", "4128.TWO")],
}


def yahoo_history(ticker: str, range_: str = "3mo") -> pd.DataFrame:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(ticker)}"
    response = requests.get(
        url,
        params={"range": range_, "interval": "1d"},
        headers=HEADERS,
        timeout=15,
    )
    response.raise_for_status()
    chart = response.json().get("chart", {})
    results = chart.get("result") or []
    if not results:
        return pd.DataFrame(columns=["日期", "收盤"])
    item = results[0]
    closes = item.get("indicators", {}).get("quote", [{}])[0].get("close", [])
    return pd.DataFrame(
        {"日期": pd.to_datetime(item.get("timestamp", []), unit="s"), "收盤": closes}
    ).dropna(subset=["收盤"])


def _stats(ticker: str) -> dict | None:
    data = yahoo_history(ticker)
    if len(data) < 2:
        return None
    latest = float(data["收盤"].iloc[-1])
    weekly_base = float(data["收盤"].iloc[-6]) if len(data) >= 6 else float(data["收盤"].iloc[0])
    monthly_base = float(data["收盤"].iloc[-22]) if len(data) >= 22 else float(data["收盤"].iloc[0])
    week = (latest / weekly_base - 1) * 100
    month = (latest / monthly_base - 1) * 100
    ma20 = float(data["收盤"].tail(20).mean())
    trend = "轉強" if latest > ma20 and week > 0 else "轉弱" if latest < ma20 and week < 0 else "震盪"
    return {
        "latest": latest,
        "week": week,
        "month": month,
        "trend": trend,
        "date": data["日期"].iloc[-1].date(),
    }


def fetch_market_weekly() -> pd.DataFrame:
    entries = [(region, name, ticker) for region, (name, ticker) in MARKETS.items()]

    def load(entry):
        region, name, ticker = entry
        try:
            return region, name, _stats(ticker)
        except Exception:
            return region, name, None

    rows = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        for region, name, stats in executor.map(load, entries):
            if stats:
                rows.append(
                    {
                        "市場": region,
                        "指數": name,
                        "本週漲跌%": stats["week"],
                        "近1月%": stats["month"],
                        "趨勢": stats["trend"],
                        "資料日期": stats["date"],
                    }
                )
    return pd.DataFrame(rows)


def fetch_benchmark_weekly(benchmark: str) -> dict | None:
    normalized = "".join(str(benchmark).split())
    ticker = next(
        (symbol for name, symbol in BENCHMARK_TICKERS.items() if "".join(name.split()).lower() == normalized.lower()),
        None,
    )
    if not ticker:
        return None
    return _stats(ticker)


def fetch_industry_data(
    top_industries: list[dict], fund_holdings: list[dict] | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    holding_rows = []
    for item in top_industries:
        industry = str(item["產業"])
        companies = INDUSTRY_PROXIES.get(industry, [])
        holding_weights = {
            str(row.get("公司／持股", "")): float(row.get("基金持股權重%", 0))
            for row in (fund_holdings or [])
        }
        matched = [company for company in companies if company[0] in holding_weights]
        source_type = "基金公開持股" if matched else "產業代表公司"
        if matched:
            companies = matched

        def load(company):
            name, ticker = company
            try:
                return name, ticker, _stats(ticker)
            except Exception:
                return name, ticker, None

        observations = []
        with ThreadPoolExecutor(max_workers=4) as executor:
            observations = [result for result in executor.map(load, companies) if result[2]]
        for name, ticker, stats in observations:
            holding_rows.append(
                {
                    "產業": industry,
                    "公司／持股": name,
                    "代碼": ticker,
                    "基金持股權重%": holding_weights.get(name, float("nan")),
                    "資料性質": source_type,
                    "本週變化%": stats["week"],
                    "近1月變化%": stats["month"],
                    "趨勢": stats["trend"],
                    "行情日期": stats["date"],
                }
            )
        if observations:
            week = sum(stats["week"] for _, _, stats in observations) / len(observations)
            month = sum(stats["month"] for _, _, stats in observations) / len(observations)
            data_date = max(stats["date"] for _, _, stats in observations)
            trend = "轉強" if week > 1 else "轉弱" if week < -1 else "震盪"
            indicator = "、".join(ticker for _, ticker, _ in observations)
        else:
            week = month = float("nan")
            data_date = pd.NaT
            trend = "資料不足"
            indicator = "尚未設定代表公司"
        rows.append(
            {
                "產業": industry,
                "持股權重%": float(item.get("持股權重%", 0)),
                "指標": indicator,
                "本週變化%": week,
                "近1月變化%": month,
                "趨勢": trend,
                "資料日期": data_date,
                "持股資料日期": item.get("持股資料日期", ""),
            }
        )
    return pd.DataFrame(rows), pd.DataFrame(holding_rows)


def fetch_industry_weekly(top_industries: list[dict]) -> pd.DataFrame:
    return fetch_industry_data(top_industries)[0]


def market_summary(market_df: pd.DataFrame) -> str:
    valid = market_df.dropna(subset=["本週漲跌%"])
    if valid.empty:
        return "市場行情資料不足，暫不判斷本週方向。"
    best = valid.loc[valid["本週漲跌%"].idxmax()]
    worst = valid.loc[valid["本週漲跌%"].idxmin()]
    breadth = int((valid["本週漲跌%"] > 0).sum())
    tone = "多數市場上漲" if breadth > len(valid) / 2 else "多數市場下跌" if breadth < len(valid) / 2 else "漲跌互見"
    return (
        f"本週呈現{tone}；{best['指數']}表現最佳（{best['本週漲跌%']:+.2f}%），"
        f"{worst['指數']}相對最弱（{worst['本週漲跌%']:+.2f}%）。"
        "此段僅依價格與均線整理，不推測未接入的新聞事件原因。"
    )


def build_html_report(inputs, market_df, industry_df, alignment, holdings_df=None) -> str:
    def rows_html(df, columns):
        header = "".join(f"<th>{escape(str(column))}</th>" for column in columns)
        body = []
        for _, row in df.iterrows():
            cells = []
            for column in columns:
                value = row[column]
                if "%" in column and pd.notna(value):
                    rendered = f"{float(value):+.2f}%"
                elif "日期" in column and pd.notna(value):
                    rendered = pd.to_datetime(value).strftime("%Y-%m-%d")
                else:
                    rendered = "資料不足" if pd.isna(value) else str(value)
                cells.append(f"<td>{escape(rendered)}</td>")
            body.append("<tr>" + "".join(cells) + "</tr>")
        return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(body)}</tbody></table>"

    def bars_html(df, label_column, value_column):
        observed_max = df[value_column].abs().max(skipna=True)
        maximum = max(1.0, float(observed_max)) if pd.notna(observed_max) else 1.0
        items = []
        for _, row in df.iterrows():
            value = row[value_column]
            if pd.isna(value):
                items.append(f"<div class='bar-row'><span>{escape(str(row[label_column]))}</span><em>資料不足</em></div>")
                continue
            width = max(2, abs(float(value)) / maximum * 100)
            cls = "positive" if value >= 0 else "negative"
            items.append(
                f"<div class='bar-row'><span>{escape(str(row[label_column]))}</span>"
                f"<div class='track'><div class='bar {cls}' style='width:{width:.1f}%'></div></div>"
                f"<em>{float(value):+.2f}%</em></div>"
            )
        return "".join(items)

    market_columns = ["市場", "指數", "本週漲跌%", "近1月%", "趨勢", "資料日期"]
    industry_columns = ["產業", "持股權重%", "本週變化%", "近1月變化%", "趨勢", "資料日期"]
    holding_columns = ["產業", "公司／持股", "代碼", "基金持股權重%", "本週變化%", "近1月變化%", "趨勢", "行情日期", "資料性質"]
    holdings_df = holdings_df if holdings_df is not None else pd.DataFrame(columns=holding_columns)
    holdings_table = rows_html(holdings_df, holding_columns) if not holdings_df.empty else "<p>逐檔行情資料不足。</p>"
    news = str(inputs.get("news_content", "")).strip()
    news_html = escape(news).replace("\n", "<br>") if news else "未提供新聞內容。"
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(inputs['fund_name'])} 一週分析</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft JhengHei',sans-serif;margin:0;background:#f5f7fb;color:#172033}}main{{max-width:1080px;margin:auto;padding:32px 20px}}.card{{background:white;border:1px solid #dfe5ef;border-radius:14px;padding:22px;margin:18px 0;box-shadow:0 4px 14px #1720330d}}h1,h2{{color:#0f766e}}.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}}.kpi{{background:#ecfdf5;border-radius:10px;padding:15px}}.kpi b{{display:block;font-size:1.35rem;margin-top:6px}}table{{width:100%;border-collapse:collapse;font-size:.92rem}}th,td{{padding:10px;border-bottom:1px solid #e5e7eb;text-align:left}}th{{background:#f0fdfa}}.bar-row{{display:grid;grid-template-columns:170px 1fr 75px;gap:10px;align-items:center;margin:10px 0}}.track{{height:16px;background:#eef2f7;border-radius:99px;overflow:hidden}}.bar{{height:100%;border-radius:99px}}.positive{{background:#dc2626}}.negative{{background:#16a34a}}em{{font-style:normal;text-align:right}}small{{color:#64748b}}@media(max-width:650px){{.bar-row{{grid-template-columns:110px 1fr 65px}}table{{font-size:.78rem}}}}</style></head>
<body><main><h1>{escape(inputs['fund_name'])} 一週基金分析報告</h1><p>資料日期：{escape(inputs['report_date'])}｜綜合判讀：<b>{escape(alignment)}</b></p>
<section class="card"><h2>基金摘要</h2><div class="kpis"><div class="kpi">基金本週<b>{inputs['fund_week']:+.2f}%</b></div><div class="kpi">Benchmark 本週<b>{inputs['benchmark_week']:+.2f}%</b></div><div class="kpi">超額報酬<b>{inputs['fund_week']-inputs['benchmark_week']:+.2f}%</b></div><div class="kpi">最大回撤<b>{inputs['max_drawdown']:.2f}%</b></div></div><p>Benchmark：{escape(inputs['benchmark'])}</p></section>
<section class="card"><h2>全球市場一週分析</h2><p>{escape(market_summary(market_df))}</p>{bars_html(market_df.sort_values('本週漲跌%',ascending=False),'指數','本週漲跌%')}{rows_html(market_df,market_columns)}</section>
<section class="card"><h2>持股前三大產業近一週變化</h2>{bars_html(industry_df,'產業','本週變化%')}{rows_html(industry_df,industry_columns)}<h3>各產業代表持股／公司一週變化</h3>{holdings_table}<small>產業變化為代表公司等權報酬，不等於基金該產業部位的實際報酬；持股權重與行情日期分別列示。</small></section>
<section class="card"><h2>新聞內容與市場觀察</h2><p>{news_html}</p><small>本段為使用者貼入內容，未經本工具獨立查證；請保留原始來源、日期並另行核對。</small></section>
<section class="card"><h2>資料來源與限制</h2><p>全球市場行情與代表公司行情：Yahoo Finance 公開 chart 資料；基金產業權重：MoneyDJ 公開基金持股資料。資料不足不自行猜測。本報告僅供市場研究，不構成投資建議。</p></section></main></body></html>"""
