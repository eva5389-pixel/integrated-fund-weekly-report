from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

from utils.analysis import (
    INDUSTRY_COLUMNS,
    MARKET_COLUMNS,
    build_markdown_report,
    classify_alignment,
    normalize_industry_data,
    normalize_market_data,
)
from utils.fund_metadata import fetch_fund_metadata, fetch_fund_top_industries
from utils.live_data import (
    build_html_report,
    fetch_industry_weekly,
    fetch_market_weekly,
    market_summary,
)


ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"

DEFAULT_WEEKLY_URL = "https://global-index-weekly-uc3hzgjlbdrzsnkqe8ybar.streamlit.app/"
DEFAULT_FUND_URL = "https://fund-analysis-report-generator-caafenpfzpxbybgeldumwp.streamlit.app/"
DEFAULT_INDUSTRY_URL = "https://industry-supply-chain-dashboard-ehrr5pn5wzf6csv2ke8mh8.streamlit.app/"


st.set_page_config(
    page_title="基金與產業一週整合報告",
    page_icon=":material/finance_mode:",
    layout="wide",
)


@st.cache_data
def load_example(name: str) -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / name)


@st.cache_data(ttl="15m", max_entries=4, show_spinner=False)
def load_live_markets() -> pd.DataFrame:
    return fetch_market_weekly()


@st.cache_data(ttl="15m", max_entries=20, show_spinner=False)
def load_live_industries(records: tuple[tuple[str, float, str], ...]) -> pd.DataFrame:
    items = [
        {"產業": name, "持股權重%": weight, "持股資料日期": data_date}
        for name, weight, data_date in records
    ]
    return fetch_industry_weekly(items)


def read_upload(upload, fallback_name: str) -> pd.DataFrame:
    if upload is None:
        return load_example(fallback_name).copy()
    return pd.read_csv(upload)


if "report_ready" not in st.session_state:
    st.session_state.report_ready = False
st.session_state.setdefault("fund_url_input", "")
st.session_state.setdefault("fund_name_input", "示範半導體基金")
st.session_state.setdefault("benchmark_input", "費城半導體指數")
st.session_state.setdefault(
    "top_industries_data",
    [
        {"產業": "半導體業", "持股權重%": 0.0, "持股資料日期": ""},
        {"產業": "電子零組件業", "持股權重%": 0.0, "持股資料日期": ""},
        {"產業": "電腦及週邊設備業", "持股權重%": 0.0, "持股資料日期": ""},
    ],
)

st.title("基金與產業一週整合報告")
st.caption(
    "把基金績效、全球市場週報與半導體／記憶體產業變化放在同一份報告中。"
    "資料不足時明確標示，不自行推測。"
)

with st.container(horizontal=True):
    st.link_button("全球市場週報", DEFAULT_WEEKLY_URL, icon=":material/public:")
    st.link_button("原基金分析工具", DEFAULT_FUND_URL, icon=":material/monitoring:")
    st.link_button("科技供應鏈儀表板", DEFAULT_INDUSTRY_URL, icon=":material/memory:")

with st.container(border=True):
    st.subheader("基金網址辨識")
    st.text_input(
        "基金網址",
        key="fund_url_input",
        placeholder="貼上 MoneyDJ、基富通或其他公開基金頁面網址",
        help="按下自動辨識後，系統會讀取公開頁面的基金名稱及 Benchmark；抓不到時不會自行猜測。",
    )
    if st.button("自動抓基金名稱與 Benchmark", icon=":material/auto_awesome:"):
        if not st.session_state.fund_url_input.strip():
            st.warning("請先貼上基金網址。")
        else:
            try:
                with st.spinner("正在讀取基金公開頁面…"):
                    metadata = fetch_fund_metadata(st.session_state.fund_url_input.strip())
                if metadata["fund_name"]:
                    st.session_state.fund_name_input = metadata["fund_name"]
                if metadata["benchmark"]:
                    st.session_state.benchmark_input = metadata["benchmark"]
                top_industries = fetch_fund_top_industries(
                    st.session_state.fund_url_input.strip()
                )
                if top_industries:
                    st.session_state.top_industries_data = top_industries
                if metadata["fund_name"] and metadata["benchmark"]:
                    st.success("已自動辨識基金名稱與 Benchmark，可在下方確認或修正。")
                elif metadata["fund_name"]:
                    st.warning("已抓到基金名稱，但來源頁未提供可辨識的 Benchmark，請手動補充。")
                else:
                    st.warning("已抓到 Benchmark，但基金名稱仍需手動確認。")
            except (ValueError, requests.RequestException) as exc:
                st.error(f"自動辨識失敗：{exc}")

