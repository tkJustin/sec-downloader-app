from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from config import (
    APP_NAME,
    CLEAN_TEXT_DIR,
    DOWNLOAD_LOG_PATH,
    EXPORTS_DIR,
    METADATA_DIR,
    PDF_DIR,
    SUPPORTED_DOWNLOAD_TYPES,
    SUPPORTED_FORMS,
    TEMPLATE_PATH,
    ensure_directories,
)
from modules.analysis import build_trend_chart
from modules.downloader import download_selected_filings
from modules.financial_facts import facts_to_quarterly_dataframe
from modules.sec_client import SecClient, SecClientError
from modules.storage import append_download_log, write_csv
from modules.task_builder import build_manual_task, normalize_tasks


st.set_page_config(page_title=APP_NAME, layout="wide")
ensure_directories()


@st.cache_resource(show_spinner=False)
def get_client() -> SecClient:
    return SecClient()


def submissions_to_filings(ticker: str, cik: int, submissions: dict, form_type: str, start_year: int, end_year: int) -> pd.DataFrame:
    recent = submissions.get("filings", {}).get("recent", {})
    if not recent:
        return pd.DataFrame()
    df = pd.DataFrame(recent)
    if df.empty:
        return df
    df["ticker"] = ticker.upper()
    df["cik"] = int(cik)
    df["filing_year"] = pd.to_datetime(df["filingDate"], errors="coerce").dt.year
    df = df.loc[
        (df["form"] == form_type)
        & (df["filing_year"] >= int(start_year))
        & (df["filing_year"] <= int(end_year))
    ].copy()
    if df.empty:
        return df
    df = df.rename(
        columns={
            "accessionNumber": "accession_number",
            "filingDate": "filing_date",
            "reportDate": "report_date",
            "primaryDocument": "primary_document",
            "primaryDocDescription": "primary_doc_description",
        }
    )
    keep_cols = [
        "select",
        "ticker",
        "cik",
        "form",
        "filing_date",
        "report_date",
        "accession_number",
        "primary_document",
        "primary_doc_description",
        "download_type",
        "act",
        "fileNumber",
        "filmNumber",
    ]
    df["select"] = True
    for col in keep_cols:
        if col not in df.columns:
            df[col] = ""
    return df[keep_cols].sort_values(["ticker", "filing_date"], ascending=[True, False]).reset_index(drop=True)


