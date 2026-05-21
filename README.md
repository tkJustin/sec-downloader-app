# SEC HTML Downloader + Quarterly Financial Dashboard V1.5

本專案是一個本地端 Streamlit 工具，用 SEC 官方公開資料來源查詢 filing metadata、下載 primary HTML filing、轉換 clean text，並從 Company Facts API 建立季度財務表與趨勢圖。

## 資料來源

- `company_tickers.json`: ticker 轉 CIK
- Submissions API: filing metadata
- EDGAR Archives: primary document HTML
- Company Facts API: XBRL financial facts

SEC request 設定集中於 `config.py`，包含明確 `User-Agent`、保守 rate limit、retry 與 timeout。

## 安裝

```bash
cd sec_downloader_app
python -m pip install -r requirements.txt
python -m playwright install chromium
```

請設定 SEC User-Agent。SEC 要求程式化存取需提供可識別的 User-Agent。

本機可設定環境變數：

```bash
set SEC_USER_AGENT=SEC Local Dashboard your_email@example.com
```

Streamlit Community Cloud 可在 App settings -> Secrets 加入：

```toml
SEC_USER_AGENT = "SEC Local Dashboard your_email@example.com"
```

## 執行

```bash
streamlit run app.py
```

Windows 也可以在專案資料夾執行：

```bat
run_app.bat
```

## Streamlit Community Cloud

部署設定：

- Repository: `tkJustin/sec-downloader-app`
- Branch: `main`
- Main file path: `app.py`
- Python version: 3.12
- Secrets: 建議加入 `SEC_USER_AGENT`

PDF 下載功能會用 Chromium 將 SEC HTML print-to-PDF。`packages.txt` 已加入 `chromium`，若雲端環境仍無法啟動 Chromium，HTML 下載與 clean text/financial dashboard 仍可使用，PDF 轉換會在結果表顯示錯誤訊息。

## 操作流程

1. 選擇 Manual input 或 Excel/CSV upload。
2. 手動輸入 ticker、form type、年度區間，或上傳 `templates/sec_download_template.xlsx`。
3. 點選 `Query SEC metadata and build filing preview`。
4. 在 preview table 勾選要下載的 filing。
5. 點選 `Download selected filings`。
6. 在結果區檢視 HTML、PDF、clean text 路徑與 clean text preview。
7. 點選 `Fetch SEC Company Facts` 顯示季度財務表與趨勢圖。
8. 使用下載按鈕匯出 manifest 與 financials CSV。

## 專案結構

```text
sec_downloader_app/
├── app.py
├── requirements.txt
├── README.md
├── config.py
├── modules/
│   ├── sec_client.py
│   ├── task_builder.py
│   ├── downloader.py
│   ├── html_parser.py
│   ├── financial_facts.py
│   ├── analysis.py
│   └── storage.py
├── data/
│   ├── input/
│   ├── metadata/
│   ├── raw_html/
│   ├── clean_text/
│   ├── financials/
│   └── exports/
├── logs/
│   └── download_log.csv
└── templates/
    └── sec_download_template.xlsx
```

## 已知限制

- V1.5 下載 primary HTML document；若選擇 `pdf`，會先保存 HTML，再用 Chromium print-to-PDF 轉成 PDF。
- PDF 轉換會驗證檔案存在、頁數與大小；版面以 Chromium 對原始 SEC HTML 的列印結果為準。
- Company Facts 指標採常見 US-GAAP tag 候選清單，部分公司或期間可能缺少某些指標。
- Submissions API 的 `recent` filings 足以涵蓋 2023-2024 測試案例；若要查更久以前資料，下一版可讀取歷史 submission files。