with st.form("report_inputs", border=True):
    st.subheader("報告設定")
    with st.container(horizontal=True):
        fund_name = st.text_input("基金名稱", key="fund_name_input")
        benchmark = st.text_input("Benchmark", key="benchmark_input")
        report_date = st.date_input("報告日期", value=date.today())

    st.markdown("**基金指標**")
    with st.container(horizontal=True):
        fund_week = st.number_input("基金本週報酬 %", value=2.4, step=0.1)
        fund_month = st.number_input("基金近一月報酬 %", value=6.8, step=0.1)
        benchmark_week = st.number_input("Benchmark 本週報酬 %", value=3.7, step=0.1)
        sharpe = st.number_input("Sharpe", value=1.25, step=0.05)
        beta = st.number_input("Beta", value=1.08, step=0.05)
        max_drawdown = st.number_input("最大回撤 %", value=-14.2, step=0.1)

    st.markdown("**資料檔案（選填）**")
    auto_live = st.checkbox(
        "自動取得全球市場與前三大產業行情",
        value=True,
        help="未上傳 CSV 時，依全球市場週報相同口徑讀取 Yahoo Finance 公開行情。",
    )
    st.markdown("**基金持股前三大產業**")
    top_industries_editor = st.data_editor(
        pd.DataFrame(st.session_state.top_industries_data),
        hide_index=True,
        num_rows="fixed",
        key="top_industries_editor",
        column_config={
            "產業": st.column_config.TextColumn(required=True),
            "持股權重%": st.column_config.NumberColumn(format="%.2f%%", min_value=0.0),
            "持股資料日期": st.column_config.TextColumn(disabled=True),
        },
    )
    st.caption("MoneyDJ 可辨識時會自動帶入；仍可修改產業名稱及權重。")
    with st.container(horizontal=True):
        market_upload = st.file_uploader(
            "市場週資料 CSV",
            type=["csv"],
            help="欄位：市場、指數、本週漲跌%、近1月%、趨勢、資料日期",
        )
        industry_upload = st.file_uploader(
            "產業週資料 CSV",
            type=["csv"],
            help="欄位：產業、指標、本週變化%、近1月變化%、趨勢、資料日期",
        )

    submitted = st.form_submit_button(
        "產生整合報告", type="primary", icon=":material/description:"
    )

if submitted:
    try:
        if auto_live and market_upload is None:
            with st.spinner("正在更新全球市場一週行情…"):
                market_raw = load_live_markets()
        else:
            market_raw = read_upload(market_upload, "market_weekly.csv")
        if auto_live and industry_upload is None:
            records = tuple(
                (
                    str(row["產業"]).strip(),
                    float(row["持股權重%"] or 0),
                    str(row.get("持股資料日期", "")),
                )
                for row in top_industries_editor.to_dict("records")
                if str(row["產業"]).strip()
            )
            with st.spinner("正在計算前三大產業代表公司近一週變化…"):
                industry_raw = load_live_industries(records)
        else:
            industry_raw = read_upload(industry_upload, "industry_weekly.csv")
        market_df = normalize_market_data(market_raw)
        industry_df = normalize_industry_data(industry_raw)
        if "持股權重%" not in industry_df:
            industry_df["持股權重%"] = float("nan")
        st.session_state.market_df = market_df
        st.session_state.industry_df = industry_df
        st.session_state.inputs = {
            "fund_url": st.session_state.fund_url_input,
            "fund_name": fund_name,
            "benchmark": benchmark,
            "report_date": report_date.isoformat(),
            "fund_week": float(fund_week),
            "fund_month": float(fund_month),
            "benchmark_week": float(benchmark_week),
            "sharpe": float(sharpe),
            "beta": float(beta),
            "max_drawdown": float(max_drawdown),
        }
        st.session_state.report_ready = True
    except (ValueError, pd.errors.ParserError, requests.RequestException) as exc:
        st.error(f"資料格式無法讀取：{exc}")

if not st.session_state.report_ready:
    st.info("填寫基金資料後按「產生整合報告」。目前附有示範市場與產業資料。")
    st.stop()