def build_manifest(tasks: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    client = get_client()
    all_filings: list[pd.DataFrame] = []
    errors: list[str] = []
    for _, task in tasks.iterrows():
        ticker = str(task["ticker"]).upper()
        try:
            cik = client.ticker_to_cik(ticker)
            submissions = client.get_submissions(cik)
            filings = submissions_to_filings(
                ticker,
                cik,
                submissions,
                str(task["form_type"]).upper(),
                int(task["start_year"]),
                int(task["end_year"]),
            )
            if filings.empty:
                errors.append(f"{ticker}: no {task['form_type']} filings found for {task['start_year']}-{task['end_year']}.")
            else:
                filings["download_type"] = str(task.get("download_type", "html")).lower()
                all_filings.append(filings)
        except Exception as exc:  # noqa: BLE001 - ticker-level failures should not crash the app.
            msg = f"{ticker}: {exc}"
            errors.append(msg)
            append_download_log(
                {
                    "ticker": ticker,
                    "form": task.get("form_type", ""),
                    "status": "metadata_failed",
                    "error": str(exc),
                }
            )
    if not all_filings:
        return pd.DataFrame(), errors
    manifest = pd.concat(all_filings, ignore_index=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    write_csv(manifest.drop(columns=["select"], errors="ignore"), METADATA_DIR / f"filing_manifest_{timestamp}.csv")
    return manifest, errors


def read_uploaded_tasks(uploaded_file) -> pd.DataFrame:
    if uploaded_file is None:
        return pd.DataFrame()
    suffix = Path(uploaded_file.name).suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(uploaded_file)
    return pd.read_csv(uploaded_file)


def show_download_results(results: pd.DataFrame) -> None:
    st.subheader("Download Results")
    if results.empty:
        st.info("No download results yet.")
        return
    st.dataframe(results, use_container_width=True, hide_index=True)
    st.download_button(
        "Download manifest CSV",
        data=results.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"download_manifest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )
    success = results.loc[results["status"] == "success"]
    if not success.empty:
        labels = success.apply(lambda r: f"{r['ticker']} {r['form']} {r['filing_date']} {r['accession_number']}", axis=1)
        selected_label = st.selectbox("Preview clean text", labels.tolist())
        selected_row = success.iloc[labels.tolist().index(selected_label)]
        text_path = Path(selected_row["clean_text_path"])
        if text_path.exists():
            text = text_path.read_text(encoding="utf-8", errors="ignore")
            st.text_area("Clean text preview", text[:12000], height=360)
        pdf_path = Path(str(selected_row.get("pdf_path", "")))
        if pdf_path.exists():
            st.download_button(
                "Download selected PDF",
                data=pdf_path.read_bytes(),
                file_name=pdf_path.name,
                mime="application/pdf",
            )


def show_financial_dashboard(manifest_or_tasks: pd.DataFrame) -> None:
    st.subheader("Quarterly Financial Dashboard")
    with st.expander("Financial data diagnostics"):
        st.write(
            "For flow metrics such as Revenue, Net Income, and Operating Cash Flow, 10-K FY values are annual totals. "
            "The app now keeps reported Q1-Q3 single-quarter values and derives Q4 as FY minus Q1-Q3. "
            "Use `value_basis`, `duration_days`, `reported_value`, and `is_derived` to audit each row."
        )
    if manifest_or_tasks.empty:
        st.info("Build a manifest first to fetch financial facts.")
        return
    ticker_cik = manifest_or_tasks[["ticker", "cik"]].drop_duplicates() if "cik" in manifest_or_tasks.columns else pd.DataFrame()
    if ticker_cik.empty:
        return
    if st.button("Fetch SEC Company Facts", type="primary"):
        frames: list[pd.DataFrame] = []
        errors: list[str] = []
        client = get_client()
        with st.status("Fetching Company Facts...", expanded=True) as status:
            for _, row in ticker_cik.iterrows():
                ticker = str(row["ticker"]).upper()
                try:
                    st.write(f"Fetching {ticker}")
                    frames.append(facts_to_quarterly_dataframe(client, ticker, int(row["cik"])))
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{ticker}: {exc}")
            status.update(label="Company Facts fetch complete", state="complete")
        st.session_state["financials"] = pd.concat([f for f in frames if not f.empty], ignore_index=True) if frames else pd.DataFrame()
        st.session_state["financial_errors"] = errors

    financials = st.session_state.get("financials", pd.DataFrame())
    for error in st.session_state.get("financial_errors", []):
        st.warning(error)
    if financials.empty:
        st.info("No financial facts loaded yet.")
        return
    st.dataframe(financials, use_container_width=True, hide_index=True)
    st.download_button(
        "Download financials CSV",
        data=financials.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"quarterly_financials_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )
    metric = st.selectbox("Trend metric", sorted(financials["metric"].dropna().unique()))
    fig = build_trend_chart(financials, metric)
    if fig:
        st.plotly_chart(fig, use_container_width=True)


def main() -> None:
    st.title(APP_NAME)
    st.caption("Local SEC EDGAR filing HTML downloader, clean text converter, and Company Facts dashboard.")

    with st.sidebar:
        st.header("Input")
        input_mode = st.radio("Task source", ["Manual input", "Excel/CSV upload"], horizontal=False)
        if TEMPLATE_PATH.exists():
            st.download_button(
                "Download Excel template",
                data=TEMPLATE_PATH.read_bytes(),
                file_name=TEMPLATE_PATH.name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    if input_mode == "Manual input":
        col1, col2, col3, col4, col5 = st.columns([1.3, 1, 1, 1, 1])
        with col1:
            ticker = st.text_input(
                "Ticker(s)",
                value="AAPL",
                help="You can enter one ticker or multiple tickers separated by commas, for example: AAPL, MSFT, NVDA.",
            ).strip().upper()
            st.caption("多檔股票請用逗號分隔，例如：AAPL, MSFT, NVDA。系統會為每個 ticker 建立一筆下載任務。")
        with col2:
            form_type = st.selectbox("Form type", SUPPORTED_FORMS)
        with col3:
            start_year = st.number_input("Start year", min_value=1994, max_value=2100, value=2023)
        with col4:
            end_year = st.number_input("End year", min_value=1994, max_value=2100, value=2024)
        with col5:
            download_type = st.selectbox(
                "Download type",
                SUPPORTED_DOWNLOAD_TYPES,
                help="html 會儲存 SEC 原始 HTML 並產生 clean text；pdf 會先下載 HTML，再用瀏覽器列印方式轉成 PDF。",
            )
        raw_tasks = build_manual_task(ticker, form_type, int(start_year), int(end_year), download_type)
    else:
        uploaded = st.file_uploader("Upload task file", type=["xlsx", "xls", "csv"])
        raw_tasks = read_uploaded_tasks(uploaded) if uploaded else pd.DataFrame()
        if uploaded:
            st.dataframe(raw_tasks, use_container_width=True, hide_index=True)

    validation = normalize_tasks(raw_tasks) if not raw_tasks.empty else None
    if validation:
        for error in validation.errors:
            st.error(error)

    can_build = validation is not None and not validation.tasks.empty and not validation.errors
    if st.button("Query SEC metadata and build filing preview", type="primary", disabled=not can_build):
        with st.status("Querying SEC metadata...", expanded=True) as status:
            manifest, errors = build_manifest(validation.tasks)
            st.session_state["manifest"] = manifest
            st.session_state["metadata_errors"] = errors
            status.update(label="Metadata query complete", state="complete")

    for error in st.session_state.get("metadata_errors", []):
        st.warning(error)

    manifest = st.session_state.get("manifest", pd.DataFrame())
    st.subheader("Filing Preview")
    if manifest.empty:
        st.info("No filing preview yet. Enter tasks and query SEC metadata.")
    else:
        edited = st.data_editor(
            manifest,
            use_container_width=True,
            hide_index=True,
            column_config={"select": st.column_config.CheckboxColumn("Download", default=True)},
            disabled=[col for col in manifest.columns if col != "select"],
            key="manifest_editor",
        )
        selected = edited.loc[edited["select"]].drop(columns=["select"], errors="ignore")
        st.write(f"Selected filings: {len(selected)} / {len(edited)}")
        st.download_button(
            "Download preview manifest CSV",
            data=edited.drop(columns=["select"], errors="ignore").to_csv(index=False).encode("utf-8-sig"),
            file_name=f"filing_preview_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
        )
        if st.button("Download selected filings", disabled=selected.empty):
            progress = st.progress(0)
            latest = st.empty()

            def update_progress(done: int, total: int, result: dict) -> None:
                progress.progress(done / total)
                latest.write(f"{done}/{total}: {result['ticker']} {result['form']} {result['filing_date']} - {result['status']}")

            st.session_state["download_results"] = download_selected_filings(get_client(), selected, update_progress)
            progress.progress(1.0)
            st.success("Download step finished.")

    show_download_results(st.session_state.get("download_results", pd.DataFrame()))
    show_financial_dashboard(manifest)

    with st.expander("Local paths and logs"):
        st.write(f"Metadata: `{METADATA_DIR}`")
        st.write(f"Raw HTML: `{CLEAN_TEXT_DIR.parent / 'raw_html'}`")
        st.write(f"PDF: `{PDF_DIR}`")
        st.write(f"Clean text: `{CLEAN_TEXT_DIR}`")
        st.write(f"Exports: `{EXPORTS_DIR}`")
        st.write(f"Download log: `{DOWNLOAD_LOG_PATH}`")


if __name__ == "__main__":
    main()
