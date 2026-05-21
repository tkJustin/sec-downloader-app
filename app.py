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
from modules.storage import append_download_log, build_zip_bytes, safe_filename, write_csv
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
    success = results.loc[results["status"].isin(["success", "success_with_warnings"])]
    if not success.empty:
        labels = success.apply(lambda r: f"{r['ticker']} {r['form']} {r['filing_date']} {r['accession_number']}", axis=1)
        selected_label = st.selectbox("Preview clean text", labels.tolist())
        selected_row = success.iloc[labels.tolist().index(selected_label)]
        text_path = Path(selected_row["clean_text_path"])
        if text_path.exists():
            text = text_path.read_text(encoding="utf-8", errors="ignore")
            st.text_area("Clean text preview", text[:12000], height=360)


def _files_for_zip(results: pd.DataFrame, columns: list[str], folder: str) -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    for _, row in results.iterrows():
        ticker = safe_filename(str(row.get("ticker", "UNKNOWN")))
        filing_date = safe_filename(str(row.get("filing_date", "")))
        form = safe_filename(str(row.get("form", "")))
        accession = safe_filename(str(row.get("accession_number", "")))
        prefix = f"{ticker}_{filing_date}_{form}_{accession}"
        for column in columns:
            value = str(row.get(column, "") or "")
            if not value:
                continue
            path = Path(value)
            if path.exists():
                files.append((path, f"{folder}/{prefix}{path.suffix}"))
    return files


def build_result_zip(success: pd.DataFrame, include_clean_text: bool) -> tuple[bytes, dict[str, int]]:
    manifest_csv = success.to_csv(index=False).encode("utf-8-sig")
    html_files = _files_for_zip(success, ["html_path"], "html")
    text_files = _files_for_zip(success, ["clean_text_path"], "clean_text") if include_clean_text else []
    pdf_files = _files_for_zip(success, ["pdf_path"], "pdf")
    all_files = html_files + text_files + pdf_files
    summary = {
        "processed_filings": int(len(success)),
        "html_files": len(html_files),
        "pdf_files": len(pdf_files),
        "clean_text_files": len(text_files),
        "total_files": len(all_files),
    }
    return build_zip_bytes(all_files, manifest_csv=manifest_csv), summary


def show_zip_package_download() -> None:
    package = st.session_state.get("zip_package")
    if not package:
        return
    summary = package["summary"]
    st.subheader("ZIP Package Ready")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Processed filings", summary["processed_filings"])
    col2.metric("HTML files", summary["html_files"])
    col3.metric("PDF files", summary["pdf_files"])
    col4.metric("Clean text files", summary["clean_text_files"])
    st.download_button(
        "Download ZIP to computer",
        data=package["data"],
        file_name=package["file_name"],
        mime="application/zip",
        type="primary",
        use_container_width=True,
    )
    if package.get("warnings"):
        for warning in package["warnings"]:
            st.warning(warning)


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
            st.caption("For multiple tickers, separate them with commas. Example: AAPL, MSFT, NVDA.")
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
                help="html packages the SEC source HTML. pdf packages the SEC source HTML and browser-rendered PDF.",
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
        st.divider()
        package_col, option_col = st.columns([2, 1])
        with package_col:
            st.markdown("**Prepare selected filings as a ZIP package**")
            st.caption("The app will fetch the selected SEC filings, build the package on the server, then show one ZIP download button for your computer.")
        with option_col:
            include_clean_text = st.checkbox("Include clean text", value=True)
        if st.button("Prepare ZIP package", type="primary", disabled=selected.empty, use_container_width=True):
            progress = st.progress(0)
            latest = st.empty()

            def update_progress(done: int, total: int, result: dict) -> None:
                progress.progress(done / total)
                latest.write(f"{done}/{total}: {result['ticker']} {result['form']} {result['filing_date']} - {result['status']}")

            results = download_selected_filings(get_client(), selected, update_progress)
            st.session_state["download_results"] = results
            success = results.loc[results["status"].isin(["success", "success_with_warnings"])]
            if not success.empty:
                zip_data, summary = build_result_zip(success, include_clean_text=include_clean_text)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                st.session_state["zip_package"] = {
                    "data": zip_data,
                    "file_name": f"sec_filings_{timestamp}.zip",
                    "summary": summary,
                    "warnings": [],
                }
                failed = int((results["status"] == "failed").sum())
                if failed:
                    st.session_state["zip_package"]["warnings"].append(f"{failed} filing(s) failed. See the results table for details.")
                warnings = int((results["status"] == "success_with_warnings").sum())
                if warnings:
                    st.session_state["zip_package"]["warnings"].append(
                        f"{warnings} filing(s) were packaged with warnings, usually because PDF conversion failed on Streamlit Cloud."
                    )
            else:
                st.session_state["zip_package"] = None
            progress.progress(1.0)
            st.success("ZIP package is ready.")

    show_zip_package_download()
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
