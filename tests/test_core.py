import pandas as pd
import pytest

from app import submissions_to_filings
from modules.html_parser import html_to_clean_text
from modules.financial_facts import _build_quarterly_values, _prepare_rows
from modules.sec_client import SecClientError
from modules.task_builder import build_manual_task, normalize_tasks, parse_ticker_input


def test_normalize_tasks_accepts_template_shape():
    raw = pd.DataFrame(
        [{"ticker": "aapl", "form_type": "10-q", "start_year": 2023, "end_year": 2024, "download_type": "html"}]
    )
    result = normalize_tasks(raw)
    assert result.errors == []
    assert result.tasks.iloc[0]["ticker"] == "AAPL"
    assert result.tasks.iloc[0]["form_type"] == "10-Q"


def test_normalize_tasks_accepts_pdf_download_type():
    raw = pd.DataFrame(
        [{"ticker": "nvda", "form_type": "10-q", "start_year": 2023, "end_year": 2024, "download_type": "pdf"}]
    )
    result = normalize_tasks(raw)
    assert result.errors == []
    assert result.tasks.iloc[0]["download_type"] == "pdf"


def test_manual_task_accepts_comma_separated_tickers():
    tasks = build_manual_task("AAPL, MSFT, nvda", "10-Q", 2023, 2024, "html")
    assert tasks["ticker"].tolist() == ["AAPL", "MSFT", "NVDA"]
    assert len(tasks) == 3


def test_parse_ticker_input_ignores_empty_segments():
    assert parse_ticker_input("AAPL, , MSFT,") == ["AAPL", "MSFT"]


def test_html_to_clean_text_removes_scripts():
    text = html_to_clean_text("<html><script>bad()</script><body><h1>Title</h1><p>Revenue</p></body></html>")
    assert "bad()" not in text
    assert "Title" in text
    assert "Revenue" in text


def test_submissions_to_filings_filters_form_and_year():
    submissions = {
        "filings": {
            "recent": {
                "accessionNumber": ["0001", "0002"],
                "filingDate": ["2024-05-01", "2022-05-01"],
                "reportDate": ["2024-03-31", "2022-03-31"],
                "form": ["10-Q", "10-Q"],
                "primaryDocument": ["a.htm", "b.htm"],
                "primaryDocDescription": ["10-Q", "10-Q"],
            }
        }
    }
    filings = submissions_to_filings("AAPL", 320193, submissions, "10-Q", 2023, 2024)
    assert len(filings) == 1
    assert filings.iloc[0]["accession_number"] == "0001"


def test_invalid_ticker_error_message_shape():
    with pytest.raises(SecClientError, match="Ticker not found"):
        raise SecClientError("Ticker not found in SEC company_tickers.json: INVALIDTICKER123")


def test_flow_q4_is_derived_from_fy_less_first_three_quarters():
    raw = pd.DataFrame(
        [
            {"ticker": "AAPL", "cik": 320193, "metric": "Net Income", "tag": "NetIncomeLoss", "unit": "USD", "fy": 2024, "fp": "Q1", "form": "10-Q", "filed": "2024-02-01", "start": "2023-10-01", "end": "2023-12-30", "value": 30, "accession_number": "q1", "frame": None},
            {"ticker": "AAPL", "cik": 320193, "metric": "Net Income", "tag": "NetIncomeLoss", "unit": "USD", "fy": 2024, "fp": "Q2", "form": "10-Q", "filed": "2024-05-01", "start": "2023-12-31", "end": "2024-03-30", "value": 20, "accession_number": "q2", "frame": None},
            {"ticker": "AAPL", "cik": 320193, "metric": "Net Income", "tag": "NetIncomeLoss", "unit": "USD", "fy": 2024, "fp": "Q3", "form": "10-Q", "filed": "2024-08-01", "start": "2024-03-31", "end": "2024-06-29", "value": 10, "accession_number": "q3", "frame": None},
            {"ticker": "AAPL", "cik": 320193, "metric": "Net Income", "tag": "NetIncomeLoss", "unit": "USD", "fy": 2024, "fp": "FY", "form": "10-K", "filed": "2024-11-01", "start": "2023-10-01", "end": "2024-09-28", "value": 100, "accession_number": "fy", "frame": None},
        ]
    )
    result = _build_quarterly_values(_prepare_rows(raw))
    q4 = result.loc[(result["metric"] == "Net Income") & (result["fp"] == "Q4")].iloc[0]
    assert q4["value"] == 40
    assert q4["reported_value"] == 100
    assert q4["is_derived"]