inputs = st.session_state.inputs
market_df = st.session_state.market_df
industry_df = st.session_state.industry_df
excess_return = inputs["fund_week"] - inputs["benchmark_week"]
alignment = classify_alignment(
    fund_week=inputs["fund_week"],
    benchmark_week=inputs["benchmark_week"],
    industry_week=float(industry_df["本週變化%"].mean()),
    sharpe=inputs["sharpe"],
)

st.divider()
st.subheader(f"{inputs['fund_name']} 一週摘要")
with st.container(horizontal=True):
    st.metric("基金本週", f"{inputs['fund_week']:.2f}%", border=True)
    st.metric("Benchmark", f"{inputs['benchmark_week']:.2f}%", border=True)
    st.metric("超額報酬", f"{excess_return:+.2f}%", border=True)
    st.metric("Sharpe", f"{inputs['sharpe']:.2f}", border=True)
    st.metric("綜合判讀", alignment, border=True)

overview, market_tab, industry_tab, report_tab = st.tabs(
    ["整合摘要", "市場一週", "相關產業", "報告下載"]
)

with overview:
    with st.container(border=True):
        st.markdown("**判讀原則**")
        st.write(
            "同時比較基金、Benchmark 與相關產業方向；基金落後 Benchmark、產業轉弱或風險指標偏高時，"
            "結論會下調。這是研究分級，不是保證報酬的買賣指令。"
        )
    st.dataframe(
        industry_df.sort_values("本週變化%", ascending=False).head(5),
        hide_index=True,
        column_config={
            "本週變化%": st.column_config.NumberColumn(format="%.2f%%"),
            "近1月變化%": st.column_config.NumberColumn(format="%.2f%%"),
            "資料日期": st.column_config.DateColumn(format="YYYY-MM-DD"),
        },
    )

with market_tab:
    st.info(market_summary(market_df))
    st.bar_chart(
        market_df.sort_values("本週漲跌%"),
        x="指數",
        y="本週漲跌%",
        horizontal=True,
    )
    st.dataframe(
        market_df[MARKET_COLUMNS],
        hide_index=True,
        column_config={
            "本週漲跌%": st.column_config.NumberColumn(format="%.2f%%"),
            "近1月%": st.column_config.NumberColumn(format="%.2f%%"),
            "資料日期": st.column_config.DateColumn(format="YYYY-MM-DD"),
        },
    )

with industry_tab:
    selected_industries = st.multiselect(
        "選擇相關產業",
        options=industry_df["產業"].drop_duplicates().tolist(),
        default=industry_df["產業"].drop_duplicates().tolist(),
    )
    filtered = industry_df[industry_df["產業"].isin(selected_industries)]
    st.bar_chart(
        filtered.sort_values("本週變化%"),
        x="指標",
        y="本週變化%",
        color="產業",
        horizontal=True,
    )
    st.dataframe(
        filtered[["產業", "持股權重%"] + [c for c in INDUSTRY_COLUMNS if c != "產業"]],
        hide_index=True,
        column_config={
            "持股權重%": st.column_config.NumberColumn(format="%.2f%%"),
            "本週變化%": st.column_config.NumberColumn(format="%.2f%%"),
            "近1月變化%": st.column_config.NumberColumn(format="%.2f%%"),
            "資料日期": st.column_config.DateColumn(format="YYYY-MM-DD"),
        },
    )

with report_tab:
    report = build_markdown_report(inputs, market_df, industry_df, alignment)
    html_report = build_html_report(inputs, market_df, industry_df, alignment)
    st.markdown(report)
    st.download_button(
        "下載 Markdown 報告",
        data=report.encode("utf-8"),
        file_name=f"{inputs['fund_name']}_{inputs['report_date']}_一週基金分析.md",
        mime="text/markdown",
        icon=":material/download:",
    )
    st.download_button(
        "一鍵下載 HTML 網頁報告",
        data=html_report.encode("utf-8"),
        file_name=f"{inputs['fund_name']}_{inputs['report_date']}_一週基金分析.html",
        mime="text/html",
        icon=":material/web:",
        type="primary",
    )
    with st.expander("資料來源與限制"):
        st.markdown(
            f"- 全球市場週報：{DEFAULT_WEEKLY_URL}\n"
            f"- 基金分析工具：{DEFAULT_FUND_URL}\n"
            f"- 科技供應鏈儀表板：{DEFAULT_INDUSTRY_URL}\n"
            f"- 基金頁面：{inputs['fund_url'] or '未提供'}\n\n"
            "Streamlit 應用頁面不適合作為穩定機器資料介面；正式自動更新應改接公開 CSV、JSON、API 或 GitHub Raw 資料。"
        )
