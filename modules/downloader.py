from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import CLEAN_TEXT_DIR, PDF_DIR, RAW_HTML_DIR
from modules.html_parser import html_to_clean_text
from modules.pdf_converter import convert_html_file_to_pdf, verify_pdf_file
from modules.sec_client import SecClient, SecClientError
from modules.storage import append_download_log, safe_filename


def download_selected_filings(client: SecClient, selected: pd.DataFrame, progress_callback=None) -> pd.DataFrame:
    results: list[dict] = []
    total = len(selected)
    for position, (_, row) in enumerate(selected.iterrows(), start=1):
        ticker = row["ticker"]
        accession = row["accession_number"]
        base_name = safe_filename(f"{ticker}_{row['filing_date']}_{row['form']}_{accession}")
        html_path = RAW_HTML_DIR / f"{base_name}.html"
        text_path = CLEAN_TEXT_DIR / f"{base_name}.txt"
        pdf_path = PDF_DIR / f"{base_name}.pdf"
        download_type = str(row.get("download_type", "html")).lower()
        status = "success"
        error = ""
        url = ""
        pdf_verification = {"pdf_page_count": "", "pdf_file_size": ""}
        try:
            document = client.download_primary_document(int(row["cik"]), accession, row["primary_document"])
            url = document.url
            html_path.write_text(document.content, encoding="utf-8")
            text_path.write_text(html_to_clean_text(document.content), encoding="utf-8")
            if download_type == "pdf":
                convert_html_file_to_pdf(html_path, pdf_path)
                pdf_verification = verify_pdf_file(pdf_path)
        except Exception as exc:  # noqa: BLE001 - errors are surfaced to UI and log.
            status = "failed"
            error = str(exc)
            html_path = Path("")
            text_path = Path("")
            pdf_path = Path("")

        result = {
            **row.to_dict(),
            "status": status,
            "error": error,
            "html_url": url,
            "html_path": str(html_path) if str(html_path) else "",
            "clean_text_path": str(text_path) if str(text_path) else "",
            "pdf_path": str(pdf_path) if str(pdf_path) else "",
            **pdf_verification,
        }
        append_download_log(result)
        results.append(result)
        if progress_callback:
            progress_callback(position, total, result)
    return pd.DataFrame(results)
