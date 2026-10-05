# 基金與產業一週整合報告

這是一個獨立的 Streamlit 專案，不會覆蓋既有的全球市場、基金分析或科技供應鏈儀表板。

## 功能

- 貼上基金網址並輸入基金核心指標。
- 匯入全球市場與產業一週 CSV。
- 比較基金、Benchmark 與相關產業方向。
- 追蹤半導體、記憶體、高階 PCB、矽晶圓、光通訊、800V 直流電及 AI 電力供應鏈。
- 產生並下載 Markdown 基金一週分析報告。
- 資料不足時明確標示，不自動猜測。

## 啟動

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## CSV 欄位

市場週資料：`市場, 指數, 本週漲跌%, 近1月%, 趨勢, 資料日期`

產業週資料：`產業, 指標, 本週變化%, 近1月變化%, 趨勢, 資料日期`

## 資料來源設計

Streamlit 網頁本身不是穩定的資料 API。本專案以 CSV 上傳及示範資料為第一版介面；後續可將原三個專案輸出至共用 GitHub Raw JSON／CSV，再進行每日或每週自動更新。

## 免責聲明

本工具僅供市場研究與資料整理，不構成投資建議。
